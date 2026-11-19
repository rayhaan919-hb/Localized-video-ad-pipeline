"""Reproducible performance & concurrency benchmark runner (Phase 12).

Measures actual p50/p95/p99 latency, throughput, error rates, and Python heap delta
against the hardened FastAPI + SQLAlchemy + DistributedRateLimiter stack.
Usage:
    python scripts/run_benchmarks.py
"""

from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
import threading
import time
import tracemalloc
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("MOCK_VERTEX_VEO", "true")
os.environ.setdefault("MOCK_TTS", "true")
os.environ.setdefault("CELERY_ALWAYS_EAGER", "true")

import app.db as db_module  # noqa: E402
from app.main import app  # noqa: E402
from app.security import rate_limiter  # noqa: E402
from app.tasks import celery_app, configure_celery_app  # noqa: E402


def _pct(samples_ms: list[float], p: float) -> float:
    if not samples_ms:
        return 0.0
    ordered = sorted(samples_ms)
    idx = min(len(ordered) - 1, max(0, math.ceil((p / 100.0) * len(ordered)) - 1))
    return round(ordered[idx], 2)


def _summarize(name: str, latencies_ms: list[float], wall_s: float, errors: int) -> dict:
    total = len(latencies_ms)
    return {
        "scenario": name,
        "requests": total,
        "errors": errors,
        "error_rate_pct": round((errors / total) * 100.0, 2) if total else 0.0,
        "wall_seconds": round(wall_s, 3),
        "throughput_rps": round(total / wall_s, 2) if wall_s > 0 else 0.0,
        "avg_ms": round(statistics.mean(latencies_ms), 2) if latencies_ms else 0.0,
        "p50_ms": _pct(latencies_ms, 50),
        "p95_ms": _pct(latencies_ms, 95),
        "p99_ms": _pct(latencies_ms, 99),
        "max_ms": round(max(latencies_ms), 2) if latencies_ms else 0.0,
    }


def main() -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            db_url = f"sqlite:///{(tmp_path / 'bench.db').as_posix()}"
            os.environ["DATABASE_URL"] = db_url
            os.environ["STORAGE_ROOT"] = str(tmp_path / "storage")
            os.environ["INITIAL_PROMO_CREDITS"] = "50"
            os.environ["RATE_LIMIT_LOGIN_PER_MINUTE"] = "1000"
            os.environ["RATE_LIMIT_REGISTER_PER_MINUTE"] = "1000"
            os.environ["RATE_LIMIT_GENERATE_PER_MINUTE"] = "1000"
            os.environ["RATE_LIMIT_DOWNLOAD_PER_MINUTE"] = "1000"
            configure_celery_app(celery_app)
            db_module.configure_database(db_url)
            db_module.init_db()
            rate_limiter.reset()

            tracemalloc.start()
            results: list[dict] = []

            try:
                with TestClient(app) as client:
                    # Scenario 1: Concurrent registrations + logins (20 concurrent auth requests)
                    auth_lat: list[float] = []
                    auth_err = 0
                    lock = threading.Lock()

                    def _auth_worker(idx: int) -> None:
                        nonlocal auth_err
                        t0 = time.perf_counter()
                        res = client.post(
                            "/v1/auth/register",
                            json={"email": f"bench-{idx}@example.com", "password": "BenchPass123!"},
                        )
                        dt = (time.perf_counter() - t0) * 1000.0
                        with lock:
                            auth_lat.append(dt)
                            if res.status_code != 201:
                                auth_err += 1

                    t_start = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        list(pool.map(_auth_worker, range(20)))
                    results.append(
                        _summarize(
                            "concurrent_register_20",
                            auth_lat,
                            time.perf_counter() - t_start,
                            auth_err,
                        )
                    )

                    # Main workspace owner for reservation + generation + download scenarios
                    owner = client.post(
                        "/v1/auth/register",
                        json={"email": "bench-owner@example.com", "password": "BenchPass123!"},
                    ).json()
                    headers = {"Authorization": f"Bearer {owner['access_token']}"}
                    ws_id = owner["primary_workspace_id"]

                    # Scenario 2: Concurrent credit reservation race (30 threads / 50 credits)
                    res_lat: list[float] = []
                    res_err = 0

                    def _reserve_worker(idx: int) -> None:
                        nonlocal res_err
                        t0 = time.perf_counter()
                        try:
                            with db_module.SessionLocal() as session:
                                jid = str(uuid.uuid4())
                                session.add(
                                    db_module.VideoJob(
                                        id=jid,
                                        workspace_id=ws_id,
                                        user_id=owner["user"]["id"],
                                        product_url=f"https://luminabotanics.com/p/{idx}",
                                        target_language="en",
                                        status="CREATED",
                                        reserved_credits=1,
                                    )
                                )
                                session.flush()
                                db_module.reserve_credit_atomically(
                                    session,
                                    workspace_id=ws_id,
                                    job_id=jid,
                                    user_id=owner["user"]["id"],
                                    cost=1,
                                    reason=f"bench-{idx}",
                                )
                                session.commit()
                        except Exception:
                            with lock:
                                res_err += 1
                        finally:
                            dt = (time.perf_counter() - t0) * 1000.0
                            with lock:
                                res_lat.append(dt)

                    t_start = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=12) as pool:
                        list(pool.map(_reserve_worker, range(30)))
                    results.append(
                        _summarize(
                            "concurrent_credit_reservations_30",
                            res_lat,
                            time.perf_counter() - t_start,
                            res_err,
                        )
                    )

                    # Scenario 3: End-to-end concurrent mocked AI + FFmpeg generation (6 jobs)
                    gen_lat: list[float] = []
                    gen_err = 0
                    completed_job_ids: list[str] = []

                    def _gen_worker(idx: int) -> None:
                        nonlocal gen_err
                        t0 = time.perf_counter()
                        res = client.post(
                            "/v1/videos/generate",
                            headers=headers,
                            json={
                                "workspace_id": ws_id,
                                "product_url": f"https://luminabotanics.com/products/bench-{idx}",
                                "target_language": "en",
                            },
                        )
                        dt = (time.perf_counter() - t0) * 1000.0
                        with lock:
                            gen_lat.append(dt)
                            if res.status_code != 202 or res.json().get("status") != "COMPLETED":
                                gen_err += 1
                            else:
                                completed_job_ids.append(res.json()["id"])

                    t_start = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        list(pool.map(_gen_worker, range(6)))
                    results.append(
                        _summarize(
                            "concurrent_e2e_video_render_6",
                            gen_lat,
                            time.perf_counter() - t_start,
                            gen_err,
                        )
                    )

                    # Scenario 4: Concurrent signed MP4 downloads (20 downloads)
                    dl_lat: list[float] = []
                    dl_err = 0
                    signed_path = client.get(
                        f"/v1/videos/{completed_job_ids[0]}/signed-url", headers=headers
                    ).json()["download_path"]

                    def _dl_worker(_idx: int) -> None:
                        nonlocal dl_err
                        t0 = time.perf_counter()
                        res = client.get(signed_path)
                        dt = (time.perf_counter() - t0) * 1000.0
                        with lock:
                            dl_lat.append(dt)
                            if res.status_code != 200 or len(res.content) < 1024:
                                dl_err += 1

                    t_start = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        list(pool.map(_dl_worker, range(20)))
                    results.append(
                        _summarize(
                            "concurrent_signed_downloads_20",
                            dl_lat,
                            time.perf_counter() - t_start,
                            dl_err,
                        )
                    )

                    rec = client.get(
                        f"/v1/workspaces/{ws_id}/credits/reconcile", headers=headers
                    ).json()

                current_mem, peak_mem = tracemalloc.get_traced_memory()
                tracemalloc.stop()

                report = {
                    "benchmark_results": results,
                    "reconciliation_after_load": rec,
                    "peak_traced_memory_mb": round(peak_mem / (1024 * 1024), 2),
                }
                print(json.dumps(report, indent=2))
            finally:
                db_module.engine.dispose()


if __name__ == "__main__":
    main()
