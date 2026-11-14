"""Core end-to-end tests for the Localized AI Video Ad Worker."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import configure_database
from app.main import app
from app.scraper import parse_product_html
from app.security import rate_limiter
from app.storage import validate_mp4_file
from app.tasks import celery_app
from app.veo import ensure_sample_fixture


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Provide isolated SQLite DB, private storage, and explicit test mock flags."""
    db_file = tmp_path / "test_video_ads.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    storage_dir = tmp_path / "storage"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-jwt-secret-key-at-least-32-chars!")
    monkeypatch.setenv("SIGNED_URL_SECRET", "test-signed-url-secret-key-32-chars!")
    monkeypatch.setenv("MOCK_VERTEX_VEO", "true")
    monkeypatch.setenv("MOCK_TTS", "true")
    monkeypatch.setenv("INITIAL_PROMO_CREDITS", "3")
    monkeypatch.setenv("CELERY_ALWAYS_EAGER", "true")
    monkeypatch.delenv("WORKER_API_KEY", raising=False)
    monkeypatch.setitem(celery_app.conf, "task_always_eager", True)
    rate_limiter.reset()
    configure_database(db_url)
    yield


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Return FastAPI TestClient with startup/shutdown lifespan hooks active."""
    with TestClient(app) as test_client:
        yield test_client


def register_and_auth(
    client: TestClient,
    email: str = "creator@example.com",
    password: str = "StrongPass123!",
    full_name: str = "Creator One",
) -> dict[str, str]:
    resp = client.post(
        "/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "workspace_id": body["primary_workspace_id"],
        "user_id": body["user"]["id"],
        "verify_token": body.get("verify_email_token", ""),
    }


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_and_mock_fixture(client: TestClient) -> None:
    """Verify /health readiness metadata and mock studio MP4 fixture helper."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["mock_vertex_veo"] is True
    assert body["mock_tts"] is True
    assert "gcp_project_id" not in body  # sensitive infra IDs not leaked publicly

    fixture = ensure_sample_fixture(duration_seconds=4.0)
    assert fixture.exists()
    meta = validate_mp4_file(fixture, require_audio=True, min_duration_seconds=3.5)
    assert meta["valid"] is True


@pytest.mark.parametrize(
    ("lang", "expected_rtl", "expected_direction", "expected_font"),
    [
        ("ur", True, "rtl", "Noto Nastaliq Urdu"),
        ("ar", True, "rtl", "Noto Sans Arabic"),
        ("hi", False, "ltr", "Noto Sans Devanagari"),
        ("en", False, "ltr", "Inter"),
    ],
)
def test_generate_video_all_languages_and_private_download(
    client: TestClient,
    lang: str,
    expected_rtl: bool,
    expected_direction: str,
    expected_font: str,
) -> None:
    """Verify end-to-end localized video generation, ledger audit, and authenticated download."""
    auth = register_and_auth(client, email=f"lang-{lang}@example.com")
    headers = _auth_headers(auth["access_token"])
    ws_id = auth["workspace_id"]

    resp = client.post(
        "/v1/videos/generate",
        headers=headers,
        json={
            "workspace_id": ws_id,
            "product_url": "https://luminabotanics.com/products/glow-niacinamide-serum",
            "target_language": lang,
            "ad_angle": "problem_solution",
            "duration_seconds": 4.0,
        },
    )
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["workspace_id"] == ws_id
    assert data["target_language"] == lang
    assert data["status"] == "COMPLETED"
    assert data["credit_balance"] == 2  # 3 signup promo - 1 finalized
    assert data["final_mp4_url"] == f"/api/v1/renders/{data['id']}"

    script = data["script_json"]
    assert script is not None
    assert script["is_rtl"] is expected_rtl
    assert script["direction"] == expected_direction
    assert script["font_family"] == expected_font
    assert script["status_history"] == [
        "CREATED",
        "QUEUED",
        "PROCESSING",
        "RENDERING",
        "COMPLETED",
    ]
    assert len(script["captions"]) == 3
    for cap in script["captions"]:
        assert cap["direction"] == expected_direction
        assert cap["end_ms"] > cap["start_ms"]

    # Unauthenticated download MUST fail; authenticated download MUST return valid MP4
    client.cookies.clear()
    unauth_dl = client.get(f"/v1/videos/{data['id']}/download")
    assert unauth_dl.status_code == 401

    auth_dl = client.get(f"/v1/videos/{data['id']}/download", headers=headers)
    assert auth_dl.status_code == 200
    assert len(auth_dl.content) > 4096
    assert b"ftyp" in auth_dl.content[:32]
    assert b"moov" in auth_dl.content

    # Signed URL download also works without cookie/bearer and expires properly
    signed = client.get(f"/v1/videos/{data['id']}/signed-url", headers=headers)
    assert signed.status_code == 200
    signed_dl = client.get(signed.json()["download_path"])
    assert signed_dl.status_code == 200
    assert signed_dl.content == auth_dl.content


def test_insufficient_credits_returns_402_and_zero_balance_stays_non_negative(
    client: TestClient,
) -> None:
    """Secondary workspace starts with 0 credits and rejects generation with HTTP 402."""
    auth = register_and_auth(client, email="nocredit@example.com")
    headers = _auth_headers(auth["access_token"])

    create_ws = client.post("/v1/workspaces", headers=headers, json={"name": "Zero Balance Client"})
    assert create_ws.status_code == 201
    zero_ws_id = create_ws.json()["id"]
    assert create_ws.json()["credit_balance"] == 0

    resp = client.post(
        "/v1/videos/generate",
        headers=headers,
        json={
            "workspace_id": zero_ws_id,
            "product_url": "https://maisonalqamar.com/products/royal-oud-parfum",
            "target_language": "ar",
        },
    )
    assert resp.status_code == 402

    ws_resp = client.get(f"/v1/workspaces/{zero_ws_id}", headers=headers)
    assert ws_resp.status_code == 200
    assert ws_resp.json()["credit_balance"] == 0


def test_pipeline_failure_refunds_credit_atomically(client: TestClient) -> None:
    """Verify failed render job sets status=FAILED and refunds reserved credit atomically."""
    auth = register_and_auth(client, email="refundtest@example.com")
    headers = _auth_headers(auth["access_token"])
    ws_id = auth["workspace_id"]

    resp = client.post(
        "/v1/videos/generate",
        headers=headers,
        json={
            "workspace_id": ws_id,
            "product_url": "https://luminabotanics.com/products/simulate-fail-item",
            "target_language": "ur",
            "simulate_failure": True,
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "FAILED"
    assert data["credit_balance"] == 3

    ws_resp = client.get(f"/v1/workspaces/{ws_id}", headers=headers)
    assert ws_resp.status_code == 200
    ws_data = ws_resp.json()
    assert ws_data["credit_balance"] == 3
    tx_types = [entry["transaction_type"] for entry in ws_data["ledger"]]
    assert "initial_promo" in tx_types
    assert "reservation" in tx_types
    assert "refund" in tx_types


def test_idempotency_key_prevents_duplicate_charge(client: TestClient) -> None:
    """Verify repeated POST /v1/videos/generate with same Idempotency-Key returns same job."""
    auth = register_and_auth(client, email="idem@example.com")
    headers = {**_auth_headers(auth["access_token"]), "Idempotency-Key": "render-req-001"}
    ws_id = auth["workspace_id"]
    payload = {
        "workspace_id": ws_id,
        "product_url": "https://aeropulse.io/products/anc-wireless-earbuds",
        "target_language": "hi",
    }

    first = client.post("/v1/videos/generate", headers=headers, json=payload)
    second = client.post("/v1/videos/generate", headers=headers, json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["credit_balance"] == 2
    assert second.json()["credit_balance"] == 2

    listing = client.get(
        f"/v1/videos?workspace_id={ws_id}", headers=_auth_headers(auth["access_token"])
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_scrape_endpoint_is_honest_without_invented_prices(client: TestClient) -> None:
    """Verify scraper never fabricates preset prices/claims and extracts real HTML accurately."""
    auth = register_and_auth(client, email="scraper@example.com")
    headers = _auth_headers(auth["access_token"])

    sample_html = """
    <html>
      <head>
        <meta property="og:title" content="Artisanal Saffron Elixir" />
        <meta property="og:site_name" content="Noor Botanicals" />
        <meta property="product:price:amount" content="199" />
        <meta property="product:price:currency" content="AED" />
        <meta property="og:image" content="https://noor.ae/img/saffron.jpg" />
      </head>
      <body>
        <ul>
          <li>Cold-pressed grade-A Khorasan saffron threads</li>
          <li>Dermatologist-reviewed lightweight facial elixir</li>
        </ul>
      </body>
    </html>
    """
    parsed = parse_product_html(sample_html, "https://noor.ae/products/saffron-elixir", "ar")
    assert parsed["title"] == "Artisanal Saffron Elixir"
    assert parsed["brand"] == "Noor Botanicals"
    assert parsed["currency"] == "AED"
    assert parsed["price"] == "AED 199"
    assert parsed["image_url"] == "https://noor.ae/img/saffron.jpg"
    assert "price" in parsed["verified_fields"]
    assert len(parsed["features"]) == 2

    # Unverified minimal HTML MUST leave price empty and flag missing_fields honestly
    minimal = parse_product_html(
        "<html><body><h1>Organic Serum</h1></body></html>", "https://noor.ae/p/1", "ur"
    )
    assert minimal["price"] == ""
    assert "price" in minimal["missing_fields"]
    assert minimal["requires_user_confirmation"] is True

    # Live call against unresolvable domain returns honest unreachable state instead of crashing
    resp = client.post(
        "/v1/products/scrape",
        headers=headers,
        json={
            "product_url": "https://nonexistent-store-xyz-12345.invalid/products/tea",
            "target_language": "ur",
        },
    )
    assert resp.status_code == 200
    scraped = resp.json()
    assert scraped["scrape_status"] == "unreachable"
    assert scraped["price"] == ""
    assert scraped["requires_user_confirmation"] is True


def test_invalid_language_rejected_with_422(client: TestClient) -> None:
    """Verify unsupported target_language is rejected cleanly by Pydantic validation."""
    auth = register_and_auth(client, email="langcheck@example.com")
    resp = client.post(
        "/v1/videos/generate",
        headers=_auth_headers(auth["access_token"]),
        json={
            "workspace_id": auth["workspace_id"],
            "product_url": "https://example.com/products/serum",
            "target_language": "fr",
        },
    )
    assert resp.status_code == 422


def test_custom_props_and_real_composited_mp4(client: TestClient, tmp_path: Path) -> None:
    """Verify custom_props override script_json and compositor outputs a valid audio+video MP4."""
    auth = register_and_auth(client, email="customprops@example.com")
    headers = _auth_headers(auth["access_token"])
    custom_props = {
        "productTitle": "Custom Studio Elixir",
        "brandName": "Atelier Noor",
        "priceDisplay": "PKR 6,200",
        "originalPriceDisplay": "PKR 8,000",
        "discountBadge": "22% OFF",
        "hookText": "ہوم اسٹوڈیو سے براہِ راست کسٹم ویڈیو ایڈ!",
        "ctaText": "ابھی آرڈر کریں",
        "captions": [
            {"id": "custom-1", "text": "پہلا کسٹم کیپشن", "highlightWord": "کسٹم"},
            {"id": "custom-2", "text": "دوسرا کسٹم کیپشن", "highlightWord": "دوسرا"},
        ],
    }

    resp = client.post(
        "/v1/videos/generate",
        headers=headers,
        json={
            "workspace_id": auth["workspace_id"],
            "product_url": "https://example.com/products/elixir",
            "target_language": "ur",
            "ad_angle": "flash_sale",
            "duration_seconds": 3.0,
            "custom_props": custom_props,
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "COMPLETED"
    script = data["script_json"]
    assert script["product_title"] == "Custom Studio Elixir"
    assert script["price_badge"] == "PKR 6,200"
    assert script["duration_ms"] == 3000

    mp4_resp = client.get(f"/v1/videos/{data['id']}/download", headers=headers)
    assert mp4_resp.status_code == 200
    tmp_mp4 = tmp_path / "downloaded.mp4"
    tmp_mp4.write_bytes(mp4_resp.content)
    meta = validate_mp4_file(tmp_mp4, require_audio=True, min_duration_seconds=2.0)
    assert meta["valid"] is True
    assert meta["has_audio"] is True
