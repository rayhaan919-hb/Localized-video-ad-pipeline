# Background Jobs, Leases & Safe Crash Recovery Architecture

## Overview

Video ad generation runs asynchronously via Celery (`services/worker/app/tasks.py`) backed by Redis (`REDIS_URL`).

```
[API: POST /v1/videos/generate]
   │ 1. Atomic reserve_credit_atomically (status=CREATED -> QUEUED)
   │ 2. dispatch_video_job() -> fail-closed check (Redis reachable, worker if required)
   ▼
[Redis Broker] ──▶ [Celery Worker (worker_prefetch_multiplier=1, acks_late=True)]
                      │
                      ├── acquire_job_lease(): sets worker_id, lease_expires_at, fencing_token++
                      ├── _LeaseHeartbeatThread: renews lease every JOB_HEARTBEAT_INTERVAL_SECONDS
                      ├── Stage transitions: UPDATE ... WHERE worker_id=:w AND fencing_token=:tok
                      ├── Success: stores private MP4, transitions COMPLETED, finalize_credit_deduction()
                      ├── Transient error: releases lease, retry_count++, self.retry() with exp backoff+jitter
                      ├── Permanent error: transitions FAILED, refund_credit_atomically() once
                      └── Worker killed -> lease expires -> recover_interrupted_jobs() increments fencing_token++ & refunds once
```

---

## Guarantees Implemented (Phases 2 & 3)

1. **No Silent Production Fallbacks:**
   - When `APP_ENV=production` or `REQUIRE_REDIS_BROKER=true`, `validate_production_config()` and `configure_celery_app()` forbid `CELERY_ALWAYS_EAGER=true` and forbid `memory://` or unreachable Redis brokers.
   - If Redis goes down while handling `POST /v1/videos/generate`, `dispatch_video_job()` raises `BrokerUnavailableError`; the API marks the job `FAILED` (`BROKER_UNAVAILABLE`), refunds the reserved credit atomically, and returns `HTTP 503` without switching execution modes.
2. **Timeouts & Retries with Backoff + Jitter:**
   - Celery enforces `task_soft_time_limit` (`300s` default) and `task_time_limit` (`360s` default), `task_acks_late=True`, `worker_prefetch_multiplier=1`, and `task_reject_on_worker_lost=True`.
   - `is_retryable_exception()` separates transient errors (`TransientJobError`, `httpx.TimeoutException`, `SoftTimeLimitExceeded`, HTTP `429`/`5xx` provider errors) from permanent errors (`PermanentJobError`, validation errors, policy violations).
   - `compute_retry_countdown()` computes bounded exponential backoff with randomized jitter (`0.5x`–`1.0x` multiplier up to `JOB_RETRY_MAX_DELAY_SECONDS`). During retries, the original credit reservation stays held without double-charging.
3. **Exclusive Leases, Heartbeats & Fencing Tokens:**
   - Before touching external providers or storage, a worker must win `acquire_job_lease()`, which atomically sets `worker_id`, `heartbeat_at`, `lease_expires_at`, and increments `fencing_token`.
   - Duplicate Celery task deliveries cannot acquire an already-leased active job or re-run a `COMPLETED` / `CANCELLED` job (`skipped_duplicate: True`).
   - `_LeaseHeartbeatThread` periodically invokes `renew_job_lease()` on a dedicated DB session for the lifetime of long-running AI/FFmpeg execution.
   - Every intermediate `_fenced_transition()` and final completion/failure update validates `VideoJob.worker_id == owner_id AND VideoJob.fencing_token == fencing_token`. Any stalled worker resuming after lease expiration or cancellation hits `StaleWorkerLeaseError`, cleans up scratch files, and exits without corrupting job state or double-refunding credits.
4. **Lease-Aware Crash Recovery (`recover_interrupted_jobs()`):**
   - Active jobs with `lease_expires_at > now` are **never** reclaimed regardless of job age.
   - Only jobs with expired leases (`lease_expires_at <= now`) or legacy/unleased rows older than `JOB_UNCLAIMED_GRACE_SECONDS` are atomically transitioned to `FAILED` (`WORKER_LEASE_EXPIRED` / `WORKER_INTERRUPTED`), have `fencing_token` incremented, and receive a single idempotent `refund_credit_atomically()`.

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
