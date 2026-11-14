"""Comprehensive security, multi-tenant isolation, credit concurrency, Stripe, and live AI tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import sqlite3
import struct
import time
import uuid
import wave
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db as db_module
from app.config import validate_production_config
from app.db import (
    InsufficientCreditsError,
    VideoJob,
    configure_database,
    init_db,
    reserve_credit_atomically,
)
from app.main import app
from app.security import rate_limiter
from app.tasks import celery_app, recover_interrupted_jobs
from app.tts import TTSProviderError, synthesize_voiceover_wav
from app.veo import VeoClient, VeoProviderError, VeoValidationError, ensure_sample_fixture


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    db_file = tmp_path / "saas_security.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-jwt-secret-key-at-least-32-chars!")
    monkeypatch.setenv("SIGNED_URL_SECRET", "test-signed-url-secret-key-32-chars!")
    monkeypatch.setenv("MOCK_VERTEX_VEO", "true")
    monkeypatch.setenv("MOCK_TTS", "true")
    monkeypatch.setenv("INITIAL_PROMO_CREDITS", "3")
    monkeypatch.setenv("CELERY_ALWAYS_EAGER", "true")
    monkeypatch.setitem(celery_app.conf, "task_always_eager", True)
    rate_limiter.reset()
    configure_database(db_url)
    yield


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


def _register(client: TestClient, email: str, password: str = "PassWord99!") -> dict:
    resp = client.post(
        "/v1/auth/register", json={"email": email, "password": password, "full_name": email}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _sign_stripe_payload(raw_body: bytes, secret: str, ts: int | None = None) -> str:
    timestamp = int(ts if ts is not None else time.time())
    signed = f"{timestamp}.".encode("utf-8") + raw_body
    sig = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def _make_valid_wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(struct.pack("<12000h", *([500] * 12000)))
    return buf.getvalue()


def test_auth_lifecycle_verify_refresh_reuse_detection_reset_and_lockout(
    client: TestClient,
) -> None:
    """Verify account lifecycle, token rotation, replay defense, reset, and lockout."""
    reg = _register(client, "alice@example.com")
    access_1 = reg["access_token"]
    refresh_1 = reg["refresh_token"]
    verify_tok = reg["verify_email_token"]

    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {access_1}"})
    assert me.status_code == 200
    assert me.json()["user"]["is_email_verified"] is False

    ver = client.post("/v1/auth/verify-email", json={"token": verify_tok})
    assert ver.status_code == 200 and ver.json()["verified"] is True

    # Refresh rotates refresh_1 -> refresh_2
    ref = client.post("/v1/auth/refresh", json={"refresh_token": refresh_1})
    assert ref.status_code == 200
    refresh_2 = ref.json()["refresh_token"]
    assert refresh_2 != refresh_1

    # Replaying revoked refresh_1 revokes ALL sessions (including refresh_2)
    replay = client.post("/v1/auth/refresh", json={"refresh_token": refresh_1})
    assert replay.status_code == 401
    subsequent = client.post("/v1/auth/refresh", json={"refresh_token": refresh_2})
    assert subsequent.status_code == 401

    # Password reset flow
    reset_req = client.post("/v1/auth/password-reset/request", json={"email": "alice@example.com"})
    assert reset_req.status_code == 200
    reset_tok = reset_req.json()["reset_token"]
    reset_ok = client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": reset_tok, "new_password": "NewStrongPassword!1"},
    )
    assert reset_ok.status_code == 200

    old_login = client.post(
        "/v1/auth/login", json={"email": "alice@example.com", "password": "PassWord99!"}
    )
    assert old_login.status_code == 401
    new_login = client.post(
        "/v1/auth/login",
        json={"email": "alice@example.com", "password": "NewStrongPassword!1"},
    )
    assert new_login.status_code == 200

    # Brute-force lockout after 5 wrong password attempts
    rate_limiter.reset()
    for _ in range(5):
        bad = client.post(
            "/v1/auth/login", json={"email": "alice@example.com", "password": "WrongPassword!"}
        )
        assert bad.status_code == 401
    locked = client.post(
        "/v1/auth/login",
        json={"email": "alice@example.com", "password": "NewStrongPassword!1"},
    )
    assert locked.status_code == 429


def test_cross_customer_isolation_across_all_protected_endpoints(client: TestClient) -> None:
    """Mandatory 2-customer security test: Customer B cannot access Customer A's resources."""
    alice = _register(client, "tenant-a@example.com")
    bob = _register(client, "tenant-b@example.com")

    h_a = {"Authorization": f"Bearer {alice['access_token']}"}
    h_b = {"Authorization": f"Bearer {bob['access_token']}"}
    ws_a = alice["primary_workspace_id"]
    ws_b = bob["primary_workspace_id"]

    # Unauthenticated calls fail closed with 401 (clear registration cookies first)
    client.cookies.clear()
    assert client.get("/v1/videos").status_code == 401
    assert client.get(f"/v1/workspaces/{ws_a}").status_code == 401
    assert (
        client.post(
            "/v1/videos/generate",
            json={
                "workspace_id": ws_a,
                "product_url": "https://example.com/p",
                "target_language": "ur",
            },
        ).status_code
        == 401
    )

    # Alice uploads a private product image asset and renders a video
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    upload = client.post(
        f"/v1/workspaces/{ws_a}/assets",
        headers=h_a,
        files={"file": ("product.png", png_bytes, "image/png")},
    )
    assert upload.status_code == 201
    asset_a = upload.json()["id"]

    gen_a = client.post(
        "/v1/videos/generate",
        headers=h_a,
        json={
            "workspace_id": ws_a,
            "product_url": "https://example.com/products/private-item",
            "target_language": "ur",
            "custom_props": {"productImageAssetId": asset_a},
        },
    )
    assert gen_a.status_code == 202
    job_a = gen_a.json()["id"]

    # Customer B isolation assertions across every endpoint
    assert client.get("/v1/videos", headers=h_b).json() == []
    assert client.get(f"/v1/videos?workspace_id={ws_a}", headers=h_b).status_code == 403
    assert client.get(f"/v1/videos/{job_a}", headers=h_b).status_code == 403
    assert client.get(f"/v1/videos/{job_a}/download", headers=h_b).status_code == 403
    assert client.get(f"/v1/videos/{job_a}/signed-url", headers=h_b).status_code == 403
    assert client.post(f"/v1/videos/{job_a}/cancel", headers=h_b).status_code == 403
    assert client.post(f"/v1/videos/{job_a}/retry", headers=h_b).status_code == 403
    assert client.get(f"/v1/workspaces/{ws_a}", headers=h_b).status_code == 403
    assert client.get(f"/v1/assets/{asset_a}", headers=h_b).status_code == 403
    assert (
        client.post(
            "/v1/videos/generate",
            headers=h_b,
            json={
                "workspace_id": ws_a,
                "product_url": "https://example.com/p",
                "target_language": "ur",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/workspaces/{ws_a}/credits/checkout",
            headers=h_b,
            json={"pack_id": "starter_10"},
        ).status_code
        == 403
    )

    # Bob cannot reference Alice's private uploaded asset in Bob's workspace render
    bob_bad = client.post(
        "/v1/videos/generate",
        headers=h_b,
        json={
            "workspace_id": ws_b,
            "product_url": "https://example.com/products/hijack",
            "target_language": "en",
            "custom_props": {"productImageAssetId": asset_a},
        },
    )
    assert bob_bad.status_code == 202
    assert bob_bad.json()["status"] == "FAILED"  # aborted & refunded rather than leaking asset
    assert client.get(f"/v1/workspaces/{ws_b}", headers=h_b).json()["credit_balance"] == 3


def test_workspace_member_rbac_enforces_roles(client: TestClient) -> None:
    """Verify Owner/Admin/Member RBAC rules on workspace membership."""
    owner = _register(client, "owner@example.com")
    member = _register(client, "member@example.com")
    third = _register(client, "third@example.com")

    h_owner = {"Authorization": f"Bearer {owner['access_token']}"}
    h_member = {"Authorization": f"Bearer {member['access_token']}"}
    ws_id = owner["primary_workspace_id"]

    add_mem = client.post(
        f"/v1/workspaces/{ws_id}/members",
        headers=h_owner,
        json={"email": "member@example.com", "role": "member"},
    )
    assert add_mem.status_code == 201

    # Member can read workspace but CANNOT add another user
    assert client.get(f"/v1/workspaces/{ws_id}", headers=h_member).status_code == 200
    assert (
        client.post(
            f"/v1/workspaces/{ws_id}/members",
            headers=h_member,
            json={"email": "third@example.com", "role": "member"},
        ).status_code
        == 403
    )

    # Owner promotes member -> admin, admin can now invite third as member (but NOT as admin)
    promote = client.patch(
        f"/v1/workspaces/{ws_id}/members/{member['user']['id']}",
        headers=h_owner,
        json={"role": "admin"},
    )
    assert promote.status_code == 200
    invite_admin = client.post(
        f"/v1/workspaces/{ws_id}/members",
        headers=h_member,
        json={"email": "third@example.com", "role": "admin"},
    )
    assert invite_admin.status_code == 403
    invite_mem = client.post(
        f"/v1/workspaces/{ws_id}/members",
        headers=h_member,
        json={"email": third["user"]["email"], "role": "member"},
    )
    assert invite_mem.status_code == 201


def test_concurrent_credit_reservations_prevent_negative_balance(client: TestClient) -> None:
    """Ensure concurrent reservations under contention cannot overspend spendable balance."""
    reg = _register(client, "race@example.com")
    ws_id = reg["primary_workspace_id"]
    uid = reg["user"]["id"]

    # Create 6 VideoJobs in CREATED state (initial promo = 3 credits)
    job_ids: list[str] = []
    with db_module.SessionLocal() as session:
        for _ in range(6):
            jid = str(uuid.uuid4())
            session.add(
                VideoJob(
                    id=jid,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://example.com/p",
                    target_language="en",
                    status="CREATED",
                )
            )
            job_ids.append(jid)
        session.commit()

    def _try_reserve(jid: str) -> bool:
        with db_module.SessionLocal() as session:
            try:
                reserve_credit_atomically(
                    session, workspace_id=ws_id, job_id=jid, user_id=uid, cost=1
                )
                session.commit()
                return True
            except InsufficientCreditsError:
                session.rollback()
                return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_try_reserve, job_ids))

    assert sum(1 for r in results if r) == 3
    assert sum(1 for r in results if not r) == 3

    ws_resp = client.get(
        f"/v1/workspaces/{ws_id}", headers={"Authorization": f"Bearer {reg['access_token']}"}
    )
    assert ws_resp.json()["credit_balance"] == 0
    assert ws_resp.json()["reserved_balance"] == 3


def test_stripe_checkout_and_signed_webhook_idempotency_and_refund(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Stripe checkout creation, HMAC signature verification, dedup, and refund."""
    reg = _register(client, "buyer@example.com")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws_id = reg["primary_workspace_id"]

    # Without Stripe config -> 503 fail-closed
    unconf = client.post(
        f"/v1/workspaces/{ws_id}/credits/checkout",
        headers=headers,
        json={"pack_id": "starter_10"},
    )
    assert unconf.status_code == 503

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_mock_server_key")
    monkeypatch.setenv("STRIPE_PRICE_STARTER_10", "price_starter_10_live")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret_value_12345")

    # Mock outgoing Stripe Checkout API call and verify server sets pack/price/metadata
    captured_form: dict = {}
    orig_post = httpx.Client.post

    class _FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "cs_test_123", "url": "https://checkout.stripe.com/c/pay/cs_test_123"}

    def _fake_post(self, url, **kwargs):
        if "api.stripe.com" in str(url):
            captured_form.update(kwargs.get("data") or {})
            return _FakeResp()
        return orig_post(self, url, **kwargs)

    with patch.object(httpx.Client, "post", _fake_post):
        checkout = client.post(
            f"/v1/workspaces/{ws_id}/credits/checkout",
            headers=headers,
            json={"pack_id": "starter_10"},
        )
    assert checkout.status_code == 200
    assert checkout.json()["checkout_url"] == "https://checkout.stripe.com/c/pay/cs_test_123"
    assert captured_form["line_items[0][price]"] == "price_starter_10_live"
    assert captured_form["metadata[workspace_id]"] == ws_id

    # Admin topup blocked for non-admin; dev-topup blocked unless explicitly enabled
    assert (
        client.post(
            f"/v1/workspaces/{ws_id}/credits/admin-adjust",
            headers=headers,
            json={"delta": 50, "reason": "Unauthorized escalation test"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/workspaces/{ws_id}/credits/dev-topup",
            headers=headers,
            json={"pack_id": "starter_10"},
        ).status_code
        == 403
    )

    # Signed Stripe webhook payload
    paid_event = {
        "id": "evt_paid_001",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "payment_intent": "pi_001",
                "payment_status": "paid",
                "amount_total": 900,
                "currency": "usd",
                "client_reference_id": ws_id,
                "metadata": {
                    "workspace_id": ws_id,
                    "user_id": reg["user"]["id"],
                    "pack_id": "starter_10",
                },
            }
        },
    }
    raw_paid = json.dumps(paid_event).encode("utf-8")

    # Bad signature, missing header, tampered amount, and stale timestamp rejected
    assert (
        client.post(
            "/v1/billing/webhooks/stripe",
            content=raw_paid,
            headers={"Stripe-Signature": "t=123,v1=deadbeef"},
        ).status_code
        == 400
    )
    stale_sig = _sign_stripe_payload(
        raw_paid, "whsec_test_secret_value_12345", ts=int(time.time()) - 1000
    )
    assert (
        client.post(
            "/v1/billing/webhooks/stripe", content=raw_paid, headers={"Stripe-Signature": stale_sig}
        ).status_code
        == 400
    )

    tampered = dict(paid_event)
    tampered["data"] = {"object": {**paid_event["data"]["object"], "amount_total": 100}}
    tampered_bytes = json.dumps(tampered).encode("utf-8")
    tamper_sig = _sign_stripe_payload(tampered_bytes, "whsec_test_secret_value_12345")
    assert (
        client.post(
            "/v1/billing/webhooks/stripe",
            content=tampered_bytes,
            headers={"Stripe-Signature": tamper_sig},
        ).status_code
        == 400
    )

    # Valid signature grants +10 credits (3 promo -> 13)
    good_sig = _sign_stripe_payload(raw_paid, "whsec_test_secret_value_12345")
    ok_hook = client.post(
        "/v1/billing/webhooks/stripe", content=raw_paid, headers={"Stripe-Signature": good_sig}
    )
    assert ok_hook.status_code == 200
    assert ok_hook.json()["credit_balance"] == 13

    # Duplicate delivery is idempotent and does NOT double-credit
    dup_hook = client.post(
        "/v1/billing/webhooks/stripe", content=raw_paid, headers={"Stripe-Signature": good_sig}
    )
    assert dup_hook.status_code == 200
    assert dup_hook.json()["status"] == "duplicate_ignored"
    assert client.get(f"/v1/workspaces/{ws_id}", headers=headers).json()["credit_balance"] == 13

    # charge.refunded revokes purchased credits cleanly
    refund_event = {
        "id": "evt_refund_001",
        "type": "charge.refunded",
        "data": {"object": {"payment_intent": "pi_001", "amount": 900, "amount_refunded": 900}},
    }
    refund_raw = json.dumps(refund_event).encode("utf-8")
    refund_sig = _sign_stripe_payload(refund_raw, "whsec_test_secret_value_12345")
    ref_hook = client.post(
        "/v1/billing/webhooks/stripe", content=refund_raw, headers={"Stripe-Signature": refund_sig}
    )
    assert ref_hook.status_code == 200
    assert ref_hook.json()["credits_revoked"] == 10
    assert ref_hook.json()["credit_balance"] == 3


def test_production_startup_validation_blocks_unsafe_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify validate_production_config() aborts if mocks, SQLite, or weak secrets exist."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MOCK_VERTEX_VEO", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///local.db")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    monkeypatch.delenv("WORKER_API_KEY", raising=False)
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        validate_production_config()
    msg = str(exc_info.value)
    assert "MOCK_VERTEX_VEO" in msg
    assert "DATABASE_URL" in msg
    assert "WORKER_API_KEY" in msg
    assert "AUTH_JWT_SECRET" in msg
    assert "CORS_ORIGINS" in msg


def test_veo_live_mode_gcs_download_and_cloud_tts_strict_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify live Veo downloads MP4s from GCS without fake fixture/oscillator fallbacks."""
    monkeypatch.setenv("MOCK_VERTEX_VEO", "false")
    monkeypatch.setenv("MOCK_TTS", "false")
    monkeypatch.setenv("GCP_PROJECT_ID", "proj-123")
    monkeypatch.setenv("GCS_BUCKET", "gs://prod-bucket")
    monkeypatch.setenv("VERTEX_ACCESS_TOKEN", "ya29.fake-oauth-token")

    client = VeoClient()
    # Parameter validation
    with pytest.raises(VeoValidationError):
        client.generate_clip("j1", "abc", duration_seconds=4)  # prompt < 5 chars fails
    with pytest.raises(VeoValidationError):
        client.generate_clip(
            "j1", "Valid detailed commercial prompt", duration_seconds=2
        )  # invalid live Veo dur 2s

    sample_bytes = ensure_sample_fixture(duration_seconds=4.0).read_bytes()
    captured_requests: list[tuple[str, dict]] = []

    class _MockResp:
        def __init__(self, status_code: int, json_data: dict | None = None, content: bytes = b""):
            self.status_code = status_code
            self._json = json_data or {}
            self.content = content
            self.text = ""

        def json(self):
            return self._json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def _mock_post(self, url, **kwargs):
        captured_requests.append((url, kwargs.get("json") or {}))
        if ":predictLongRunning" in url:
            return _MockResp(200, {"name": "projects/proj-123/operations/op-1"})
        if ":fetchPredictOperation" in url:
            return _MockResp(
                200,
                {
                    "done": True,
                    "response": {
                        "videos": [{"gcsUri": "gs://prod-bucket/workspaces/ws/jobs/j1/out.mp4"}]
                    },
                },
            )
        # Simulated Cloud TTS failure
        return _MockResp(500, {"error": "TTS backend down"})

    def _mock_get(self, url, **kwargs):
        assert "storage.googleapis.com/storage/v1/b/prod-bucket/o/" in url
        return _MockResp(200, content=sample_bytes)

    with (
        patch.object(httpx.Client, "post", _mock_post),
        patch.object(httpx.Client, "get", _mock_get),
    ):
        res = client.generate_clip(
            job_id="j1",
            prompt="Luxury perfume showcase in warm golden sunlight",
            work_dir=tmp_path / "work",
            duration_seconds=4.0,
            product_image_bytes=b"\x89PNG\r\n\x1a\n\x00\x00",
            product_image_mime="image/png",
        )
        assert res.mocked is False
        assert res.local_clip_path.exists()
        assert res.gcs_uri.endswith("out.mp4")
        # Confirm product reference image attached to Vertex Veo payload
        predict_payload = captured_requests[0][1]
        assert predict_payload["instances"][0]["image"]["mimeType"] == "image/png"

        # Cloud TTS MUST raise TTSProviderError on 500 instead of generating sine audio!
        with pytest.raises(TTSProviderError):
            synthesize_voiceover_wav(
                "j1",
                {"target_language": "en", "tts_text": "Real voiceover narration."},
                output_dir=tmp_path,
            )

    # Confirm Veo fails loudly when GCS download fails (never copies dummy fixture!)
    def _mock_get_fail(self, url, **kwargs):
        return _MockResp(403, content=b"forbidden")

    with (
        patch.object(httpx.Client, "post", _mock_post),
        patch.object(httpx.Client, "get", _mock_get_fail),
    ):
        with pytest.raises(VeoProviderError):
            client.generate_clip(
                job_id="j2",
                prompt="Luxury perfume showcase in warm sunlight",
                work_dir=tmp_path / "work2",
                duration_seconds=4.0,
            )

    # Confirm Cloud TTS succeeds cleanly when valid base64 LINEAR16 WAV is returned
    wav_b64 = base64.b64encode(_make_valid_wav_bytes()).decode("ascii")

    def _mock_tts_ok(self, url, **kwargs):
        return _MockResp(200, {"audioContent": wav_b64})

    with patch.object(httpx.Client, "post", _mock_tts_ok):
        wav_path = synthesize_voiceover_wav(
            "j_ok",
            {"target_language": "en", "tts_text": "Valid narration output."},
            output_dir=tmp_path,
        )
        assert wav_path.exists() and wav_path.stat().st_size > 1000


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://127.0.0.1:8000/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://localhost:5432/",
    ],
)
def test_ssrf_targets_and_invalid_image_upload_blocked(
    client: TestClient,
    bad_url: str,
) -> None:
    """Verify SSRF blocklist rejects internal URLs and upload checks reject non-images."""
    reg = _register(client, "ssrf@example.com")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws_id = reg["primary_workspace_id"]

    resp = client.post(
        "/v1/products/scrape",
        headers=headers,
        json={"product_url": bad_url, "target_language": "en"},
    )
    assert resp.status_code == 400

    bad_upload = client.post(
        f"/v1/workspaces/{ws_id}/assets",
        headers=headers,
        files={"file": ("shell.png", b"<?php system($_GET['cmd']); ?>", "image/png")},
    )
    assert bad_upload.status_code == 400


def test_job_cancellation_and_worker_recovery_refund_credits(client: TestClient) -> None:
    """Verify job cancellation and startup recovery for interrupted jobs refund credits cleanly."""
    reg = _register(client, "recover@example.com")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    ws_id = reg["primary_workspace_id"]
    uid = reg["user"]["id"]

    # Insert an interrupted PROCESSING job with reserved credit
    jid = str(uuid.uuid4())
    with db_module.SessionLocal() as session:
        session.add(
            VideoJob(
                id=jid,
                workspace_id=ws_id,
                user_id=uid,
                product_url="https://example.com/p",
                target_language="ur",
                status="PROCESSING",
                reserved_credits=1,
            )
        )
        session.flush()
        reserve_credit_atomically(session, workspace_id=ws_id, job_id=jid, user_id=uid, cost=1)
        session.commit()

    # Cancel endpoint refunds cleanly
    cancel_resp = client.post(f"/v1/videos/{jid}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"
    assert cancel_resp.json()["credit_balance"] == 3

    # Test startup recovery for an interrupted RENDERING job
    jid2 = str(uuid.uuid4())
    with db_module.SessionLocal() as session:
        session.add(
            VideoJob(
                id=jid2,
                workspace_id=ws_id,
                user_id=uid,
                product_url="https://example.com/p2",
                target_language="ar",
                status="RENDERING",
                reserved_credits=1,
            )
        )
        session.flush()
        reserve_credit_atomically(session, workspace_id=ws_id, job_id=jid2, user_id=uid, cost=1)
        session.commit()

    recovered = recover_interrupted_jobs()
    assert recovered == 1
    assert client.get(f"/v1/workspaces/{ws_id}", headers=headers).json()["credit_balance"] == 3


def test_v1_sqlite_database_non_destructive_upgrade(tmp_path: Path) -> None:
    """Verify init_db() upgrades legacy v1 SQLite database preserving existing rows safely."""
    legacy_db = tmp_path / "legacy_v1.db"
    conn = sqlite3.connect(legacy_db)
    ws_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    conn.executescript(
        f"""
        CREATE TABLE workspaces (
          id CHAR(36) PRIMARY KEY,
          owner_id CHAR(36) NOT NULL,
          credit_balance INTEGER NOT NULL DEFAULT 10,
          created_at TIMESTAMP NOT NULL
        );
        CREATE TABLE video_jobs (
          id CHAR(36) PRIMARY KEY,
          workspace_id CHAR(36) NOT NULL,
          product_url TEXT NOT NULL,
          target_language VARCHAR(8) NOT NULL CHECK (target_language IN ('ur', 'ar', 'hi', 'en')),
          script_json TEXT,
          veo_gcs_uri TEXT,
          final_mp4_url TEXT,
          status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (
            status IN ('PENDING', 'GENERATING_CLIPS', 'COMPOSITING', 'COMPLETED', 'FAILED')
          ),
          created_at TIMESTAMP NOT NULL
        );
        CREATE TABLE credit_ledger (
          id CHAR(36) PRIMARY KEY,
          workspace_id CHAR(36) NOT NULL,
          job_id CHAR(36),
          delta INTEGER NOT NULL,
          reason TEXT NOT NULL,
          balance_after INTEGER NOT NULL,
          created_at TIMESTAMP NOT NULL
        );
        INSERT INTO workspaces VALUES ('{ws_id}', '{owner_id}', 7, '2025-01-01 00:00:00');
        INSERT INTO video_jobs VALUES (
          '{job_id}', '{ws_id}', 'https://legacy.store/p', 'ur', '{{}}',
          NULL, NULL, 'COMPLETED', '2025-01-01 00:00:00'
        );
        """
    )
    conn.commit()
    conn.close()

    configure_database(f"sqlite:///{legacy_db.as_posix()}")
    init_db()

    with db_module.SessionLocal() as session:
        migrated_job = session.get(VideoJob, job_id)
        assert migrated_job is not None
        assert migrated_job.product_url == "https://legacy.store/p"
        assert migrated_job.progress_pct == 0
