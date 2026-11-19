# Revalidated Enterprise Production Hardening Audit

**Audit Baseline Commit:** `dcf344d` (`main`)  
**Audit Date:** 2026-11-20  
**Scope:** Full-stack audit of FastAPI API (`services/worker/app/main.py`), Celery/Redis pipeline (`tasks.py`), Auth/RBAC (`auth.py`), Billing (`billing.py`), SSRF/Scraper (`scraper.py`), Security Middleware (`security.py`), Database & RLS (`db.py`, `migrations.py`, `schema.sql`), Next.js Studio BFF (`apps/studio/`), and CI/CD (`.github/workflows/ci.yml`).

---

## 1. Executive Revalidation Verdict

The application already possessed a strong security baseline in several critical layers (PBKDF2-SHA256 authentication with session rotation & reuse detection, atomic `Workspace.credit_balance >= cost` SQL reservations, HMAC Stripe signature verification, private workspace storage path traversal guards, BFF HttpOnly cookie wrapping, and CSP headers). However, independent inspection of the live code confirmed **3 P0 Critical**, **4 P1 High**, and **3 P2 Operational** gaps blocking commercial production deployment.

---

## 2. Confirmed Problems (`P0`–`P2`)

### `P0-001` — Silent Celery Fallback to In-Memory Broker & Eager Execution
- **Severity:** **P0 (Critical Reliability & Architecture Integrity)**
- **Affected Files:** `services/worker/app/tasks.py` (`lines 38-59`), `services/worker/app/config.py` (`lines 421-478`), `services/worker/app/main.py` (`lines 1377-1408`)
- **Root Cause:**
  1. At module import time, `tasks.py` calls `_redis_up = is_redis_reachable(settings.REDIS_URL)` and silently downgrades to `broker="memory://"`, `backend="cache+memory://"`, and `task_always_eager=True` whenever Redis is unreachable—even when `APP_ENV=production`.
  2. `validate_production_config()` does not require a live `redis://` / `rediss://` broker or reject `CELERY_ALWAYS_EAGER=true`.
  3. `process_video_job` lacks task execution timeouts (`soft_time_limit` / `time_limit`), `acks_late=True`, `worker_prefetch_multiplier=1`, and retry classification with exponential backoff and jitter.
- **Recommended Solution:** Enforce fail-closed production broker validation (`REQUIRE_REDIS_BROKER`, forbid `CELERY_ALWAYS_EAGER=true` in production), validate broker/worker readiness explicitly during `dispatch_video_job()`, configure task timeouts and `acks_late`, classify transient vs permanent errors with jittered exponential backoff, and keep credit reservations intact across retries.
- **Testing Requirements:** Production config validation with unreachable Redis / eager mode enabled; HTTP `503` + clean credit refund on Redis unavailability; transient timeout retry leading to success without double charges; permanent failure immediate refund; duplicate task delivery deduplication.

### `P0-002` — Age-Only Job Recovery & Absence of Worker Leases / Fencing Tokens
- **Severity:** **P0 (Critical Data Integrity & Double-Execution Risk)**
- **Affected Files:** `services/worker/app/tasks.py` (`lines 133-150, 312-345, 424-463`), `services/worker/app/db.py` (`lines 228-276`), `services/worker/app/main.py` (`line 318`)
- **Root Cause:**
  1. `recover_interrupted_jobs(min_age_seconds)` determines liveness strictly from `VideoJob.updated_at <= cutoff`, with no `worker_id`, `lease_expires_at`, `heartbeat_at`, or monotonic `fencing_token`. Legitimate long-running Veo generations could be falsely aborted if a stage exceeds `min_age_seconds`.
  2. `_transition()` in `tasks.py` mutates ORM fields and commits without verifying worker ownership or `fencing_token`, allowing a stalled worker waking up after crash/recovery to overwrite a `FAILED`/`CANCELLED` record.
- **Recommended Solution:** Add `worker_id`, `lease_expires_at`, `heartbeat_at`, `fencing_token`, and `correlation_id` to `video_jobs` (`004_job_leases_and_immutability.sql`). Implement atomic `acquire_job_lease()`, background heartbeat `renew_job_lease()`, fencing-token-checked conditional SQL transitions (`StaleWorkerLeaseError`), and lease-expiry-based `recover_interrupted_jobs()`.
- **Testing Requirements:** Normal long-running active lease preserved during recovery; worker crash/expired lease reclaimed with idempotent single refund; competing workers blocked; stale worker rejected via `fencing_token` mismatch; repeated recovery idempotency.

### `P0-003` — SSRF DNS Rebinding Window (TOCTOU) & Stream Hardening Gaps
- **Severity:** **P0 (Critical Security Vulnerability)**
- **Affected Files:** `services/worker/app/scraper.py` (`lines 41-101, 327-364`)
- **Root Cause:**
  1. `validate_public_http_url()` resolves DNS with `socket.getaddrinfo()`, after which `httpx.Client.stream()` performs a second independent DNS lookup—leaving a DNS rebinding TOCTOU window where the second lookup can resolve to `127.0.0.1` or `169.254.169.254`.
  2. `_is_forbidden_ip()` omits explicit global checks (`not ip_obj.is_global`, CGNAT `100.64.0.0/10`, 6to4/Teredo) and non-canonical IP representations (`0x7f000001`, octal/integer IPs).
  3. `_fetch_with_ssrf_redirects()` lacks wall-clock stream deadlines, `Accept-Encoding: identity` / decompression-bomb protection, Content-Type enforcement, and dangerous internal port restrictions.
- **Recommended Solution:** Pin validated destination IPs directly inside a custom `httpcore.SyncBackend` / `httpx.HTTPTransport` (`SSRFSafeTransport`) so the TCP socket connects solely to the validated global IP; block CGNAT/non-global/unusual IP literals and internal service ports; enforce total wall-clock timeout, Content-Type whitelist, and `Accept-Encoding: identity` + stream byte cap across every redirect hop.
- **Testing Requirements:** SSRF regression coverage for private IPv4/IPv6, localhost, `::1`, `::ffff:127.0.0.1`, cloud metadata, CGNAT, octal/hex/integer IPs, redirect chains, oversized/compressed responses, and simulated DNS rebinding.

### `P1-001` — Process-Local Rate Limiting Bypassable Across Multiple Instances
- **Severity:** **P1 (Serious Multi-Instance Reliability & Security Gap)**
- **Affected Files:** `services/worker/app/security.py` (`lines 97-166`), `services/worker/app/main.py` (`lines 295-311` and endpoints)
- **Root Cause:** `SlidingWindowRateLimiter` stores buckets exclusively in Python heap memory (`defaultdict(deque)`), allowing attackers to multiply quotas across `N` workers/containers. Separate configurable rate-limit buckets are absent for registration, password reset, render retry, file downloads, and billing checkout.
- **Recommended Solution:** Implement Redis-backed atomic Lua sliding-window `DistributedRateLimiter` shared across instances (with pluggable shared store & non-production local fallback), burst protection, `429` + `Retry-After` + `X-RateLimit-*` headers, and distinct configurable limits across all 8 endpoint classes.
- **Testing Requirements:** Multi-instance shared counter enforcement across two independent limiter instances, per-category `429` + `Retry-After` enforcement, and burst limit tests.

### `P1-002` — Out-of-Order Stripe Refund Handling & Ledger Immutability Enforcement
- **Severity:** **P1 (Serious Financial Data Integrity Gap)**
- **Affected Files:** `services/worker/app/billing.py` (`lines 389-506`), `services/worker/app/db.py` (`lines 278-318`), `schema.sql` (`lines 107-130`)
- **Root Cause:**
  1. If `charge.refunded` / `charge.dispute.created` arrives before `checkout.session.completed`, `billing.py` records `refund_without_matching_purchase` (`credits_delta=0`), and the delayed purchase webhook never reconciles the prior refund.
  2. `credit_ledger` relies on convention rather than ORM/SQL delete-prevention triggers and uses `ON DELETE CASCADE` from `workspaces` in `schema.sql`.
  3. No API/helper verifies `workspace.credit_balance == SUM(credit_ledger.delta)` continuously.
- **Recommended Solution:** Persist `amount_cents` on unmatched refunds and reconcile automatically when the purchase webhook completes; enforce `before_delete` / `before_update` ORM guards + SQL `prevent_credit_ledger_delete` triggers; change `schema.sql` ledger workspace FK to `ON DELETE RESTRICT`; add `reconcile_workspace_credits()` and `/v1/workspaces/{id}/credits/reconcile`.
- **Testing Requirements:** Out-of-order refund-then-purchase reconciliation test, ledger deletion rejection test, and concurrent credit balance invariant reconciliation test.

### `P1-003` — Database Connection Pool Configuration & `FORCE ROW LEVEL SECURITY`
- **Severity:** **P1 (Serious Database Production Hardening Gap)**
- **Affected Files:** `services/worker/app/db.py` (`lines 364-377`), `schema.sql` (`lines 157-166`)
- **Root Cause:** `_build_engine()` relies on SQLAlchemy defaults without explicit configurable `pool_size`, `max_overflow`, `pool_timeout`, or `pool_recycle` for PostgreSQL. `schema.sql` enables `ROW LEVEL SECURITY` without `FORCE ROW LEVEL SECURITY`, leaving table-owner roles exempt if ever reused directly.
- **Recommended Solution:** Configure explicit PostgreSQL pooling parameters from settings in `_build_engine()` and apply `FORCE ROW LEVEL SECURITY` in `schema.sql` and migration `004`.
- **Testing Requirements:** Engine pool configuration verification for PostgreSQL URLs, non-destructive migration `004` upgrade on legacy SQLite databases, and SQL policy verification.

### `P1-004` — Locked-Account JWT Enforcement, Session Revocation & Member Removal RBAC
- **Severity:** **P1 (Security Hardening Gap)**
- **Affected Files:** `services/worker/app/auth.py` (`lines 525-554`), `services/worker/app/main.py` (`lines 548-563, 842-921`)
- **Root Cause:** `get_current_user()` does not reject valid JWTs belonging to accounts currently locked via `locked_until`; users lack a self-service `"logout all devices"` endpoint (`POST /v1/auth/logout-all`); admins/owners lack a `DELETE /v1/workspaces/{id}/members/{uid}` endpoint with privilege-escalation guards.
- **Recommended Solution:** Reject locked users in `get_current_user()`, implement `revoke_all_user_sessions()` + `POST /v1/auth/logout-all`, and implement `DELETE /v1/workspaces/{id}/members/{uid}` enforcing owner/admin hierarchy.
- **Testing Requirements:** Locked JWT rejection (`403`), `logout-all` revoking all refresh sessions, and member removal RBAC / anti-escalation tests.

### `P2-001` — CI/CD Permissions, Dependency Vulnerability & Migration Gates
- **Severity:** **P2 (Operational & Supply-Chain Security)**
- **Affected Files:** `.github/workflows/ci.yml`, `services/worker/pyproject.toml`
- **Root Cause:** `ci.yml` lacks explicit `permissions: contents: read`, `pip-audit`, `npm audit --omit=dev --audit-level=high`, secret-pattern check, and schema migration verification.
- **Recommended Solution:** Add least-privilege workflow permissions, `pip-audit` dependency check, `npm audit`, and automated migration smoke checks in CI.

### `P2-002` — Job Correlation Propagation, Metrics Endpoint & Load Benchmarking
- **Severity:** **P2 (Observability & Capacity Verification)**
- **Affected Files:** `services/worker/app/security.py`, `services/worker/app/main.py`, `services/worker/app/tasks.py`
- **Root Cause:** `X-Request-ID` correlation IDs are not stored on `VideoJob` or logged per Celery pipeline stage; operators lack a `/v1/ops/metrics` endpoint reporting queue depth, lease health, failure rates, and stage timings; no load benchmark suite measures latency percentiles under concurrency.
- **Recommended Solution:** Propagate `correlation_id` through `VideoJob` and structured worker logs, track stage latencies in `MetricsRegistry`, expose `/v1/ops/metrics` + enriched `/health`, and implement automated staging + load benchmark suites.

### `P2-003` — Commercial Documentation Suite Gaps
- **Severity:** **P2 (Operational Readiness)**
- **Affected Files:** Root operational docs & `AUDIT/*`
- **Root Cause:** Required commercial runbooks (`PRODUCTION_READINESS.md`, `DEPLOYMENT_GUIDE.md`, `ENVIRONMENT_VARIABLES.md`, `DATABASE_MIGRATIONS.md`, `BACKGROUND_JOBS.md`, `INCIDENT_RESPONSE.md`, `BACKUP_AND_RECOVERY.md`, `MONITORING.md`, `TESTING_GUIDE.md`, `AUDIT/FINAL_PRODUCTION_READINESS_REPORT.md`) do not yet exist in unified form matching the hardened design.
- **Recommended Solution:** Author the complete documentation set strictly grounded in the implemented codebase and verified test/benchmark runs.

---

## 3. Existing Verified Strengths Preserved

1. **Authentication & Session Hygiene:** PBKDF2-HMAC-SHA256 (`260,000` iterations), timing-equalized unknown-email handling, rotating SHA-256 hashed refresh sessions with reuse/theft revocation, disposable email blocking (`APP_ENV != test`), Google OAuth 2.0 + PKCE `S256` with HMAC-signed CSRF state cookie, and HttpOnly BFF cookie forwarding (`stripAuthTokensFromPayload`).
2. **Same-Origin CSRF & Private Storage:** All Studio BFF mutating routes enforce `assertSameOriginRequest()`, UUID path validation, CSP/HSTS headers, path-traversal-checked workspace directories, HMAC download URLs, and FFmpeg MP4 container + audio verification (`validate_mp4_file`).
3. **Credit Reservation Atomicity:** Conditional `UPDATE workspaces ... WHERE credit_balance >= cost RETURNING credit_balance` prevents race-induced negative balances alongside SQLite/PostgreSQL idempotency constraints.

---

## 4. Items Requiring External Staging Credentials

The following live cloud checks cannot execute authentically without buyer staging secrets and will be built as gated staging test infrastructure (`@pytest.mark.staging`) plus failure-mode simulations:
- Live PostgreSQL 15+ multi-role `SET ROLE authenticated` RLS execution check (`SUPABASE` / `DATABASE_URL`).
- Live multi-process Redis (`REDIS_URL`) + Celery worker SIGKILL / restart validation.
- Live Vertex AI Veo 3.1, Google Cloud TTS, and GCS signed-bucket object fetch (`GCP_PROJECT_ID`, `GCS_BUCKET`, ADC).
- Live Stripe test-mode Checkout Session & webhook signing (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, price IDs).
- Live SMTP delivery (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`).
