# Background Jobs, Leases & Safe Crash Recovery Architecture

## Overview

Video ad generation runs asynchronously via Celery (`services/worker/app/tasks.py`) backed by Redis (`REDIS_URL`).

```
[API: POST /v1/videos/generate]
   │ 1. Atomic transaction: VideoJob(CREATED) + reserve_credit_atomically + JobDispatchOutbox(PENDING)
   │ 2. publish_outbox_event() -> fail-closed check (Redis reachable, worker if required)
   ▼
[Redis Broker] ──▶ [Celery Worker (worker_prefetch_multiplier=1, acks_late=True)]
                      │
                      ├── acquire_job_lease(): DB-clock lease, worker_id, fencing_token++, ignores terminal/leased jobs
                      ├── _LeaseHeartbeatThread: renews unexpired active lease via DB clock
                      ├── Stage transitions: UPDATE ... WHERE worker_id=:w AND fencing_token=:tok
                      ├── Success: stores private MP4, transitions COMPLETED, finalize_credit_deduction()
                      ├── Transient error: releases lease, retry_count++, self.retry() with exp backoff+jitter
                      ├── Permanent error: transitions FAILED, refund_credit_atomically() once
                      └── Worker killed -> lease expires -> recover_expired_leases() (active jobs only; NEVER queued jobs) + reconcile_dispatch_outbox()
```

---

## Guarantees Implemented (Phases 2, 3 & Final Hardening)

1. **No Silent Production Fallbacks & Transactional Dispatch Outbox:**
   - When `APP_ENV=production` or `REQUIRE_REDIS_BROKER=true`, `validate_production_config()` and `configure_celery_app()` forbid `CELERY_ALWAYS_EAGER=true` and forbid `memory://` or unreachable Redis brokers.
   - `POST /v1/videos/generate` writes `VideoJob`, credit reservation, and `JobDispatchOutbox` atomically in a single DB transaction (`005_transactional_outbox_and_rls_hardening.sql`), eliminating post-commit API crash orphans.
   - If Redis is unreachable on initial `publish_outbox_event(..., fail_job_on_broker_error=True)`, the API marks the job & outbox `FAILED` (`BROKER_UNAVAILABLE`), refunds the reserved credit atomically, and returns `HTTP 503` without switching execution modes. Deferred relays (`reconcile_dispatch_outbox()`) retry transient broker blips with bounded backoff (`max_attempts=5`).
2. **Timeouts & Retries with Backoff + Jitter:**
   - Celery enforces `task_soft_time_limit` (`300s` default) and `task_time_limit` (`360s` default), `task_acks_late=True`, `worker_prefetch_multiplier=1`, and `task_reject_on_worker_lost=True`.
   - `is_retryable_exception()` separates transient errors (`TransientJobError`, `httpx.TimeoutException`, `SoftTimeLimitExceeded`, HTTP `429`/`5xx` provider errors) from permanent errors (`PermanentJobError`, validation errors, policy violations).
   - `compute_retry_countdown()` computes bounded exponential backoff with randomized jitter (`0.5x`–`1.0x` multiplier up to `JOB_RETRY_MAX_DELAY_SECONDS`). During retries, the original credit reservation stays held without double-charging.
3. **Database-Clock Atomic Leases, Heartbeats & Fencing Tokens:**
   - All lease comparisons and updates use PostgreSQL `clock_timestamp()` (or SQLite `strftime`) via `db_now_expr()` / `db_offset_expr()` — never skewed multi-host Python timestamps.
   - `acquire_job_lease()` rejects duplicate deliveries on already-leased active jobs or terminal (`COMPLETED`/`FAILED`/`CANCELLED`) jobs (`skipped_duplicate: True`), and increments `fencing_token` atomically.
   - `_LeaseHeartbeatThread` periodically invokes `renew_job_lease()`, whose SQL `WHERE` enforces `status IN ACTIVE_EXECUTION_STATUSES AND lease_expires_at > db_now` so an expired or recovered job can never be revived.
   - Every intermediate `_fenced_transition()`, completion/failure write, and `cancel_video_job()` checks/increments `fencing_token` via compare-and-swap.
4. **Queued-Safe Lease Recovery (`recover_expired_leases()` / `recover_interrupted_jobs()`):**
   - Legitimate `CREATED`, `QUEUED`, and `PENDING` jobs waiting under Redis queue congestion are **never** scanned or failed by recovery regardless of age.
   - `recover_expired_leases()` scans only `ACTIVE_EXECUTION_STATUSES` (`PROCESSING`, `RENDERING`, `GENERATING_CLIPS`, `COMPOSITING`) with `FOR UPDATE SKIP LOCKED` on PostgreSQL and executes an atomic CAS `UPDATE` verifying `(id, status, worker_id, fencing_token, lease_expires_at <= db_now)` before cancelling any pending outbox row and issuing one idempotent `refund_credit_atomically()`.
   - `recover_interrupted_jobs()` invokes `recover_expired_leases()` and then runs `reconcile_dispatch_outbox()`.

---

## Deploying Celery Workers in Production

```bash
cd services/worker
export APP_ENV=production
celery -A app.tasks.celery_app worker \
  --loglevel=info \
  --concurrency=2 \
  --prefetch-multiplier=1 \
  -O fair
```

Recommended production flags:
- `--concurrency`: match vCPU/FFmpeg count (e.g. `2`–`4` per container).
- `--max-tasks-per-child=50`: periodically recycle worker processes to bound native FFmpeg memory growth.
- Run a scheduled periodic recovery cron/beat invocation calling `recover_interrupted_jobs(min_age_seconds=120)` every 60 seconds alongside startup recovery.
