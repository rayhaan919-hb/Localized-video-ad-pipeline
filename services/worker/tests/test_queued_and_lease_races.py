"""Regression & concurrency tests for Phase 2 (queued recovery/outbox) & Phase 3 (lease races)."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

import app.db as db_module
from app.db import (
    JobDispatchOutbox,
    VideoJob,
    Workspace,
    acquire_job_lease,
    create_dispatch_outbox_event,
    db_offset_expr,
    reconcile_workspace_credits,
    renew_job_lease,
    reserve_credit_atomically,
    utcnow,
)
from app.main import app
from app.security import rate_limiter
from app.tasks import (
    celery_app,
    configure_celery_app,
    process_video_job,
    reconcile_dispatch_outbox,
    recover_expired_leases,
    recover_interrupted_jobs,
)
from app.veo import VeoClient, VeoGenerationResult, ensure_sample_fixture


@pytest.fixture(autouse=True)
def isolated_queue_race_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "queue_races.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("AUTH_JWT_SECRET", "queue-race-jwt-secret-key-32-chars!!")
    monkeypatch.setenv("SIGNED_URL_SECRET", "queue-race-signed-url-secret-32-ch!")
    monkeypatch.setenv("MOCK_VERTEX_VEO", "true")
    monkeypatch.setenv("MOCK_TTS", "true")
    monkeypatch.setenv("INITIAL_PROMO_CREDITS", "20")
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


def _register(client: TestClient, email: str) -> dict:
    res = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "StrongPassword123!", "full_name": "Queue Tester"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_queued_job_waiting_beyond_recovery_threshold_is_never_failed() -> None:
    """Queued/Pending/Created jobs waiting past recovery thresholds stay intact indefinitely."""
    with TestClient(app) as client:
        reg = _register(client, "queued-safe@example.com")
        ws_id = reg["primary_workspace_id"]
        uid = reg["user"]["id"]

        old_ts = utcnow() - timedelta(hours=5)
        jids: list[tuple[str, str]] = []
        with db_module.SessionLocal() as session:
            for st in ("CREATED", "QUEUED", "PENDING"):
                jid = str(uuid.uuid4())
                jids.append((jid, st))
                session.add(
                    VideoJob(
                        id=jid,
                        workspace_id=ws_id,
                        user_id=uid,
                        product_url="https://luminabotanics.com/products/queued-item",
                        target_language="ur",
                        status=st,
                        reserved_credits=1,
                        created_at=old_ts,
                        updated_at=old_ts,
                    )
                )
                session.flush()
                reserve_credit_atomically(
                    session, workspace_id=ws_id, job_id=jid, user_id=uid, cost=1
                )
            session.commit()

        assert recover_interrupted_jobs(min_age_seconds=0, reconcile_outbox=False) == 0
        assert recover_interrupted_jobs(min_age_seconds=60, reconcile_outbox=False) == 0

        with db_module.SessionLocal() as session:
            for jid, expected_status in jids:
                row = session.get(VideoJob, jid)
                assert row is not None
                assert row.status == expected_status
            rec = reconcile_workspace_credits(session, ws_id)
            assert rec["credit_balance"] == 17
            assert rec["reserved_balance"] == 3
            assert rec["is_balanced"] is True


def test_queued_congestion_and_abandoned_active_job_recovery_isolation() -> None:
    """Queue congestion survives recovery scans while abandoned active jobs recover."""
    with TestClient(app) as client:
        reg = _register(client, "congestion@example.com")
        ws_id = reg["primary_workspace_id"]
        uid = reg["user"]["id"]

        old_ts = utcnow() - timedelta(minutes=45)
        queued_ids: list[str] = []
        active_healthy_id = str(uuid.uuid4())
        abandoned_id = str(uuid.uuid4())

        with db_module.SessionLocal() as session:
            for idx in range(10):
                qid = str(uuid.uuid4())
                queued_ids.append(qid)
                session.add(
                    VideoJob(
                        id=qid,
                        workspace_id=ws_id,
                        user_id=uid,
                        product_url=f"https://luminabotanics.com/products/q-{idx}",
                        target_language="ar",
                        status="QUEUED",
                        reserved_credits=1,
                        created_at=old_ts,
                        updated_at=old_ts,
                    )
                )
                session.flush()
                reserve_credit_atomically(
                    session, workspace_id=ws_id, job_id=qid, user_id=uid, cost=1
                )

            session.add(
                VideoJob(
                    id=active_healthy_id,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/healthy-active",
                    target_language="en",
                    status="PROCESSING",
                    worker_id="worker-healthy",
                    fencing_token=1,
                    heartbeat_at=utcnow(),
                    lease_expires_at=utcnow() + timedelta(seconds=120),
                    reserved_credits=1,
                    updated_at=old_ts,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=active_healthy_id, user_id=uid, cost=1
            )

            session.add(
                VideoJob(
                    id=abandoned_id,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/abandoned",
                    target_language="hi",
                    status="RENDERING",
                    worker_id="worker-crashed",
                    fencing_token=1,
                    heartbeat_at=old_ts,
                    lease_expires_at=utcnow() - timedelta(seconds=10),
                    reserved_credits=1,
                    updated_at=old_ts,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=abandoned_id, user_id=uid, cost=1
            )
            session.commit()

        assert recover_interrupted_jobs(min_age_seconds=60, reconcile_outbox=False) == 1
        assert recover_interrupted_jobs(min_age_seconds=0, reconcile_outbox=False) == 0

        with db_module.SessionLocal() as session:
            for qid in queued_ids:
                assert session.get(VideoJob, qid).status == "QUEUED"
            assert session.get(VideoJob, active_healthy_id).status == "PROCESSING"
            abandoned = session.get(VideoJob, abandoned_id)
            assert abandoned is not None
            assert abandoned.status == "FAILED"
            assert abandoned.error_code == "WORKER_LEASE_EXPIRED"
            rec = reconcile_workspace_credits(session, ws_id)
            assert rec["credit_balance"] == 9
            assert rec["reserved_balance"] == 11
            assert rec["is_balanced"] is True

        # Worker starting right after recovery scan executes one of the queued jobs cleanly
        after_scan = process_video_job(job_id=queued_ids[0], worker_id="worker-post-scan")
        assert after_scan["status"] == "COMPLETED"


def test_transactional_outbox_retry_recovery_and_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outbox survives API crash/Redis outage, recovers cleanly, and bounds retries."""
    with TestClient(app) as client:
        reg = _register(client, "outbox@example.com")
        headers = {"Authorization": f"Bearer {reg['access_token']}"}
        ws_id = reg["primary_workspace_id"]
        uid = reg["user"]["id"]

        # 1. Simulate API crash right after committing CREATED + reservation + PENDING outbox row
        job1_id = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=job1_id,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/outbox-1",
                    target_language="en",
                    status="CREATED",
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=job1_id, user_id=uid, cost=1
            )
            outbox1 = create_dispatch_outbox_event(
                session,
                job_id=job1_id,
                workspace_id=ws_id,
                payload={"job_id": job1_id, "target_language": "en"},
            )
            session.commit()
            outbox1_id = outbox1.id

        # 2. Temporary Redis outage schedules retry without failing customer job
        monkeypatch.setenv("REQUIRE_REDIS_BROKER", "true")
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/9")
        res_outage = reconcile_dispatch_outbox()
        assert res_outage["retried"] == 1
        with db_module.SessionLocal() as session:
            ob1 = session.get(JobDispatchOutbox, outbox1_id)
            j1 = session.get(VideoJob, job1_id)
            assert ob1 is not None and ob1.status == "PENDING" and ob1.attempts == 1
            assert j1 is not None and j1.status == "CREATED"
            # Force next_attempt_at ready cleanly for immediate recovery test
            session.execute(
                update(JobDispatchOutbox)
                .where(JobDispatchOutbox.id == outbox1_id)
                .values(next_attempt_at=db_offset_expr(session, -1.0))
            )
            session.commit()

        # 3. Broker recovers -> reconcile_dispatch_outbox() publishes and completes job1
        monkeypatch.setenv("REQUIRE_REDIS_BROKER", "false")
        res_ok = reconcile_dispatch_outbox()
        assert res_ok["published"] == 1
        with db_module.SessionLocal() as session:
            assert session.get(JobDispatchOutbox, outbox1_id).status == "PUBLISHED"
            assert session.get(VideoJob, job1_id).status == "COMPLETED"
            assert reconcile_workspace_credits(session, ws_id)["is_balanced"] is True

        # 4. Exhausted outbox retries mark job FAILED cleanly and refund credit once
        job2_id = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=job2_id,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/outbox-2",
                    target_language="en",
                    status="CREATED",
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=job2_id, user_id=uid, cost=1
            )
            outbox2 = create_dispatch_outbox_event(
                session,
                job_id=job2_id,
                workspace_id=ws_id,
                payload={"job_id": job2_id, "target_language": "en"},
                max_attempts=1,
            )
            session.commit()
            outbox2_id = outbox2.id

        monkeypatch.setenv("REQUIRE_REDIS_BROKER", "true")
        res_exhaust = reconcile_dispatch_outbox()
        assert res_exhaust["failed"] == 1
        with db_module.SessionLocal() as session:
            assert session.get(JobDispatchOutbox, outbox2_id).status == "FAILED"
            j2 = session.get(VideoJob, job2_id)
            assert j2 is not None and j2.status == "FAILED"
            assert j2.error_code == "OUTBOX_DISPATCH_EXHAUSTED"
            rec = reconcile_workspace_credits(session, ws_id)
            assert rec["credit_balance"] == 19
            assert rec["is_balanced"] is True

        # 5. Cancelling a CREATED/QUEUED job cancels pending outbox and skips stale delivery
        job3_id = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=job3_id,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/outbox-3",
                    target_language="en",
                    status="QUEUED",
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=job3_id, user_id=uid, cost=1
            )
            outbox3 = create_dispatch_outbox_event(
                session,
                job_id=job3_id,
                workspace_id=ws_id,
                payload={"job_id": job3_id, "target_language": "en"},
            )
            session.commit()
            outbox3_id = outbox3.id

        cancel_res = client.post(f"/v1/videos/{job3_id}/cancel", headers=headers)
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "CANCELLED"
        assert cancel_res.json()["credit_balance"] == 19

        # Old queued Celery message arriving after FAILED/CANCELLED must skip safely
        stale_cancelled = process_video_job(job_id=job3_id, worker_id="stale-celery-msg")
        assert stale_cancelled["skipped_duplicate"] is True
        assert stale_cancelled["status"] == "CANCELLED"
        stale_failed = process_video_job(job_id=job2_id, worker_id="stale-celery-msg")
        assert stale_failed["skipped_duplicate"] is True
        assert stale_failed["status"] == "FAILED"
        with db_module.SessionLocal() as session:
            assert session.get(JobDispatchOutbox, outbox3_id).status == "CANCELLED"
            assert reconcile_workspace_credits(session, ws_id)["credit_balance"] == 19


def test_heartbeat_vs_recovery_concurrency_and_fencing_invariants() -> None:
    """Prove mutual exclusion & fencing between heartbeats, recovery workers, and workers."""
    with TestClient(app) as client:
        reg = _register(client, "races@example.com")
        ws_id = reg["primary_workspace_id"]
        uid = reg["user"]["id"]

        # 1. Heartbeat immediately before recovery blocks recovery
        j_hb = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=j_hb,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/hb-before",
                    target_language="en",
                    status="PROCESSING",
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=j_hb, user_id=uid, cost=1
            )
            session.commit()
            tok = acquire_job_lease(session, job_id=j_hb, worker_id="w-hb", lease_seconds=0.35)
            session.commit()
            assert tok == 1
            assert renew_job_lease(
                session, job_id=j_hb, worker_id="w-hb", fencing_token=1, lease_seconds=60
            )
            session.commit()
        assert recover_expired_leases(min_age_seconds=0) == 0

        # 2. Recovery immediately before heartbeat blocks heartbeat from reviving job
        j_revive = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=j_revive,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/no-revive",
                    target_language="en",
                    status="QUEUED",
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=j_revive, user_id=uid, cost=1
            )
            session.commit()
            tok2 = acquire_job_lease(session, job_id=j_revive, worker_id="w-exp", lease_seconds=0.1)
            session.commit()
            assert tok2 == 1

        time.sleep(0.18)
        # Worker tries renewing ALREADY expired lease directly -> MUST fail (False)
        with db_module.SessionLocal() as session:
            assert (
                renew_job_lease(
                    session, job_id=j_revive, worker_id="w-exp", fencing_token=1, lease_seconds=60
                )
                is False
            )
        assert recover_expired_leases(min_age_seconds=0) == 1
        with db_module.SessionLocal() as session:
            assert (
                renew_job_lease(
                    session, job_id=j_revive, worker_id="w-exp", fencing_token=1, lease_seconds=60
                )
                is False
            )
            assert session.get(VideoJob, j_revive).status == "FAILED"

        # 3. Two recovery workers racing on same expired job recover strictly once
        j_dual_rec = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=j_dual_rec,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/dual-rec",
                    target_language="en",
                    status="PROCESSING",
                    worker_id="w-dead",
                    fencing_token=1,
                    lease_expires_at=utcnow() - timedelta(seconds=10),
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=j_dual_rec, user_id=uid, cost=1
            )
            session.commit()

        rec_barrier = threading.Barrier(2)
        rec_counts: list[int] = []

        def _rec_worker() -> None:
            rec_barrier.wait(timeout=5.0)
            rec_counts.append(recover_expired_leases(min_age_seconds=0))

        t1 = threading.Thread(target=_rec_worker)
        t2 = threading.Thread(target=_rec_worker)
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)
        assert sum(rec_counts) == 1

        # 4. Two workers competing for same QUEUED job: strictly 1 acquires lease
        j_compete = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=j_compete,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/compete",
                    target_language="en",
                    status="QUEUED",
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=j_compete, user_id=uid, cost=1
            )
            session.commit()

        comp_barrier = threading.Barrier(2)
        acquired_tokens: list[int | None] = []

        def _lease_racer(wid: str) -> None:
            comp_barrier.wait(timeout=5.0)
            with db_module.SessionLocal() as s:
                t = acquire_job_lease(s, job_id=j_compete, worker_id=wid, lease_seconds=60)
                s.commit()
                acquired_tokens.append(t)

        ta = threading.Thread(target=_lease_racer, args=("w-alpha",))
        tb = threading.Thread(target=_lease_racer, args=("w-beta",))
        ta.start()
        tb.start()
        ta.join(timeout=10.0)
        tb.join(timeout=10.0)
        assert acquired_tokens.count(1) == 1
        assert acquired_tokens.count(None) == 1

        # Duplicate task delivery referencing active leased job skips safely
        dup = process_video_job(job_id=j_compete, worker_id="w-alpha")
        assert dup["skipped_duplicate"] is True

        # 5. Concurrent Heartbeat Renewal vs Recovery barrier race across repeated trials
        for idx in range(5):
            j_race = str(uuid.uuid4())
            with db_module.SessionLocal() as session:
                session.add(
                    VideoJob(
                        id=j_race,
                        workspace_id=ws_id,
                        user_id=uid,
                        product_url=f"https://luminabotanics.com/products/race-{idx}",
                        target_language="en",
                        status="QUEUED",
                        reserved_credits=1,
                    )
                )
                session.flush()
                reserve_credit_atomically(
                    session, workspace_id=ws_id, job_id=j_race, user_id=uid, cost=1
                )
                session.commit()
                tok_r = acquire_job_lease(
                    session, job_id=j_race, worker_id="w-race", lease_seconds=0.15
                )
                session.commit()
                assert tok_r == 1

            time.sleep(0.14 if idx % 2 == 0 else 0.17)
            race_barrier = threading.Barrier(2)
            hb_result: dict[str, bool] = {}

            def _hb_thread(target_id: str = j_race) -> None:
                race_barrier.wait(timeout=5.0)
                with db_module.SessionLocal() as s:
                    ok = renew_job_lease(
                        s,
                        job_id=target_id,
                        worker_id="w-race",
                        fencing_token=1,
                        lease_seconds=60,
                    )
                    s.commit()
                    hb_result["renewed"] = ok

            def _rec_thread() -> None:
                race_barrier.wait(timeout=5.0)
                recover_expired_leases(min_age_seconds=0)

            hb_t = threading.Thread(target=_hb_thread)
            rc_t = threading.Thread(target=_rec_thread)
            hb_t.start()
            rc_t.start()
            hb_t.join(timeout=10.0)
            rc_t.join(timeout=10.0)

            with db_module.SessionLocal() as session:
                final_row = session.get(VideoJob, j_race)
                assert final_row is not None
                if hb_result["renewed"]:
                    assert final_row.status == "PROCESSING"
                else:
                    assert final_row.status == "FAILED"
                # Release/clean remaining active test job or keep balanced
                if final_row.status == "PROCESSING":
                    # Transition cleanly out so next loop stays independent
                    session.execute(
                        update(VideoJob)
                        .where(VideoJob.id == j_race)
                        .values(lease_expires_at=db_offset_expr(session, 120.0))
                    )
                    session.commit()

        # 6. Stale worker attempting completion after job was recovered gets fenced
        j_stale_done = str(uuid.uuid4())
        with db_module.SessionLocal() as session:
            session.add(
                VideoJob(
                    id=j_stale_done,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/stale-done",
                    target_language="en",
                    status="QUEUED",
                    reserved_credits=1,
                )
            )
            session.flush()
            reserve_credit_atomically(
                session, workspace_id=ws_id, job_id=j_stale_done, user_id=uid, cost=1
            )
            session.commit()

        sample_clip = ensure_sample_fixture(duration_seconds=4.0)

        def _force_expire_and_recover(self, **kwargs):
            with db_module.SessionLocal() as inner:
                inner.execute(
                    update(VideoJob)
                    .where(VideoJob.id == j_stale_done)
                    .values(lease_expires_at=db_offset_expr(inner, -5.0))
                )
                inner.commit()
            assert recover_expired_leases(min_age_seconds=0) == 1
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

        with patch.object(VeoClient, "generate_clip", _force_expire_and_recover):
            fenced = process_video_job(job_id=j_stale_done, worker_id="w-late")
            assert fenced.get("fenced") is True
            assert fenced["status"] == "FAILED"

        with db_module.SessionLocal() as session:
            ws_check = reconcile_workspace_credits(session, ws_id)
            assert ws_check["is_balanced"] is True
            assert session.get(Workspace, ws_id).credit_balance >= 0
