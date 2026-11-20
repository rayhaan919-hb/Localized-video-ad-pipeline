"""Stripe billing, GCP Veo/TTS contract checks, and live staging verification suites.

Contract & security boundary tests always execute cleanly in CI/local runs.
Live Stripe test-mode and GCP Vertex AI / Cloud TTS / GCS tests execute when
``STRIPE_STAGING_TEST=1`` or ``GCP_STAGING_TEST=1`` are explicitly enabled.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
import wave
from pathlib import Path

import httpx
import pytest
from celery.exceptions import SoftTimeLimitExceeded

import app.db as db_module
from app.auth import hash_password
from app.billing import (
    BillingConfigurationError,
    WebhookSignatureError,
    create_stripe_checkout_session,
    process_stripe_webhook,
    verify_stripe_signature,
)
from app.db import (
    User,
    Workspace,
    create_workspace_for_user,
    reconcile_workspace_credits,
    utcnow,
)
from app.scraper import UnsafeUrlError
from app.storage import validate_mp4_file
from app.tasks import PermanentJobError, is_retryable_exception
from app.tts import (
    TTSConfigurationError,
    TTSProviderError,
    generate_localized_script,
    synthesize_voiceover_wav,
)
from app.veo import VeoClient, VeoConfigurationError, VeoProviderError, VeoValidationError


@pytest.fixture
def billing_contract_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "staging_contract.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_JWT_SECRET", "staging-contract-jwt-secret-key-32ch!")
    monkeypatch.setenv("SIGNED_URL_SECRET", "staging-contract-url-secret-key-32ch!")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_staging_contract_secret_value")
    db_module.configure_database(db_url)
    db_module.init_db()
    return tmp_path


def _sign_stripe_payload(body: bytes, secret: str, ts: int | None = None) -> str:
    timestamp = int(time.time()) if ts is None else ts
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={sig}"


def test_stripe_webhook_tamper_replay_duplicate_and_refund_reconciliation(
    billing_contract_env: Path,
) -> None:
    """Verify fail-closed HMAC verification, timestamp replay guard, idempotency & refunds."""
    secret = os.environ["STRIPE_WEBHOOK_SECRET"]
    with db_module.SessionLocal() as session:
        user = User(
            id=str(uuid.uuid4()),
            email="stripe-contract@example.com",
            password_hash=hash_password("StrongStripePass123!"),
            full_name="Stripe Contract",
            is_email_verified=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(user)
        session.flush()
        ws = create_workspace_for_user(
            session,
            owner_id=user.id,
            name="Stripe Workspace",
            grant_initial_promo=True,
            promo_credits=2,
        )
        session.commit()
        ws_id = ws.id
        uid = user.id

    purchase_event = {
        "id": f"evt_purchase_{uuid.uuid4().hex[:10]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_test_{uuid.uuid4().hex[:10]}",
                "payment_status": "paid",
                "payment_intent": f"pi_{uuid.uuid4().hex[:12]}",
                "amount_total": 900,
                "currency": "usd",
                "metadata": {
                    "workspace_id": ws_id,
                    "user_id": uid,
                    "pack_id": "starter_10",
                },
            }
        },
    }
    raw_purchase = json.dumps(purchase_event).encode("utf-8")

    # 1. Tampered HMAC signature rejected
    with pytest.raises(WebhookSignatureError):
        verify_stripe_signature(raw_purchase, "t=1700000000,v1=deadbeef", secret)

    # 2. Stale timestamp (>300s) rejected even with valid HMAC
    stale_ts = int(time.time()) - 900
    stale_sig = _sign_stripe_payload(raw_purchase, secret, ts=stale_ts)
    with pytest.raises(WebhookSignatureError):
        verify_stripe_signature(raw_purchase, stale_sig, secret)

    # 3. Valid purchase webhook credits 10 credits & duplicate replay is idempotent
    valid_sig = _sign_stripe_payload(raw_purchase, secret)
    with db_module.SessionLocal() as session:
        res1 = process_stripe_webhook(session, raw_body=raw_purchase, signature_header=valid_sig)
        assert res1["status"] == "credited"
        assert res1["credit_balance"] == 12

        res2 = process_stripe_webhook(session, raw_body=raw_purchase, signature_header=valid_sig)
        assert res2["status"] == "duplicate_ignored"

    # 4. Refund reverses purchased credits cleanly and keeps ledger balanced
    pi_id = purchase_event["data"]["object"]["payment_intent"]
    refund_event = {
        "id": f"evt_refund_{uuid.uuid4().hex[:10]}",
        "type": "charge.refunded",
        "data": {
            "object": {
                "payment_intent": pi_id,
                "amount": 900,
                "amount_refunded": 900,
                "currency": "usd",
            }
        },
    }
    raw_refund = json.dumps(refund_event).encode("utf-8")
    refund_sig = _sign_stripe_payload(raw_refund, secret)
    with db_module.SessionLocal() as session:
        res_ref = process_stripe_webhook(session, raw_body=raw_refund, signature_header=refund_sig)
        assert res_ref["status"] == "refund_processed"
        assert res_ref["credits_revoked"] == 10
        assert res_ref["credit_balance"] == 2
        assert reconcile_workspace_credits(session, ws_id)["is_balanced"] is True


def test_stripe_checkout_and_gcp_clients_fail_closed_without_credentials(
    billing_contract_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure live payment/GCP calls raise configuration errors when secrets are absent."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_STARTER_10", raising=False)

    user = User(
        id=str(uuid.uuid4()),
        email="failclosed@example.com",
        password_hash=hash_password("StrongFailClosed123!"),
        full_name="Fail Closed",
        is_email_verified=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Closed WS",
        owner_id=user.id,
        credit_balance=10,
        reserved_balance=0,
        promo_granted=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    with pytest.raises(BillingConfigurationError):
        create_stripe_checkout_session(workspace=ws, user=user, pack_id="starter_10")

    monkeypatch.setenv("MOCK_VERTEX_VEO", "false")
    monkeypatch.setenv("MOCK_TTS", "false")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCS_BUCKET_NAME", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    with pytest.raises(VeoConfigurationError):
        VeoClient(mock_mode=False).generate_clip(
            job_id=str(uuid.uuid4()),
            prompt="Vertical product commercial closeup.",
            work_dir=billing_contract_env,
        )

    script_data = generate_localized_script(
        {"title": "Botanical Elixir", "brand": "Lumina"}, target_language="en"
    )
    with pytest.raises(TTSConfigurationError):
        synthesize_voiceover_wav(
            str(uuid.uuid4()),
            script_data,
            output_dir=billing_contract_env,
            mock_mode=False,
        )


def test_retryable_vs_permanent_provider_exception_classification() -> None:
    """Verify transient provider errors retry while validation/config errors fail immediately."""
    assert is_retryable_exception(VeoProviderError("Vertex HTTP 503 service unavailable")) is True
    assert is_retryable_exception(TTSProviderError("HTTP 429 rate limited")) is True
    assert is_retryable_exception(httpx.TimeoutException("timed out")) is True
    assert is_retryable_exception(SoftTimeLimitExceeded()) is True

    assert is_retryable_exception(VeoProviderError("HTTP 400 invalid argument")) is False
    assert is_retryable_exception(VeoValidationError("bad duration")) is False
    assert is_retryable_exception(VeoConfigurationError("missing credentials")) is False
    assert is_retryable_exception(UnsafeUrlError("ssrf blocked")) is False
    assert is_retryable_exception(PermanentJobError("invalid input")) is False
    assert is_retryable_exception(ValueError("bad parameter")) is False


def test_live_stripe_staging_checkout_session_creation(billing_contract_env: Path) -> None:
    """Create a real Stripe test-mode Checkout Session when STRIPE_STAGING_TEST=1."""
    if os.environ.get("STRIPE_STAGING_TEST", "").strip() != "1":
        pytest.skip("STRIPE_STAGING_TEST!=1; skipping live Stripe test-mode API call.")

    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if stripe_key.startswith("sk_live_"):
        pytest.fail("Refusing live Stripe key (sk_live_*) inside staging test suite!")
    if not stripe_key or not os.environ.get("STRIPE_PRICE_STARTER_10", "").strip():
        pytest.fail("STRIPE_SECRET_KEY (test) and STRIPE_PRICE_STARTER_10 are required.")

    user = User(
        id=str(uuid.uuid4()),
        email=f"staging-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("StagingStripePass123!"),
        full_name="Staging Stripe",
        is_email_verified=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Staging Checkout WS",
        owner_id=user.id,
        credit_balance=1,
        reserved_balance=0,
        promo_granted=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    res = create_stripe_checkout_session(workspace=ws, user=user, pack_id="starter_10")
    assert res["checkout_session_id"].startswith("cs_test_")
    assert res["checkout_url"].startswith("https://")


def test_live_gcp_staging_tts_and_veo_generation(
    billing_contract_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify real Google Cloud TTS + Vertex AI Veo + GCS delivery when GCP_STAGING_TEST=1."""
    if os.environ.get("GCP_STAGING_TEST", "").strip() != "1":
        pytest.skip("GCP_STAGING_TEST!=1; skipping live GCP Vertex Veo & Cloud TTS verification.")

    monkeypatch.setenv("MOCK_VERTEX_VEO", "false")
    monkeypatch.setenv("MOCK_TTS", "false")

    job_id = str(uuid.uuid4())
    script_data = generate_localized_script(
        {"title": "Botanical Hydrating Serum", "brand": "Lumina"}, target_language="en"
    )
    wav_path = synthesize_voiceover_wav(
        job_id,
        script_data,
        output_dir=billing_contract_env,
        mock_mode=False,
    )
    assert wav_path.exists()
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnframes() > 0
        assert wf.getframerate() >= 16000

    veo_res = VeoClient(mock_mode=False).generate_clip(
        job_id=job_id,
        prompt="Minimalist studio showcase of a botanical glass dropper bottle resting on linen.",
        target_language="en",
        work_dir=billing_contract_env,
        duration_seconds=4.0,
        aspect_ratio="9:16",
    )
    assert veo_res.mocked is False
    assert veo_res.gcs_uri.startswith("gs://")
    meta = validate_mp4_file(veo_res.local_clip_path, min_duration_seconds=1.0)
    assert meta["valid"] is True
