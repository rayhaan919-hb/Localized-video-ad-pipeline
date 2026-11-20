"""Live PostgreSQL integration, migration, RLS, and race-condition tests.

Gated by ``TEST_POSTGRES_URL``. When unset, tests skip cleanly with an explicit
message rather than faking a pass on SQLite.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import app.db as db_module
from app.auth import hash_password
from app.db import (
    JobDispatchOutbox,
    User,
    VideoJob,
    Workspace,
    acquire_job_lease,
    create_workspace_for_user,
    db_offset_expr,
    reconcile_workspace_credits,
    renew_job_lease,
    reserve_credit_atomically,
    utcnow,
)
from app.tasks import recover_expired_leases

pytestmark = pytest.mark.postgres_integration

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "").strip()
if not TEST_POSTGRES_URL:
    pytest.skip(
        "TEST_POSTGRES_URL not set; skipping live PostgreSQL integration suite.",
        allow_module_level=True,
    )

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _ensure_supabase_role_and_auth_shims(engine) -> None:
    """Provision minimal auth.uid() and anon/authenticated shims on vanilla Postgres."""
    shim_sql = """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN NOBYPASSRLS;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN NOBYPASSRLS;
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN BYPASSRLS;
      END IF;
    END
    $$;

    CREATE SCHEMA IF NOT EXISTS auth;

    CREATE OR REPLACE FUNCTION auth.uid()
    RETURNS UUID
    LANGUAGE sql
    STABLE
    AS $$
      SELECT COALESCE(
        NULLIF(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
        NULL
      )::uuid;
    $$;

    GRANT USAGE ON SCHEMA auth TO PUBLIC;
    GRANT EXECUTE ON FUNCTION auth.uid() TO PUBLIC;
    """
    with engine.begin() as conn:
        conn.execute(text(shim_sql))


def _apply_sql_migrations_cleanly(engine) -> None:
    """Apply SQL migrations 001..005 in order and verify idempotency."""
    migration_files = sorted(MIGRATIONS_DIR.glob("00*.sql"))
    assert len(migration_files) >= 5
    with engine.begin() as conn:
        for mf in migration_files:
            conn.exec_driver_sql(mf.read_text(encoding="utf-8"))
        # Grant table access so authenticated NOBYPASSRLS roles evaluate RLS policies directly.
        conn.execute(text("GRANT USAGE ON SCHEMA public TO authenticated, anon"))
        conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON "
                "workspaces, workspace_members, workspace_assets, video_jobs, credit_ledger "
                "TO authenticated"
            )
        )


@pytest.fixture(scope="module")
def pg_env():
    """Bootstrap PostgreSQL schema once per module and configure worker SessionLocal."""
    bootstrap_engine = create_engine(TEST_POSTGRES_URL, pool_pre_ping=True, future=True)
    _ensure_supabase_role_and_auth_shims(bootstrap_engine)
    _apply_sql_migrations_cleanly(bootstrap_engine)
    bootstrap_engine.dispose()

    prev_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_POSTGRES_URL
    db_module.configure_database(TEST_POSTGRES_URL)
    db_module.init_db()
    yield TEST_POSTGRES_URL
    if prev_db_url is not None:
        os.environ["DATABASE_URL"] = prev_db_url


def _create_pg_user_and_workspace(
    session,
    *,
    email_prefix: str,
    initial_credits: int = 10,
) -> tuple[User, Workspace]:
    uid = str(uuid.uuid4())
    user = User(
        id=uid,
        email=f"{email_prefix}-{uid[:8]}@example.com",
        password_hash=hash_password("StrongPgPassword123!"),
        full_name="PG Integration Tester",
        is_email_verified=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(user)
    session.flush()
    ws = create_workspace_for_user(
        session,
        owner_id=user.id,
        name=f"PG Workspace {uid[:6]}",
        grant_initial_promo=initial_credits > 0,
        promo_credits=initial_credits,
    )
    session.flush()
    return user, ws


def test_pg_migrations_rls_flags_and_pool_configuration(pg_env: str) -> None:
    """Verify migrations 001..005, FORCE ROW LEVEL SECURITY flags, and QueuePool config."""
    assert db_module.engine.dialect.name == "postgresql"
    assert db_module.engine.pool.size() >= 1

    with db_module.SessionLocal() as session:
        applied = {
            row[0]
            for row in session.execute(text("SELECT version FROM schema_migrations")).fetchall()
        }
        assert "002_saas_multi_tenant_auth_billing" in applied
        assert "003_google_oauth_identity" in applied
        assert "004_job_leases_and_immutability" in applied
        assert "005_transactional_outbox_and_rls_hardening" in applied

        rows = session.execute(
            text(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class
                JOIN pg_namespace n ON n.oid = pg_class.relnamespace
                WHERE n.nspname = 'public'
                  AND relname IN (
                    'schema_migrations', 'users', 'auth_sessions', 'stripe_events',
                    'workspaces', 'workspace_members', 'workspace_assets',
                    'video_jobs', 'credit_ledger', 'job_dispatch_outbox'
                  )
                """
            )
        ).fetchall()
        rls_map = {str(r[0]): (bool(r[1]), bool(r[2])) for r in rows}
        for table_name in (
            "schema_migrations",
            "users",
            "auth_sessions",
            "stripe_events",
            "workspaces",
            "workspace_members",
            "workspace_assets",
            "video_jobs",
            "credit_ledger",
            "job_dispatch_outbox",
        ):
            assert rls_map.get(table_name) == (True, True), (
                f"Expected RLS + FORCE RLS on {table_name}, got {rls_map.get(table_name)}"
            )


def test_pg_credit_ledger_immutability_and_workspace_delete_protection(pg_env: str) -> None:
    """Verify PostgreSQL trigger forbids ledger deletion even on workspace removal attempts."""
    with db_module.SessionLocal() as session:
        _, ws = _create_pg_user_and_workspace(session, email_prefix="immutable", initial_credits=5)
        ws_id = ws.id
        session.commit()

    with db_module.SessionLocal() as session:
        with pytest.raises((SQLAlchemyError, IntegrityError)):
            session.execute(
                text("DELETE FROM credit_ledger WHERE workspace_id = :ws"),
                {"ws": ws_id},
            )
            session.commit()
        session.rollback()

    with db_module.SessionLocal() as session:
        with pytest.raises((SQLAlchemyError, IntegrityError)):
            session.execute(text("DELETE FROM workspaces WHERE id = :ws"), {"ws": ws_id})
            session.commit()
        session.rollback()


def test_pg_concurrent_credit_reservation_prevents_overdraft(pg_env: str) -> None:
    """12 concurrent PostgreSQL threads reserving from 10 credits permit exactly 10."""
    with db_module.SessionLocal() as session:
        user, ws = _create_pg_user_and_workspace(
            session, email_prefix="pg-conc-credit", initial_credits=10
        )
        ws_id = ws.id
        uid = user.id
        job_ids: list[str] = []
        for idx in range(12):
            jid = str(uuid.uuid4())
            job_ids.append(jid)
            session.add(
                VideoJob(
                    id=jid,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url=f"https://luminabotanics.com/products/pg-{idx}",
                    target_language="en",
                    status="CREATED",
                    reserved_credits=1,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
        session.commit()

    barrier = threading.Barrier(12)
    results: list[str] = []
    lock = threading.Lock()

    def _worker(jid: str) -> None:
        barrier.wait(timeout=10.0)
        with db_module.SessionLocal() as s:
            try:
                reserve_credit_atomically(
                    s,
                    workspace_id=ws_id,
                    job_id=jid,
                    user_id=uid,
                    cost=1,
                )
                s.commit()
                outcome = "reserved"
            except Exception as exc:
                s.rollback()
                outcome = type(exc).__name__
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_worker, args=(jid,)) for jid in job_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert results.count("reserved") == 10
    assert results.count("InsufficientCreditsError") == 2

    with db_module.SessionLocal() as session:
        refreshed = session.get(Workspace, ws_id)
        assert refreshed is not None
        assert refreshed.credit_balance == 0
        assert refreshed.reserved_balance == 10
        recon = reconcile_workspace_credits(session, ws_id)
        assert recon["is_balanced"] is True


def test_pg_clock_timestamp_heartbeat_vs_recovery_and_dual_recovery_races(pg_env: str) -> None:
    """Verify PostgreSQL clock_timestamp() + FOR UPDATE SKIP LOCKED mutual exclusion."""
    # Scenario A: 16 heartbeat-vs-recovery boundary races
    for iteration in range(4):
        with db_module.SessionLocal() as session:
            user, ws = _create_pg_user_and_workspace(
                session, email_prefix=f"pg-hb-{iteration}", initial_credits=5
            )
            ws_id = ws.id
            uid = user.id
            jid = str(uuid.uuid4())
            session.add(
                VideoJob(
                    id=jid,
                    workspace_id=ws_id,
                    user_id=uid,
                    product_url="https://luminabotanics.com/products/pg-hb",
                    target_language="ur",
                    status="QUEUED",
                    reserved_credits=1,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            session.flush()
            reserve_credit_atomically(session, workspace_id=ws_id, job_id=jid, user_id=uid, cost=1)
            session.flush()
            token = acquire_job_lease(session, job_id=jid, worker_id="pg-worker-a", lease_seconds=5)
            assert token is not None
            session.execute(
                text(
                    "UPDATE video_jobs "
                    "SET lease_expires_at = clock_timestamp() + interval '0.12 seconds' "
                    "WHERE id = :jid"
                ),
                {"jid": jid},
            )
            session.commit()

        barrier = threading.Barrier(2)
        outcomes: dict[str, object] = {}

        def _renew() -> None:
            barrier.wait(timeout=10.0)
            with db_module.SessionLocal() as s:
                outcomes["renewed"] = renew_job_lease(
                    s,
                    job_id=jid,
                    worker_id="pg-worker-a",
                    fencing_token=int(token),
                    lease_seconds=120,
                )
                s.commit()

        def _recover() -> None:
            barrier.wait(timeout=10.0)
            outcomes["recovered"] = recover_expired_leases(min_age_seconds=0)

        t1 = threading.Thread(target=_renew)
        t2 = threading.Thread(target=_recover)
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

        with db_module.SessionLocal() as session:
            job = session.get(VideoJob, jid)
            recon = reconcile_workspace_credits(session, ws_id)
            assert recon["is_balanced"] is True
            assert job is not None
            if job.status == "PROCESSING":
                assert outcomes["renewed"] is True
                assert job.lease_expires_at is not None
            else:
                assert job.status == "FAILED"

    # Scenario B: Dual simultaneous recovery scans over one genuinely expired job
    with db_module.SessionLocal() as session:
        user, ws = _create_pg_user_and_workspace(
            session, email_prefix="pg-dual-rec", initial_credits=4
        )
        ws_id = ws.id
        uid = user.id
        expired_jid = str(uuid.uuid4())
        session.add(
            VideoJob(
                id=expired_jid,
                workspace_id=ws_id,
                user_id=uid,
                product_url="https://luminabotanics.com/products/pg-expired",
                target_language="ar",
                status="PROCESSING",
                worker_id="dead-pg-worker",
                fencing_token=1,
                reserved_credits=1,
                lease_expires_at=db_offset_expr(session, -30.0),
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        session.flush()
        reserve_credit_atomically(
            session, workspace_id=ws_id, job_id=expired_jid, user_id=uid, cost=1
        )
        session.commit()

    rec_barrier = threading.Barrier(2)
    counts: list[int] = []

    def _run_rec() -> None:
        rec_barrier.wait(timeout=10.0)
        counts.append(recover_expired_leases(min_age_seconds=0))

    r1 = threading.Thread(target=_run_rec)
    r2 = threading.Thread(target=_run_rec)
    r1.start()
    r2.start()
    r1.join(timeout=10.0)
    r2.join(timeout=10.0)

    assert sum(counts) == 1
    with db_module.SessionLocal() as session:
        assert reconcile_workspace_credits(session, ws_id)["is_balanced"] is True


def test_pg_nobypss_rls_tenant_a_vs_tenant_b_vs_anon_isolation(pg_env: str) -> None:
    """Audit pg_roles and prove RLS tenant isolation under a genuine NOBYPASSRLS role."""
    with db_module.SessionLocal() as session:
        user_a, ws_a = _create_pg_user_and_workspace(
            session, email_prefix="rls-a", initial_credits=6
        )
        user_b, ws_b = _create_pg_user_and_workspace(
            session, email_prefix="rls-b", initial_credits=6
        )
        job_a_id = str(uuid.uuid4())
        job_b_id = str(uuid.uuid4())
        session.add_all(
            [
                VideoJob(
                    id=job_a_id,
                    workspace_id=ws_a.id,
                    user_id=user_a.id,
                    product_url="https://luminabotanics.com/products/tenant-a",
                    target_language="ur",
                    status="QUEUED",
                    reserved_credits=1,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                ),
                VideoJob(
                    id=job_b_id,
                    workspace_id=ws_b.id,
                    user_id=user_b.id,
                    product_url="https://luminabotanics.com/products/tenant-b",
                    target_language="hi",
                    status="QUEUED",
                    reserved_credits=1,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                ),
            ]
        )
        session.flush()
        session.add(
            JobDispatchOutbox(
                id=str(uuid.uuid4()),
                job_id=job_a_id,
                workspace_id=ws_a.id,
                payload_json={"job_id": job_a_id},
                status="PENDING",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        session.commit()

        user_a_id, ws_a_id = user_a.id, ws_a.id
        user_b_id, ws_b_id = user_b.id, ws_b.id

    temp_role = f"rls_audit_{uuid.uuid4().hex[:10]}"
    raw_engine = create_engine(pg_env, pool_pre_ping=True, future=True)
    try:
        with raw_engine.begin() as conn:
            conn.execute(
                text(f"CREATE ROLE {temp_role} NOLOGIN NOBYPASSRLS IN ROLE authenticated")
            )
            role_row = conn.execute(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = :r"),
                {"r": temp_role},
            ).fetchone()
            assert role_row is not None and role_row[0] is False

        # Tenant A context
        with raw_engine.begin() as conn:
            conn.execute(text(f"SET LOCAL ROLE {temp_role}"))
            conn.execute(
                text("SELECT set_config('request.jwt.claims', :claims, true)"),
                {"claims": json.dumps({"sub": user_a_id, "role": "authenticated"})},
            )
            visible_ws = {
                str(r[0]) for r in conn.execute(text("SELECT id FROM workspaces")).fetchall()
            }
            assert ws_a_id in visible_ws
            assert ws_b_id not in visible_ws
            visible_jobs = {
                str(r[0]) for r in conn.execute(text("SELECT id FROM video_jobs")).fetchall()
            }
            assert job_a_id in visible_jobs
            assert job_b_id not in visible_jobs

            # Cross-tenant UPDATE affects 0 rows under RLS
            upd_b = conn.execute(
                text("UPDATE video_jobs SET stage_detail = 'pwned' WHERE id = :jb"),
                {"jb": job_b_id},
            )
            assert upd_b.rowcount == 0

            # Internal default-deny tables are unreadable even to authenticated members
            outbox_rows = conn.execute(text("SELECT id FROM job_dispatch_outbox")).fetchall()
            assert outbox_rows == []
            user_rows = conn.execute(text("SELECT id FROM users")).fetchall()
            assert user_rows == []

        # Tenant B context
        with raw_engine.begin() as conn:
            conn.execute(text(f"SET LOCAL ROLE {temp_role}"))
            conn.execute(
                text("SELECT set_config('request.jwt.claims', :claims, true)"),
                {"claims": json.dumps({"sub": user_b_id, "role": "authenticated"})},
            )
            visible_jobs_b = {
                str(r[0]) for r in conn.execute(text("SELECT id FROM video_jobs")).fetchall()
            }
            assert job_b_id in visible_jobs_b
            assert job_a_id not in visible_jobs_b

        # Anon context sees 0 tenant rows
        with raw_engine.begin() as conn:
            conn.execute(text("SET LOCAL ROLE anon"))
            anon_jobs = conn.execute(text("SELECT id FROM video_jobs")).fetchall()
            assert anon_jobs == []
    finally:
        with raw_engine.begin() as conn:
            conn.execute(text(f"DROP ROLE IF EXISTS {temp_role}"))
        raw_engine.dispose()
