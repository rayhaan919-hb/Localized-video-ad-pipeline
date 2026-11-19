# Observability, Structured Logging & Monitoring Guide

## 1. Structured JSON Logging & Correlation IDs
- `RequestContextMiddleware` (`services/worker/app/security.py`) assigns or validates `X-Request-ID` on every HTTP request, echoes it in response headers, and attaches it to `request.state.request_id`.
- `generate_video()` persists `correlation_id` on `VideoJob` and passes it into Celery's `process_video_job`.
- Every JSON log event emitted via `log_audit_event()` automatically redacts secret keys (`password`, `secret`, `token`, `api_key`, `authorization`, `signature`, `credential`, `cookie`, `private_key`) via `sanitize_log_data()`, while preserving operational identifiers (`request_id`, `job_id`, `worker_id`, `fencing_token`).

Key log events:
- `http_request` — HTTP method, path, status code, duration ms, `request_id`.
- `video_job_completed` — includes `worker_id`, `fencing_token`, `size_bytes`, and `stage_timings_ms` (`scrape_ms`, `tts_ms`, `veo_ms`, `ffmpeg_ms`, `total_ms`).
- `video_job_retry_scheduled` — transient exception, retry count, exponential backoff delay.
- `video_job_stale_worker_fenced` — blocked late overwrite by stale worker.
- `video_job_failed` — error class and credit refund confirmation.
- `stripe_credits_granted`, `stripe_webhook_signature_rejected` — billing audit events.
- `rate_limiter_redis_error`, `worker_api_key_rejected`, `workspace_access_denied` — security alerts.

---

## 2. Health & Metrics Endpoints

### `GET /health`
Unauthenticated readiness probe suitable for container orchestrators (`Kubernetes`, `Cloud Run`, `Fly.io`, `Render`):
- Probes DB (`SELECT 1`), FFmpeg binary availability, Redis broker connectivity (`redis_broker`), eager mode flag (`celery_eager_mode`), `queue_depth`, and `in_flight_jobs`.
- Returns `HTTP 503` if DB is unreachable or if `APP_ENV=production` detects `redis_broker=false` or `celery_eager_mode=true`.

### `GET /v1/ops/metrics`
Operator telemetry endpoint (requires `X-Admin-Secret` or authenticated platform admin in production):
- `db_latency_ms`: Live SQL round-trip timing.
- `rate_limiter_backend`: `"redis"`, `"shared_store"`, or `"local_memory_fallback"`.
- `queue`: `{ redis_broker, celery_eager_mode, require_redis_broker, queue_depth, active_workers }`.
- `jobs`: `{ in_flight, active_leases, expired_leases, total_failed }`.
- `telemetry`: HTTP status counters, rate-limit rejection counters, billing/job counters, and `p50`/`p95`/`p99`/`max` latency histograms for HTTP requests and per-stage AI timings (`stage.scrape`, `stage.tts`, `stage.veo`, `stage.ffmpeg`, `job.total`).

---

## 3. Recommended Production Alerts

| Alert Condition | Threshold | Severity |
| :--- | :--- | :---: |
| `/health` returns non-200 | 2 consecutive checks (`30s`) | **Critical** |
| `jobs.expired_leases > 0` | `>= 1` for `> 3 minutes` | **High** |
| `queue.queue_depth` sustained growth | `> 50` queued while `active_leases == 0` | **Critical** |
| `telemetry.counters["rate_limit.rejected.*"]` spike | `> 100 / 5 min` | **Warning** |
| `telemetry.timings["http.request"].p95_ms` | `> 2000 ms` (non-eager) | **High** |
| Stripe `stripe_webhook_signature_rejected` surge | `> 10 / 5 min` | **High** |
| External Sentry / OTLP hook | Configure `SENTRY_DSN` and `OTEL_EXPORTER_OTLP_ENDPOINT` in prod environment | Optional |
