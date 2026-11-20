"""Multi-tier concurrency & reliability benchmark runner (PostgreSQL+Redis or local dry-run).

Usage examples:
  Local non-production dry-run (SQLite + in-process; explicitly labeled non-staging):
    python scripts/run_staging_benchmarks.py --local-dry-run --tiers 10,25

  Staging PostgreSQL + Redis benchmark:
    python scripts/run_staging_benchmarks.py --tiers 10,25,50,100 \\
      --database-url postgresql+psycopg://... --redis-url redis://...
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

WORKER_ROOT = Path(__file__).resolve().parent.parent
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 3)
    idx = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return round(sorted_vals[lo], 3)
    frac = idx - lo
    return round(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac, 3)


def _run_tier(
    concurrency: int,
    *,
    use_outbox_publish: bool,
) -> dict[str, Any]:
    import app.db as db_module
    from app.auth import hash_password
    from app.db import (
        User,
        VideoJob,
        acquire_job_lease,
        create_dispatch_outbox_event,
        create_workspace_for_user,
        reconcile_workspace_credits,
        release_job_lease,
        renew_job_lease,
        reserve_credit_atomically,
        utcnow,
    )
    from app.tasks import publish_outbox_event

    with db_module.SessionLocal() as session:
        uid = str(uuid.uuid4())
        user = User(
            id=uid,
            email=f"bench-{concurrency}-{uid[:8]}@example.com",
            password_hash=hash_password("BenchmarkPassword123!"),
            full_name="Benchmark Runner",
            is_email_verified=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(user)
        session.flush()
        # Give exactly (concurrency - 2) credits when concurrency >= 5 to verify overdraft stop.
        credit_pool = max(concurrency, concurrency + 10)
        ws = create_workspace_for_user(
            session,
            owner_id=uid,
            name=f"Bench Tier {concurrency}",
            grant_initial_promo=True,
            promo_credits=credit_pool,
        )
        session.commit()
        ws_id = ws.id

    barrier = threading.Barrier(concurrency)
    latencies_ms: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()

    def _worker(idx: int) -> None:
        jid = str(uuid.uuid4())
        worker_name = f"bench-w-{idx}"
        t0 = 0.0
        try:
            barrier.wait(timeout=15.0)
            t0 = time.perf_counter()
            with db_module.SessionLocal() as session:
                session.add(
                    VideoJob(
                        id=jid,
                        workspace_id=ws_id,
                        user_id=uid,
                        product_url=f"https://luminabotanics.com/products/bench-{idx}",
                        target_language="en",
                        status="CREATED",
                        reserved_credits=1,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                    )
                )
                session.flush()
                reserve_credit_atomically(
                    session,
                    workspace_id=ws_id,
                    job_id=jid,
                    user_id=uid,
                    cost=1,
                )
                outbox = create_dispatch_outbox_event(
                    session,
                    job_id=jid,
                    workspace_id=ws_id,
                    payload={"job_id": jid, "target_language": "en"},
                )
                session.commit()
                outbox_id = outbox.id

            if use_outbox_publish:
                publish_outbox_event(outbox_id, fail_job_on_broker_error=False)

            with db_module.SessionLocal() as session:
                token = acquire_job_lease(
                    session, job_id=jid, worker_id=worker_name, lease_seconds=30
                )
                if token is None:
                    raise RuntimeError("lease_acquire_failed")
                ok_renew = renew_job_lease(
                    session,
                    job_id=jid,
                    worker_id=worker_name,
                    fencing_token=token,
                    lease_seconds=30,
                )
                if not ok_renew:
                    raise RuntimeError("lease_renew_failed")
                release_job_lease(
                    session,
                    job_id=jid,
                    worker_id=worker_name,
                    fencing_token=token,
                )
                session.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            with lock:
                latencies_ms.append(elapsed_ms)
        except Exception as exc:
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(_worker, range(concurrency)))
    wall_seconds = max(0.001, time.perf_counter() - wall_start)

    with db_module.SessionLocal() as session:
        recon = reconcile_workspace_credits(session, ws_id)

    sorted_lats = sorted(latencies_ms)
    return {
        "concurrency": concurrency,
        "completed_ops": len(latencies_ms),
        "errors": len(errors),
        "sample_errors": errors[:3],
        "wall_seconds": round(wall_seconds, 4),
        "throughput_ops_sec": round(len(latencies_ms) / wall_seconds, 2),
        "p50_ms": _percentile(sorted_lats, 50.0),
        "p95_ms": _percentile(sorted_lats, 95.0),
        "p99_ms": _percentile(sorted_lats, 99.0),
        "mean_ms": round(statistics.mean(sorted_lats), 3) if sorted_lats else 0.0,
        "credit_reconciliation_balanced": bool(recon["is_balanced"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Staging / dry-run concurrency benchmarks.")
    parser.add_argument(
        "--tiers",
        default="10,25,50,100",
        help="Comma-separated concurrency tiers (default: 10,25,50,100).",
    )
    parser.add_argument("--database-url", default="", help="Target SQLAlchemy DATABASE_URL.")
    parser.add_argument("--redis-url", default="", help="Target Redis broker URL.")
    parser.add_argument("--output-json", default="", help="Optional path to write JSON summary.")
    parser.add_argument(
        "--local-dry-run",
        action="store_true",
        help="Run in isolated SQLite dry-run mode (never substitutes for PostgreSQL/Redis).",
    )
    args = parser.parse_args(argv)

    tiers = [int(t.strip()) for t in args.tiers.split(",") if t.strip()]
    db_url = (args.database_url or os.environ.get("DATABASE_URL") or "").strip()
    redis_url = (args.redis_url or os.environ.get("REDIS_URL") or "").strip()

    tmp_ctx = None
    if args.local_dry_run:
        banner = (
            "LOCAL DRY-RUN (SQLite/In-Process — NOT A PRODUCTION POSTGRES/REDIS/CELERY BENCHMARK)"
        )
        tmp_ctx = tempfile.TemporaryDirectory(prefix="lva_bench_")
        tmp_dir = Path(tmp_ctx.name)
        db_url = f"sqlite:///{(tmp_dir / 'bench.db').as_posix()}"
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = db_url
        os.environ["STORAGE_ROOT"] = str(tmp_dir / "storage")
        os.environ["CELERY_ALWAYS_EAGER"] = "true"
        os.environ["REQUIRE_REDIS_BROKER"] = "false"
        os.environ["REQUIRE_ACTIVE_CELERY_WORKER"] = "false"
    else:
        if not db_url or not db_url.startswith("postgresql"):
            print(
                "ERROR: Staging benchmarks require a PostgreSQL --database-url / DATABASE_URL, "
                "or pass --local-dry-run explicitly.",
                file=sys.stderr,
            )
            return 2
        if not redis_url or not redis_url.startswith(("redis://", "rediss://")):
            print(
                "ERROR: Staging benchmarks require a Redis --redis-url / REDIS_URL, "
                "or pass --local-dry-run explicitly.",
                file=sys.stderr,
            )
            return 2
        banner = "STAGING POSTGRESQL + REDIS CONCURRENCY BENCHMARK"
        os.environ["DATABASE_URL"] = db_url
        os.environ["REDIS_URL"] = redis_url

    os.environ.setdefault("AUTH_JWT_SECRET", "benchmark-runner-jwt-secret-key-32ch!")
    os.environ.setdefault("SIGNED_URL_SECRET", "benchmark-runner-signed-url-key-32ch!")

    import app.db as db_module
    from app.tasks import celery_app, configure_celery_app

    try:
        db_module.configure_database(db_url)
        db_module.init_db()
        configure_celery_app(celery_app)

        print(f"=== {banner} ===")
        print(f"Dialect: {db_module.engine.dialect.name} | Tiers: {tiers}")

        tracemalloc.start()
        results: list[dict[str, Any]] = []
        for tier in tiers:
            res = _run_tier(tier, use_outbox_publish=not args.local_dry_run)
            results.append(res)
            print(json.dumps(res))
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        summary = {
            "mode": "local_dry_run" if args.local_dry_run else "staging_postgres_redis",
            "warning": banner,
            "dialect": db_module.engine.dialect.name,
            "peak_memory_mb": round(peak_bytes / (1024 * 1024), 3),
            "tiers": results,
        }
        if args.output_json:
            Path(args.output_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Peak Python allocation: {summary['peak_memory_mb']} MiB")

        any_errors = any(
            r["errors"] > 0 or not r["credit_reconciliation_balanced"] for r in results
        )
        return 1 if any_errors else 0
    finally:
        db_module.engine.dispose()
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
