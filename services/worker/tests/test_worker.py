"""End-to-end and unit tests for the Localized AI Video Ad Worker."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db as db_module
from app.config import DEFAULT_OWNER_ID, RENDERS_DIR
from app.db import Workspace, configure_database
from app.main import app
from app.scraper import parse_product_html
from app.veo import SAMPLE_FIXTURE_PATH, ensure_sample_fixture


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Provide an isolated SQLite database and mock Veo mode for every test."""
    db_file = tmp_path / "test_video_ads.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("MOCK_VERTEX_VEO", "true")
    configure_database(db_url)
    yield


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Return a FastAPI TestClient with lifespan hooks active."""
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_sample_fixture(client: TestClient) -> None:
    """Verify service health metadata and offline 2-second 9:16 MP4 fixture."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["veo_model"] == "veo-3.1-generate-001"
    assert body["gcp_project_id"] == "video-pipeline-514123"
    assert body["gcs_bucket"] == "gs://videosaving"
    assert body["mock_vertex_veo"] is True

    fixture = ensure_sample_fixture()
    assert fixture == SAMPLE_FIXTURE_PATH
    assert fixture.exists()
    assert fixture.stat().st_size > 2048


@pytest.mark.parametrize(
    ("lang", "expected_rtl", "expected_direction", "expected_font"),
    [
        ("ur", True, "rtl", "Noto Nastaliq Urdu"),
        ("ar", True, "rtl", "Noto Sans Arabic"),
        ("hi", False, "ltr", "Noto Sans Devanagari"),
        ("en", False, "ltr", "Inter"),
    ],
)
def test_generate_video_all_languages_and_rtl_metadata(
    client: TestClient,
    lang: str,
    expected_rtl: bool,
    expected_direction: str,
    expected_font: str,
) -> None:
    """Verify POST /v1/videos/generate across ur, ar, hi, en with atomic credit deduction."""
    workspace_id = str(uuid.uuid4())
    resp = client.post(
        "/v1/videos/generate",
        json={
            "workspace_id": workspace_id,
            "product_url": "https://luminabotanics.com/products/glow-niacinamide-serum",
            "target_language": lang,
            "ad_angle": "problem_solution",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["workspace_id"] == workspace_id
    assert data["target_language"] == lang
    assert data["status"] == "COMPLETED"
    assert data["credit_balance"] == 9
    assert data["veo_gcs_uri"] == f"gs://videosaving/jobs/{data['id']}/veo_clip_9_16.mp4"
    assert data["final_mp4_url"] == f"/static/renders/{data['id']}.mp4"

    script = data["script_json"]
    assert script is not None
    assert script["is_rtl"] is expected_rtl
    assert script["direction"] == expected_direction
    assert script["font_family"] == expected_font
    assert script["status_history"] == [
        "PENDING",
        "GENERATING_CLIPS",
        "COMPOSITING",
        "COMPLETED",
    ]
    assert len(script["captions"]) == 3
    for cap in script["captions"]:
        assert cap["direction"] == expected_direction
        assert cap["end_ms"] > cap["start_ms"]

    # Verify static MP4 file exists on disk and is downloadable via HTTP
    rendered_mp4 = RENDERS_DIR / f"{data['id']}.mp4"
    assert rendered_mp4.exists()
    assert rendered_mp4.stat().st_size > 2048

    static_resp = client.get(data["final_mp4_url"])
    assert static_resp.status_code == 200
    assert len(static_resp.content) > 2048


def test_insufficient_credits_returns_402_and_prevents_negative_balance(
    client: TestClient,
) -> None:
    """Verify atomic credit guard rejects generation with HTTP 402 when credit_balance == 0."""
    zero_ws_id = str(uuid.uuid4())
    with db_module.SessionLocal() as session:
        session.add(
            Workspace(
                id=zero_ws_id,
                owner_id=DEFAULT_OWNER_ID,
                credit_balance=0,
            )
        )
        session.commit()

    resp = client.post(
        "/v1/videos/generate",
        json={
            "workspace_id": zero_ws_id,
            "product_url": "https://maisonalqamar.com/products/royal-oud-parfum",
            "target_language": "ar",
        },
    )
    assert resp.status_code == 402
    assert "Insufficient credits" in resp.json()["detail"]

    ws_resp = client.get(f"/v1/workspaces/{zero_ws_id}")
    assert ws_resp.status_code == 200
    assert ws_resp.json()["credit_balance"] == 0


def test_pipeline_failure_refunds_credit_atomically(client: TestClient) -> None:
    """Verify failed render job sets status=FAILED and refunds +1 credit atomically."""
    ws_id = str(uuid.uuid4())
    resp = client.post(
        "/v1/videos/generate",
        json={
            "workspace_id": ws_id,
            "product_url": "https://example.com/products/simulate-fail-item",
            "target_language": "ur",
            "simulate_failure": True,
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "FAILED"
    assert data["credit_balance"] == 10
    assert "FAILED" in data["script_json"]["status_history"]

    ws_resp = client.get(f"/v1/workspaces/{ws_id}")
    assert ws_resp.status_code == 200
    ws_data = ws_resp.json()
    assert ws_data["credit_balance"] == 10
    reasons = [entry["reason"] for entry in ws_data["ledger"]]
    assert "video_render_deduction" in reasons
    assert "video_render_failed_refund" in reasons


def test_credit_checkout_and_video_listing(client: TestClient) -> None:
    """Verify credit pack checkout top-up and GET /v1/videos + GET /v1/videos/{job_id}."""
    ws_id = str(uuid.uuid4())
    with db_module.SessionLocal() as session:
        session.add(Workspace(id=ws_id, owner_id=DEFAULT_OWNER_ID, credit_balance=0))
        session.commit()

    checkout_resp = client.post(
        f"/v1/workspaces/{ws_id}/credits/checkout",
        json={"credits": 5, "pack_id": "starter_5"},
    )
    assert checkout_resp.status_code == 200
    assert checkout_resp.json()["credit_balance"] == 5

    gen_resp = client.post(
        "/v1/videos/generate",
        json={
            "workspace_id": ws_id,
            "product_url": "https://aeropulse.io/products/anc-wireless-earbuds",
            "target_language": "hi",
        },
    )
    assert gen_resp.status_code == 202
    job_id = gen_resp.json()["id"]
    assert gen_resp.json()["credit_balance"] == 4

    list_resp = client.get(f"/v1/videos?workspace_id={ws_id}")
    assert list_resp.status_code == 200
    jobs = list_resp.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id

    single_resp = client.get(f"/v1/videos/{job_id}")
    assert single_resp.status_code == 200
    assert single_resp.json()["id"] == job_id
    assert single_resp.json()["status"] == "COMPLETED"


def test_scrape_endpoint_and_html_parser(client: TestClient) -> None:
    """Verify POST /v1/products/scrape and BeautifulSoup HTML OpenGraph extraction."""
    scrape_resp = client.post(
        "/v1/products/scrape",
        json={
            "product_url": "https://zaytoon.pk/products/royal-sidr-honey",
            "target_language": "ur",
        },
    )
    assert scrape_resp.status_code == 200
    meta = scrape_resp.json()
    assert meta["currency"] == "PKR"
    assert "Sidr Honey" in meta["title"]
    assert len(meta["features"]) >= 3

    sample_html = """
    <html>
      <head>
        <meta property="og:title" content="Artisanal Saffron Elixir" />
        <meta property="og:site_name" content="Noor Botanicals" />
        <meta property="product:price:amount" content="199" />
        <meta property="product:price:currency" content="AED" />
      </head>
      <body>
        <ul>
          <li>Cold-pressed grade-A Khorasan saffron threads</li>
          <li>Clinically tested radiance booster in 7 days</li>
        </ul>
      </body>
    </html>
    """
    parsed = parse_product_html(
        sample_html,
        "https://noor.ae/products/saffron-elixir",
        target_language="ar",
    )
    assert parsed["title"] == "Artisanal Saffron Elixir"
    assert parsed["brand"] == "Noor Botanicals"
    assert parsed["currency"] == "AED"
    assert parsed["price"] == "AED 199"
    assert len(parsed["features"]) == 2


def test_invalid_language_rejected_with_422(client: TestClient) -> None:
    """Verify unsupported target_language is rejected by schema validation."""
    resp = client.post(
        "/v1/videos/generate",
        json={
            "workspace_id": str(uuid.uuid4()),
            "product_url": "https://example.com/products/serum",
            "target_language": "fr",
        },
    )
    assert resp.status_code == 422
