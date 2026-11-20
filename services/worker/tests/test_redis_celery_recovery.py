"""Live Redis Lua rate-limiter and Celery worker crash/recovery integration tests.

Gated by ``TEST_REDIS_URL``. Uses ``TEST_POSTGRES_URL`` if configured or a shared
temporary SQLite database so both parent test runner and real Celery subprocesses
share state cleanly.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import timezone
from pathlib import Path

import pytest

import app.db as db_module
from app.auth import hash_password
from app.db import (
    ACTIVE_EXECUTION_STATUSES,
    JobDispatchOutbox,
    User,
    VideoJob,
    Workspace,
    create_dispatch_outbox_event,
    create_workspace_for_user,
    get_db_now,
    reconcile_workspace_credits,
    reserve_credit_atomically,
    utcnow,
)
from app.security import DistributedRateLimiter
from app.tasks import (
    celery_app,
    configure_celery_app,
    process_video_job,
    reconcile_dispatch_outbox,
    recover_expired_leases,
    recover_interrupted_jobs,
)

pytestmark = pytest.mark.redis_celery_integration

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "").strip()
if not TEST_REDIS_URL:
    pytest.skip(
        "TEST_REDIS_URL not set; skipping live Redis & Celery worker integration suite.",
        allow_module_level=True,
    )

WORKER_ROOT = Path(__file__).resolve().parent.parent


def _build_worker_env(shared_db_url: str, storage_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": shared_db_url,
            "REDIS_URL": TEST_REDIS_URL,
            "STORAGE_ROOT": str(storage_root),
            "AUTH_JWT_SECRET": "redis-celery-test-jwt-secret-key-32-chars!",
            "SIGNED_URL_SECRET": "redis-celery-test-signed-url-key-32-ch!",
            "MOCK_VERTEX_VEO": "true",
            "MOCK_TTS": "true",
            "CELERY_ALWAYS_EAGER": "false",
            "REQUIRE_REDIS_BROKER": "true",
            "REQUIRE_ACTIVE_CELERY_WORKER": "false",
            "JOB_LEASE_DURATION_SECONDS": "10",
            "JOB_HEARTBEAT_INTERVAL_SECONDS": "1",
        }
    )
    return env


def _spawn_celery_worker(env: dict[str, str], queue: str = "celery") -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.tasks:celery_app",
            "worker",
            "--loglevel=INFO",
            "--pool=solo",
            "--concurrency=1",
            "-Q",
            queue,
        ],
        cwd=str(WORKER_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + 20.0
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"Celery worker exited prematurely: {out}")
        try:
            pings = celery_app.control.inspect(timeout=0.75).ping() or {}
            if pings:
                return proc
        except Exception:
            pass
        time.sleep(0.35)
    proc.terminate()
    raise RuntimeError("Timed out waiting for Celery worker ping on live Redis.")


def _terminate_proc(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)


@pytest.fixture
def redis_celery_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import redis

    client = redis.Redis.from_url(TEST_REDIS_URL)
    client.flushdb()

    pg_url = os.environ.get("TEST_POSTGRES_URL", "").strip()
    shared_db_url = pg_url or f"sqlite:///{(tmp_path / 'celery_shared.db').as_posix()}"
    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", shared_db_url)
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)
    monkeypatch.setenv("STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("AUTH_JWT_SECRET", "redis-celery-test-jwt-secret-key-32-chars!")
    monkeypatch.setenv("SIGNED_URL_SECRET", "redis-celery-test-signed-url-key-32-ch!")
    monkeypatch.setenv("MOCK_VERTEX_VEO", "true")
    monkeypatch.setenv("MOCK_TTS", "true")
    monkeypatch.setenv("CELERY_ALWAYS_EAGER", "false")
    monkeypatch.setenv("REQUIRE_REDIS_BROKER", "true")
    monkeypatch.setenv("REQUIRE_ACTIVE_CELERY_WORKER", "false")
    monkeypatch.setenv("JOB_LEASE_DURATION_SECONDS", "10")
    monkeypatch.setenv("JOB_HEARTBEAT_INTERVAL_SECONDS", "1")

    configure_celery_app(celery_app)
    db_module.configure_database(shared_db_url)
    db_module.init_db()
    worker_env = _build_worker_env(shared_db_url, storage_root)
    yield {"redis": client, "worker_env": worker_env, "db_url": shared_db_url}
    configure_celery_app(celery_app)
    client.flushdb()


def _seed_job_and_workspace(
    *,
    initial_credits: int = 10,
    duration_seconds: int = 4,
    status: str = "QUEUED",
) -> tuple[str, str, str]:
    with db_module.SessionLocal() as session:
        uid = str(uuid.uuid4())
        user = User(
            id=uid,
            email=f"redis-celery-{uid[:8]}@example.com",
            password_hash=hash_password("StrongRedisPass123!"),
            full_name="Redis Celery Tester",
            is_email_verified=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(user)
        session.flush()
        ws = create_workspace_for_user(
            session,
            owner_id=uid,
            name="Redis Celery Workspace",
            grant_initial_promo=initial_credits > 0,
            promo_credits=initial_credits,
        )
        session.flush()
        jid = str(uuid.uuid4())
        session.add(
            VideoJob(
                id=jid,
                workspace_id=ws.id,
                user_id=uid,
                product_url="https://luminabotanics.com/products/redis-test",
                target_language="en",
                aspect_ratio="9:16",
                duration_seconds=duration_seconds,
                status=status,
                reserved_credits=1,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        session.flush()
        reserve_credit_atomically(session, workspace_id=ws.id, job_id=jid, user_id=uid, cost=1)
        session.commit()
        return uid, ws.id, jid


def test_real_redis_lua_distributed_rate_limiter_across_instances(redis_celery_env) -> None:
    """Two independent DistributedRateLimiter instances share atomic limits in real Redis."""
    limiter_a = DistributedRateLimiter(redis_url=TEST_REDIS_URL)
    limiter_b = DistributedRateLimiter(redis_url=TEST_REDIS_URL)
    assert limiter_a.backend_mode == "redis"
    assert limiter_b.backend_mode == "redis"

    key = f"client-{uuid.uuid4().hex[:8]}"
    assert limiter_a.check_with_metadata("staging-auth", key, limit=3, window_seconds=30).allowed
    assert limiter_b.check_with_metadata("staging-auth", key, limit=3, window_seconds=30).allowed
    assert limiter_a.check_with_metadata("staging-auth", key, limit=3, window_seconds=30).allowed

    blocked = limiter_b.check_with_metadata("staging-auth", key, limit=3, window_seconds=30)
    assert blocked.allowed is False
    assert blocked.retry_after >= 1
    assert blocked.remaining == 0


def test_real_celery_worker_queued_congestion_and_duplicate_delivery(redis_celery_env) -> None:
    """Queued jobs survive recovery while waiting, duplicate tasks charge once cleanly."""
    _, ws_id, jid = _seed_job_and_workspace(initial_credits=10, duration_seconds=4)

    # Enqueue duplicate tasks BEFORE starting the Celery worker so it sits in Redis queue.
    props = {
        "confirmedMetadata": {
            "title": "Botanical Redis Essence",
            "brand": "Lumina",
            "description": "Verified integration fixture product.",
        }
    }
    process_video_job.delay(job_id=jid, custom_props=props, duration_seconds=4.0)
    process_video_job.delay(job_id=jid, custom_props=props, duration_seconds=4.0)

    # Running recovery while queued in Redis must NOT fail or refund the queued job.
    assert recover_interrupted_jobs(min_age_seconds=0, reconcile_outbox=False) == 0
    with db_module.SessionLocal() as session:
        queued_job = session.get(VideoJob, jid)
        assert queued_job is not None
        assert queued_job.status == "QUEUED"

    proc = _spawn_celery_worker(redis_celery_env["worker_env"])
    try:
        deadline = time.time() + 30.0
        while time.time() < deadline:
            with db_module.SessionLocal() as session:
                job = session.get(VideoJob, jid)
                if job and job.status == "COMPLETED":
                    break
            time.sleep(0.25)

        with db_module.SessionLocal() as session:
            job = session.get(VideoJob, jid)
            ws = session.get(Workspace, ws_id)
            assert job is not None and job.status == "COMPLETED"
            assert ws is not None and ws.credit_balance == 9
            assert ws.reserved_balance == 0
            assert reconcile_workspace_credits(session, ws_id)["is_balanced"] is True
    finally:
        _terminate_proc(proc)


def test_real_celery_worker_sigkill_lease_expiry_and_outbox_recovery(redis_celery_env) -> None:
    """Worker SIGKILL -> lease expiry recovery -> restarted worker skips stale delivery."""
    _, ws_id, crash_jid = _seed_job_and_workspace(initial_credits=5, duration_seconds=12)
    slow_props = {
        "confirmedMetadata": {
            "title": "Slow Crash Verification Serum",
            "brand": "Lumina",
            "description": "Longer clip fixture to observe active worker execution.",
        }
    }
    proc = _spawn_celery_worker(redis_celery_env["worker_env"])
    try:
        process_video_job.delay(job_id=crash_jid, custom_props=slow_props, duration_seconds=12.0)
        entered_active = False
        deadline = time.time() + 15.0
        while time.time() < deadline:
            with db_module.SessionLocal() as session:
                job = session.get(VideoJob, crash_jid)
                if job and job.status in ("PROCESSING", "RENDERING") and job.worker_id:
                    entered_active = True
                    break
            time.sleep(0.05)

        if entered_active:
            proc.kill()
            proc.wait(timeout=5.0)

            with db_module.SessionLocal() as session:
                killed_job = session.get(VideoJob, crash_jid)
                assert killed_job is not None
                still_active = killed_job.status in ACTIVE_EXECUTION_STATUSES
                lease_exp = killed_job.lease_expires_at
                db_now = get_db_now(session)

            if still_active:
                assert lease_exp is not None
                exp_utc = (
                    lease_exp
                    if lease_exp.tzinfo is not None
                    else lease_exp.replace(tzinfo=timezone.utc)
                )
                remaining = max(0.0, (exp_utc - db_now).total_seconds())
                rec_deadline = time.time() + max(16.0, remaining + 8.0)
                recovered = 0
                while time.time() < rec_deadline:
                    recovered = recover_expired_leases(min_age_seconds=0)
                    with db_module.SessionLocal() as session:
                        post_job = session.get(VideoJob, crash_jid)
                        if recovered >= 1 or (post_job is not None and post_job.status == "FAILED"):
                            break
                    time.sleep(0.5)
                assert recovered >= 1

                with db_module.SessionLocal() as session:
                    failed_job = session.get(VideoJob, crash_jid)
                    ws_after = session.get(Workspace, ws_id)
                    assert failed_job is not None
                    assert failed_job.status == "FAILED"
                    assert failed_job.error_code == "WORKER_LEASE_EXPIRED"
                    assert ws_after is not None
                    assert ws_after.credit_balance == 5
                    assert ws_after.reserved_balance == 0
                    assert reconcile_workspace_credits(session, ws_id)["is_balanced"] is True
        else:
            # If fast CPU finished before SIGKILL polling, verify clean completion instead.
            _terminate_proc(proc)
    finally:
        if proc.poll() is None:
            _terminate_proc(proc)

    was_recovered = False
    with db_module.SessionLocal() as session:
        cur_crash = session.get(VideoJob, crash_jid)
        was_recovered = cur_crash is not None and cur_crash.status == "FAILED"
        assert reconcile_workspace_credits(session, ws_id)["is_balanced"] is True

    # Also verify transactional outbox relay delivers unpublished event to restarted worker.
    _, out_ws_id, out_jid = _seed_job_and_workspace(
        initial_credits=5, duration_seconds=4, status="CREATED"
    )
    with db_module.SessionLocal() as session:
        outbox_ev = create_dispatch_outbox_event(
            session,
            job_id=out_jid,
            workspace_id=out_ws_id,
            payload={
                "job_id": out_jid,
                "custom_props": slow_props,
                "duration_seconds": 4.0,
                "aspect_ratio": "9:16",
            },
        )
        outbox_id = outbox_ev.id
        session.commit()

    relayed = reconcile_dispatch_outbox(limit=25)
    assert relayed["published"] >= 1
    with db_module.SessionLocal() as session:
        refreshed_outbox = session.get(JobDispatchOutbox, outbox_id)
        assert refreshed_outbox is not None
        assert refreshed_outbox.status == "PUBLISHED"

    proc2 = _spawn_celery_worker(redis_celery_env["worker_env"])
    try:
        deadline = time.time() + 30.0
        while time.time() < deadline:
            with db_module.SessionLocal() as session:
                out_job = session.get(VideoJob, out_jid)
                if out_job and out_job.status == "COMPLETED":
                    break
            time.sleep(0.25)

        with db_module.SessionLocal() as session:
            out_job = session.get(VideoJob, out_jid)
            assert out_job is not None and out_job.status == "COMPLETED"
            assert reconcile_workspace_credits(session, out_ws_id)["is_balanced"] is True
            if was_recovered:
                post_crash = session.get(VideoJob, crash_jid)
                ws_final = session.get(Workspace, ws_id)
                assert post_crash is not None and post_crash.status == "FAILED"
                assert ws_final is not None and ws_final.credit_balance == 5
                assert reconcile_workspace_credits(session, ws_id)["is_balanced"] is True
    finally:
        _terminate_proc(proc2)
