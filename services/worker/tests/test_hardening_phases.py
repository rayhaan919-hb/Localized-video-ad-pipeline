"""Regression tests for Enterprise Hardening Phases 2-11."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

import app.db as db_module
from app.config import validate_production_config
from app.db import (
    AuthSession,
    CreditLedger,
    StripeEvent,
    VideoJob,
    Workspace,
    acquire_job_lease,
    reconcile_workspace_credits,
    renew_job_lease,
    reserve_credit_atomically,
    utcnow,
)
from app.main import app
from app.scraper import (
    ScraperError,
    SSRFSafeNetworkBackend,
    UnsafeUrlError,
    _fetch_with_ssrf_redirects,
    validate_public_http_url,
)
from app.security import DistributedRateLimiter, SharedRateLimitStore, rate_limiter
from app.tasks import (
    PermanentJobError,
    TransientJobError,
    _LeaseHeartbeatThread,
    celery_app,
    compute_retry_countdown,
    configure_celery_app,
    process_video_job,
    recover_interrupted_jobs,
)
from app.veo import (
    VeoClient,
    VeoConfigurationError,
    VeoGenerationResult,
    VeoProviderError,
    ensure_sample_fixture,
)


@pytest.fixture(autouse=True)
def isolated_hardening_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_file = tmp_path / "hardening.db"
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
    monkeypatch.setenv("REQUIRE_REDIS_BROKER", "false")
    monkeypatch.setenv("REQUIRE_ACTIVE_CELERY_WORKER", "false")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    monkeypatch.delenv("WORKER_API_KEY", raising=False)
    configure_celery_app(celery_app)
    rate_limiter.reset()
    db_module.configure_database(db_url)
    db_module.init_db()
    yield
    configure_celery_app(celery_app)
    rate_limiter.reset()


def _register_user(client: TestClient, email: str, password: str = "StrongPass123!") -> dict:
    res = client.post(
        "/v1/auth/register",
        json={"email": email, "password": password, "full_name": email.split("@")[0]},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _sign_stripe_payload(payload: dict, secret: str) -> tuple[bytes, str]:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ts = int(time.time())
    signed = f"{ts}.".encode("utf-8") + raw
    sig = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return raw, f"t={ts},v1={sig}"


def test_phase2_background_job_reliability_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify prod refuses eager/memory fallback, Redis outages return 503, and retries work."""
    # 1. Production forbids CELERY_ALWAYS_EAGER=true and unreachable/missing Redis
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CELERY_ALWAYS_EAGER", "true")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/9")
    with pytest.raises(RuntimeError) as prod_err:
        validate_production_config()
    assert "CELERY_ALWAYS_EAGER" in str(prod_err.value)
    assert "REDIS_URL" in str(prod_err.value)
    with pytest.raises(RuntimeError):
        configure_celery_app(celery_app)

    monkeypatch.setenv("CELERY_ALWAYS_EAGER", "false")
    cfg = configure_celery_app(celery_app)
    assert cfg["task_always_eager"] is False
    assert cfg["broker_url"] == "redis://127.0.0.1:6399/9"

    # Restore test mode
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CELERY_ALWAYS_EAGER", "true")
    configure_celery_app(celery_app)

    # 2. Redis down during /v1/videos/generate returns 503 and refunds reserved credit atomically
    with TestClient(app) as client:
        reg = _register_user(client, "redisdown@example.com")
        headers = {"Authorization": f"Bearer {reg['access_token']}"}
        ws_id = reg["primary_workspace_id"]

        monkeypatch.setenv("REQUIRE_REDIS_BROKER", "true")
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/9")
        outage_res = client.post(
            "/v1/videos/generate",
            headers=headers,
            json={
                "workspace_id": ws_id,
                "product_url": "https://luminabotanics.com/products/serum",
                "target_language": "en",
            },
        )
        assert outage_res.status_code == 503
        ws_after = client.get(f"/v1/workspaces/{ws_id}", headers=headers).json()
        assert ws_after["credit_balance"] == 3
        assert ws_after["reserved_balance"] == 0
        monkeypatch.setenv("REQUIRE_REDIS_BROKER", "false")

        # 3. Backoff + jitter bounds check
        delays = [compute_retry_countdown(1, base_delay=2.0, max_delay=30.0) for _ in range(10)]
        assert all(2.0 <= d <= 4.0 for d in delays)
        assert len(set(delays)) > 1

        # 4. Transient AI timeout triggers retry with backoff and succeeds without double charge
        sample_clip = ensure_sample_fixture(duration_seconds=4.0)
        attempts = {"count": 0}

        def _flaky_veo(self, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise TransientJobError("Vertex AI gateway timeout (transient 503)")
            dest = Path(kwargs["work_dir"]) / f"{kwargs['job_id']}.mp4"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(sample_clip.read_bytes())
            return VeoGenerationResult(
                job_id=kwargs["job_id"],
                model="veo-3.1-generate-001",
                gcs_uri="gs://mock/retry-ok.mp4",
                local_clip_path=dest,
                mocked=True,
                duration_seconds=4.0,
            )

        with patch.object(VeoClient, "generate_clip", _flaky_veo):
            retry_ok = client.post(
                "/v1/videos/generate",
                headers=headers,
                json={
                    "workspace_id": ws_id,
                    "product_url": "https://luminabotanics.com/products/retry-serum",
                    "target_language": "en",
                },
            )
            assert retry_ok.status_code == 202
            data = retry_ok.json()
            assert data["status"] == "COMPLETED"
            assert attempts["count"] == 2
            assert data["credit_balance"] == 2

        with db_module.SessionLocal() as session:
            job_row = session.get(VideoJob, data["id"])
            assert job_row is not None
            assert job_row.retry_count == 1
            assert reconcile_workspace_credits(session, ws_id)["is_balanced"] is True

        # 5. Permanent error fails immediately without retries and refunds credit
        monkeypatch.setenv("JOB_MAX_RETRIES", "2")
        perm_attempts = {"count": 0}

        def _perm_fail(self, **kwargs):
            perm_attempts["count"] += 1
            raise PermanentJobError("Invalid Veo safety policy violation")

        with patch.object(VeoClient, "generate_clip", _perm_fail):
            perm_res = client.post(
                "/v1/videos/generate",
                headers=headers,
                json={
                    "workspace_id": ws_id,
                    "product_url": "https://luminabotanics.com/products/bad-item",
                    "target_language": "en",
                },
            )
            assert perm_res.status_code == 202
            assert perm_res.json()["status"] == "FAILED"
            assert perm_attempts["count"] == 1
            assert perm_res.json()["credit_balance"] == 2

        # 6. Exhausted transient retries mark FAILED and refund once
        exhaust_attempts = {"count": 0}

        def _always_timeout(self, **kwargs):
            exhaust_attempts["count"] += 1
            raise TransientJobError("Persistent upstream 504 timeout")

        with patch.object(VeoClient, "generate_clip", _always_timeout):
            ex_res = client.post(
                "/v1/videos/generate",
                headers=headers,
                json={
                    "workspace_id": ws_id,
                    "product_url": "https://luminabotanics.com/products/timeout-item",
                    "target_language": "en",
                },
            )
            assert ex_res.status_code == 202
            assert ex_res.json()["status"] == "FAILED"
            assert exhaust_attempts["count"] == 3
            assert ex_res.json()["credit_balance"] == 2

        # 7. Duplicate delivery for COMPLETED job is skipped safely
        dup_out = process_video_job(job_id=data["id"], worker_id="dup-worker")
        assert dup_out["skipped_duplicate"] is True
        assert dup_out["status"] == "COMPLETED"


def test_phase3_leases_heartbeats_fencing_and_safe_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify leases prevent premature reclaim, heartbeats renew, and stale workers are fenced."""
    with TestClient(app) as client:
        reg = _register_user(client, "leases@example.com")
        ws_id = reg["primary_workspace_id"]
        uid = reg["user"]["id"]

        # 1. Active unexpired lease with old updated_at is NEVER reclaimed
        active_jid = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=active_jid,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/long-job",
                    target_language="ur",
                    status="PROCESSING",
                    worker_id="worker-alive",
                    fencing_token=1,
                    heartbeat_at=utcnow(),
                    lease_expires_at=utcnow() + timedelta(seconds=120),
                    updated_at=utcnow() - timedelta(hours=3),
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=active_jid, user_id=uid, cost=1
            )
            session.commit()

        assert recover_interrupted_jobs(min_age_seconds=0) == 0

        # 2. Competing worker cannot steal an active unexpired lease
        with db_module.SessionLocal() as session:
            assert (
                acquire_job_lease(
                    session, job_id=active_jid, worker_id="worker-intruder", lease_seconds=60
                )
                is None
            )
            old_exp = session.get(VideoJob, active_jid).lease_expires_at
            assert renew_job_lease(
                session,
                job_id=active_jid,
                worker_id="worker-alive",
                fencing_token=1,
                lease_seconds=240,
            )
            session.commit()
            session.expire_all()
            assert session.get(VideoJob, active_jid).lease_expires_at > old_exp

        # 3. Background heartbeat thread renews lease cleanly
        hb = _LeaseHeartbeatThread(
            job_id=active_jid,
            worker_id="worker-alive",
            fencing_token=1,
            lease_seconds=300,
            interval_seconds=0.05,
        )
        hb.start()
        time.sleep(0.18)
        hb.stop()
        assert hb.lease_lost is False

        # 4. Crashed worker with expired lease IS reclaimed once and never double-refunded
        crashed_jid = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=crashed_jid,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/crashed-job",
                    target_language="ar",
                    status="RENDERING",
                    worker_id="worker-dead",
                    fencing_token=1,
                    heartbeat_at=utcnow() - timedelta(minutes=10),
                    lease_expires_at=utcnow() - timedelta(seconds=5),
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=crashed_jid, user_id=uid, cost=1
            )
            session.commit()

        assert recover_interrupted_jobs(min_age_seconds=900) == 1
        assert recover_interrupted_jobs(min_age_seconds=0) == 0

        with db_module.SessionLocal() as session:
            recovered_job = session.get(VideoJob, crashed_jid)
            assert recovered_job is not None
            assert recovered_job.status == "FAILED"
            assert recovered_job.error_code == "WORKER_LEASE_EXPIRED"
            assert recovered_job.fencing_token == 2
            assert recovered_job.worker_id is None
            assert session.get(Workspace, ws_id).credit_balance == 2

        # 5. Stale worker attempting to mutate/complete after recovery is fenced out
        fenced_jid = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=fenced_jid,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/fenced-job",
                    target_language="en",
                    status="QUEUED",
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=fenced_jid, user_id=uid, cost=1
            )
            session.commit()

        sample_clip = ensure_sample_fixture(duration_seconds=4.0)

        def _slow_veo_gets_recovered(self, **kwargs):
            # Force lease expiration & recovery while worker is paused in external AI call
            with db_module.SessionLocal() as inner_s:
                inner_job = inner_s.get(VideoJob, fenced_jid)
                assert inner_job is not None
                inner_job.lease_expires_at = utcnow() - timedelta(seconds=2)
                inner_s.commit()
            assert recover_interrupted_jobs(min_age_seconds=0) == 1
            dest = Path(kwargs["work_dir"]) / f"{kwargs['job_id']}.mp4"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(sample_clip.read_bytes())
            return VeoGenerationResult(
                job_id=kwargs["job_id"],
                model="veo-3.1-generate-001",
                gcs_uri="gs://mock/late.mp4",
                local_clip_path=dest,
                mocked=True,
                duration_seconds=4.0,
            )

        with patch.object(VeoClient, "generate_clip", _slow_veo_gets_recovered):
            res = process_video_job(job_id=fenced_jid, worker_id="stale-worker")
            assert res.get("fenced") is True
            assert res["status"] == "FAILED"

        with db_module.SessionLocal() as session:
            fenced_row = session.get(VideoJob, fenced_jid)
            assert fenced_row is not None
            assert fenced_row.status == "FAILED"
            ws_check = reconcile_workspace_credits(session, ws_id)
            assert ws_check["is_balanced"] is True
            assert ws_check["credit_balance"] == 2


def test_phase4_distributed_multi_instance_rate_limiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify multi-instance shared counter enforcement and 429 + Retry-After across categories."""
    shared_store = SharedRateLimitStore()
    inst_a = DistributedRateLimiter(shared_store=shared_store)
    inst_b = DistributedRateLimiter(shared_store=shared_store)
    assert inst_a.backend_mode == "shared_store"

    # 3 hits on instance A + 2 hits on instance B exhaust a limit of 5 globally
    assert inst_a.check("api", "user-42", limit=5, window_seconds=60)[0] is True
    assert inst_b.check("api", "user-42", limit=5, window_seconds=60)[0] is True
    assert inst_a.check("api", "user-42", limit=5, window_seconds=60)[0] is True
    assert inst_b.check("api", "user-42", limit=5, window_seconds=60)[0] is True
    assert inst_a.check("api", "user-42", limit=5, window_seconds=60)[0] is True

    allowed_6, retry_6 = inst_b.check("api", "user-42", limit=5, window_seconds=60)
    assert allowed_6 is False
    assert retry_6 >= 1

    # Burst protection test
    burst_d1 = inst_a.check_with_metadata(
        "generate", "user-99", limit=20, window_seconds=60, burst_limit=2, burst_window_seconds=10
    )
    burst_d2 = inst_b.check_with_metadata(
        "generate", "user-99", limit=20, window_seconds=60, burst_limit=2, burst_window_seconds=10
    )
    burst_d3 = inst_a.check_with_metadata(
        "generate", "user-99", limit=20, window_seconds=60, burst_limit=2, burst_window_seconds=10
    )
    assert burst_d1.allowed is True
    assert burst_d2.allowed is True
    assert burst_d3.allowed is False
    assert burst_d3.retry_after >= 1

    # Endpoint rate limits return 429 + Retry-After across category limits
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_SCRAPE_PER_MINUTE", "1")
    monkeypatch.setenv("RATE_LIMIT_BILLING_PER_MINUTE", "1")
    monkeypatch.setenv("RATE_LIMIT_DOWNLOAD_PER_MINUTE", "1")
    rate_limiter.reset()

    with TestClient(app) as client:
        reg = _register_user(client, "ratelimit@example.com")
        headers = {"Authorization": f"Bearer {reg['access_token']}"}
        ws_id = reg["primary_workspace_id"]

        for _ in range(2):
            r = client.post(
                "/v1/auth/login",
                json={"email": "ratelimit@example.com", "password": "wrong-password"},
            )
            assert r.status_code == 401
        login_429 = client.post(
            "/v1/auth/login",
            json={"email": "ratelimit@example.com", "password": "wrong-password"},
        )
        assert login_429.status_code == 429
        assert "Retry-After" in login_429.headers

        r_scrape_1 = client.post(
            "/v1/products/scrape",
            headers=headers,
            json={"product_url": "https://nonexistent-rl.invalid/p", "target_language": "en"},
        )
        assert r_scrape_1.status_code == 200
        r_scrape_2 = client.post(
            "/v1/products/scrape",
            headers=headers,
            json={"product_url": "https://nonexistent-rl.invalid/p", "target_language": "en"},
        )
        assert r_scrape_2.status_code == 429
        assert "Retry-After" in r_scrape_2.headers

        # Billing checkout & signed-url download limits also enforce 429 + Retry-After
        co1 = client.post(
            f"/v1/workspaces/{ws_id}/credits/checkout",
            headers=headers,
            json={"pack_id": "starter_10"},
        )
        assert co1.status_code == 503
        co2 = client.post(
            f"/v1/workspaces/{ws_id}/credits/checkout",
            headers=headers,
            json={"pack_id": "starter_10"},
        )
        assert co2.status_code == 429
        assert "Retry-After" in co2.headers

        fake_jid = str(uuid.uuid4())
        dl1 = client.get(f"/v1/videos/{fake_jid}/signed-url", headers=headers)
        assert dl1.status_code == 404
        dl2 = client.get(f"/v1/videos/{fake_jid}/signed-url", headers=headers)
        assert dl2.status_code == 429
        assert "Retry-After" in dl2.headers


def test_phase5_ssrf_dns_rebinding_redirects_and_stream_caps() -> None:
    """Verify SSRF blocks private/obfuscated IPs, DNS rebinding, redirects, and size caps."""
    blocked_urls = [
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://127.1/",
        "file:///etc/passwd",
        "ftp://shop.example.com/file",
        "https://user:secret@shop.example.com/p",
        "https://shop.example.com:5432/db",
    ]
    for url in blocked_urls:
        with pytest.raises(UnsafeUrlError):
            validate_public_http_url(url)

    # DNS rebinding #1: SSRFSafeNetworkBackend refuses connect if resolution swaps to 127.0.0.1
    backend = SSRFSafeNetworkBackend(allow_private_in_test=False)
    with patch(
        "app.scraper.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    ):
        with pytest.raises(UnsafeUrlError):
            backend.connect_tcp("rebind.attacker.example", 80)

    # DNS rebinding #2: pinned IP connects ONLY to initial public IP, never swapped private IP
    connected_targets: list[str] = []

    class _FakeStream:
        pass

    dns_calls = {"n": 0}

    def _rebinding_getaddrinfo(host, port, *args, **kwargs):
        dns_calls["n"] += 1
        ip = "93.184.216.34" if dns_calls["n"] == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]

    pinned_cache: dict[tuple[str, int], list[str]] = {}
    with patch("app.scraper.socket.getaddrinfo", side_effect=_rebinding_getaddrinfo):
        pinned = SSRFSafeNetworkBackend(allow_private_in_test=False, pinned_ips=pinned_cache)
        from app.scraper import resolve_and_validate_host_ips

        pinned_cache[("shop-rebind.pk", 80)] = resolve_and_validate_host_ips("shop-rebind.pk", 80)
        with patch.object(
            type(backend).__mro__[1],
            "connect_tcp",
            lambda _self, h, p, **kw: connected_targets.append(h) or _FakeStream(),
        ):
            pinned.connect_tcp("shop-rebind.pk", 80)
    assert connected_targets == ["93.184.216.34"]

    # Redirect to private IP and oversized stream caps
    class _FakeResp:
        def __init__(self, status_code: int, url: str, headers: dict, chunks: list[bytes]):
            self.status_code = status_code
            self.url = url
            self.headers = headers
            self._chunks = chunks

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self):
            return iter(self._chunks)

    def _redirect_stream(self, method, url, **kwargs):
        if "hop1" in url:
            return _FakeResp(
                302, url, {"location": "http://169.254.169.254/latest/meta-data/"}, []
            )
        if "huge" in url:
            return _FakeResp(200, url, {"content-type": "text/html"}, [b"a" * 300, b"b" * 300])
        if "pdf" in url:
            return _FakeResp(200, url, {"content-type": "application/pdf"}, [b"%PDF-1.4"])
        return _FakeResp(200, url, {"content-type": "text/html"}, [b"<html></html>"])

    with (
        patch("app.scraper.validate_public_http_url", side_effect=lambda u, **kw: (
            (_ for _ in ()).throw(UnsafeUrlError("blocked private redirect"))
            if "169.254.169.254" in u
            else u
        )),
        patch.object(httpx.Client, "stream", _redirect_stream),
    ):
        with pytest.raises(UnsafeUrlError):
            _fetch_with_ssrf_redirects(
                "https://shop.pk/hop1", headers={}, allow_private_in_test=True
            )
        with pytest.raises(ScraperError):
            _fetch_with_ssrf_redirects(
                "https://shop.pk/huge",
                headers={},
                allow_private_in_test=True,
                max_bytes=400,
            )
        with pytest.raises(ScraperError):
            _fetch_with_ssrf_redirects(
                "https://shop.pk/pdf",
                headers={},
                allow_private_in_test=True,
                allowed_content_types=("text/html",),
            )


def test_phase6_to_11_billing_immutability_rbac_and_observability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify OOO refunds, ledger immutability, locked JWT block, RBAC delete, and ops metrics."""
    wh_secret = "whsec_test_hardening_secret_123456"
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_hardening_123")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", wh_secret)

    with TestClient(app) as client:
        owner = _register_user(client, "owner-hardening@example.com")
        admin = _register_user(client, "admin-hardening@example.com")
        member = _register_user(client, "member-hardening@example.com")

        owner_h = {"Authorization": f"Bearer {owner['access_token']}"}
        admin_h = {"Authorization": f"Bearer {admin['access_token']}"}
        member_h = {"Authorization": f"Bearer {member['access_token']}"}
        ws_id = owner["primary_workspace_id"]

        # Invite admin and member
        assert (
            client.post(
                f"/v1/workspaces/{ws_id}/members",
                headers=owner_h,
                json={"email": "admin-hardening@example.com", "role": "admin"},
            ).status_code
            == 201
        )
        assert (
            client.post(
                f"/v1/workspaces/{ws_id}/members",
                headers=owner_h,
                json={"email": "member-hardening@example.com", "role": "member"},
            ).status_code
            == 201
        )

        # Out-of-order Stripe webhook: charge.refunded arrives BEFORE checkout.session.completed
        pi_id = "pi_out_of_order_999"
        refund_payload = {
            "id": "evt_ooo_refund_1",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_ooo_1",
                    "payment_intent": pi_id,
                    "amount": 900,
                    "amount_refunded": 900,
                    "currency": "usd",
                }
            },
        }
        raw_ref, sig_ref = _sign_stripe_payload(refund_payload, wh_secret)
        ref_res = client.post(
            "/v1/billing/webhooks/stripe",
            content=raw_ref,
            headers={"Stripe-Signature": sig_ref},
        )
        assert ref_res.status_code == 200
        assert ref_res.json()["status"] == "refund_unmatched"

        purchase_payload = {
            "id": "evt_ooo_purchase_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_ooo_1",
                    "payment_status": "paid",
                    "payment_intent": pi_id,
                    "amount_total": 900,
                    "currency": "usd",
                    "client_reference_id": ws_id,
                    "metadata": {
                        "workspace_id": ws_id,
                        "user_id": owner["user"]["id"],
                        "pack_id": "starter_10",
                    },
                }
            },
        }
        raw_pur, sig_pur = _sign_stripe_payload(purchase_payload, wh_secret)
        pur_res = client.post(
            "/v1/billing/webhooks/stripe",
            content=raw_pur,
            headers={"Stripe-Signature": sig_pur},
        )
        assert pur_res.status_code == 200
        assert pur_res.json()["credit_balance"] == 3  # +10 granted then -10 auto-revoked!

        reconcile_res = client.get(f"/v1/workspaces/{ws_id}/credits/reconcile", headers=owner_h)
        assert reconcile_res.status_code == 200
        assert reconcile_res.json()["is_balanced"] is True
        assert reconcile_res.json()["credit_balance"] == 3

        with db_module.SessionLocal() as session:
            prior_evt = session.scalar(
                select(StripeEvent).where(StripeEvent.stripe_event_id == "evt_ooo_refund_1")
            )
            assert prior_evt is not None
            assert prior_evt.status == "refund_processed_out_of_order"
            assert prior_evt.credits_delta == -10

            # Ledger immutability: ORM delete and raw SQL delete MUST abort!
            ledger_row = session.scalar(
                select(CreditLedger).where(CreditLedger.workspace_id == ws_id)
            )
            assert ledger_row is not None
            with pytest.raises(RuntimeError, match="immutable"):
                session.delete(ledger_row)
                session.flush()
            session.rollback()
            with pytest.raises(IntegrityError):
                session.execute(
                    text("DELETE FROM credit_ledger WHERE id = :lid"), {"lid": ledger_row.id}
                )
            session.rollback()

        # Member removal RBAC hierarchy checks
        assert (
            client.delete(
                f"/v1/workspaces/{ws_id}/members/{admin['user']['id']}",
                headers=member_h,
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/v1/workspaces/{ws_id}/members/{owner['user']['id']}",
                headers=admin_h,
            ).status_code
            == 400
        )
        assert (
            client.delete(
                f"/v1/workspaces/{ws_id}/members/{member['user']['id']}",
                headers=admin_h,
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/v1/workspaces/{ws_id}/members/{admin['user']['id']}",
                headers=owner_h,
            ).status_code
            == 200
        )

        # Correlation ID propagation & /v1/ops/metrics
        gen_res = client.post(
            "/v1/videos/generate",
            headers={**owner_h, "X-Request-ID": "req-corr-trace-001"},
            json={
                "workspace_id": ws_id,
                "product_url": "https://luminabotanics.com/products/trace-test",
                "target_language": "en",
            },
        )
        assert gen_res.status_code == 202
        assert gen_res.headers["X-Request-ID"] == "req-corr-trace-001"
        with db_module.SessionLocal() as session:
            trace_job = session.get(VideoJob, gen_res.json()["id"])
            assert trace_job is not None
            assert trace_job.correlation_id == "req-corr-trace-001"
            assert "stage_timings_ms" in (trace_job.script_json or {})

        ops_res = client.get("/v1/ops/metrics", headers=owner_h)
        assert ops_res.status_code == 200
        ops_json = ops_res.json()
        assert "db_latency_ms" in ops_json
        assert "jobs" in ops_json
        assert "timings" in ops_json["telemetry"]

        # POST /v1/auth/logout-all revokes all refresh sessions for user
        logout_all = client.post("/v1/auth/logout-all", headers=owner_h)
        assert logout_all.status_code == 200
        assert logout_all.json()["revoked_sessions"] >= 1
        with db_module.SessionLocal() as session:
            active_sess = list(
                session.scalars(
                    select(AuthSession).where(
                        AuthSession.user_id == owner["user"]["id"],
                        AuthSession.revoked_at.is_(None),
                    )
                ).all()
            )
            assert len(active_sess) == 0

        # Locked account existing JWT must be rejected with 403
        with db_module.SessionLocal() as session:
            locked_u = session.get(db_module.User, owner["user"]["id"])
            assert locked_u is not None
            locked_u.locked_until = utcnow() + timedelta(minutes=15)
            session.commit()
        locked_me = client.get("/v1/auth/me", headers=owner_h)
        assert locked_me.status_code == 403


def test_concurrency_thread_safety_under_lease_and_credits() -> None:
    """Stress-test concurrent credit reservations + job creation under 10 parallel threads."""
    with TestClient(app) as client:
        reg = _register_user(client, "stress@example.com")
        headers = {"Authorization": f"Bearer {reg['access_token']}"}
        ws_id = reg["primary_workspace_id"]

        statuses: list[int] = []
        lock = threading.Lock()

        def _hit():
            res = client.post(
                "/v1/videos/generate",
                headers=headers,
                json={
                    "workspace_id": ws_id,
                    "product_url": "https://luminabotanics.com/products/stress-item",
                    "target_language": "en",
                },
            )
            with lock:
                statuses.append(res.status_code)

        threads = [threading.Thread(target=_hit) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)

        assert statuses.count(202) == 3
        assert statuses.count(402) == 7
        with db_module.SessionLocal() as session:
            rec = reconcile_workspace_credits(session, ws_id)
            assert rec["credit_balance"] == 0
            assert rec["reserved_balance"] == 0
            assert rec["is_balanced"] is True


def test_phase10_staging_provider_failure_and_credential_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failure handling for missing/expired provider credentials, timeouts, and outages."""
    # 1. Missing GCP config in live Veo mode fails loudly with VeoConfigurationError
    monkeypatch.setenv("MOCK_VERTEX_VEO", "false")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    live_client = VeoClient()
    with pytest.raises(VeoConfigurationError):
        live_client.generate_clip(
            job_id="cfg-err",
            prompt="Luxury perfume bottle under golden lighting",
            work_dir=tmp_path,
        )

    # 2. HTTP 401 expired credential response from Vertex Veo surfaces clean VeoProviderError
    monkeypatch.setenv("GCP_PROJECT_ID", "staging-proj")
    monkeypatch.setenv("GCS_BUCKET", "gs://staging-bucket")
    monkeypatch.setenv("VERTEX_ACCESS_TOKEN", "ya29.expired-token")
    live_client2 = VeoClient()

    class _ErrResp:
        status_code = 401
        text = "Request had invalid authentication credentials."

    with patch.object(httpx.Client, "post", return_value=_ErrResp()):
        with pytest.raises(VeoProviderError, match="401"):
            live_client2.generate_clip(
                job_id="auth-err",
                prompt="Luxury perfume bottle under golden lighting",
                work_dir=tmp_path,
            )

    # 3. Live staging external smoke gate (skips cleanly unless STAGING_LIVE_TESTS=1)
    if os.environ.get("STAGING_LIVE_TESTS") == "1":
        health = httpx.get(
            os.environ.get("STAGING_WORKER_URL", "http://127.0.0.1:8000") + "/health",
            timeout=5.0,
        )
        assert health.status_code == 200
        assert health.json()["redis_broker"] is True
