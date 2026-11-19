# Changelog

## [2.1.0] — Enterprise Production Hardening & Commercial Readiness (2026-11-20)

### Background Job Reliability & Safe Crash Recovery (`services/worker/app/tasks.py`, `db.py`, `config.py`)
- Eliminated silent production fallback to `memory://` broker and `CELERY_ALWAYS_EAGER=true` (`validate_production_config()`, `configure_celery_app()`, `dispatch_video_job()`). Missing/unreachable Redis now fails closed with `BrokerUnavailableError`, refunds the reserved credit atomically, and returns `HTTP 503`.
- Enforced Celery task soft/hard timeouts (`JOB_SOFT_TIME_LIMIT_SECONDS`, `JOB_HARD_TIME_LIMIT_SECONDS`), `task_acks_late=True`, `worker_prefetch_multiplier=1`, and bounded retries with exponential backoff + jitter separating `TransientJobError` from `PermanentJobError`.
- Added atomic worker job ownership and crash recovery (`worker_id`, `lease_expires_at`, `heartbeat_at`, monotonic `fencing_token`, and `correlation_id` via migration `004_job_leases_and_immutability.sql`). Active workers renew leases via `_LeaseHeartbeatThread`; every intermediate/final state transition verifies `(worker_id, fencing_token)` (`StaleWorkerLeaseError`); `recover_interrupted_jobs()` reclaims only expired or unclaimed stale jobs and refunds credits at most once.
- Fixed a concurrent file write race in `ensure_sample_fixture()` (`services/worker/app/veo.py`) discovered during Phase 12 parallel load testing using `_FIXTURE_LOCK` + atomic `os.replace()`.

### Distributed Rate Limiting & Connection-Time SSRF Defense (`services/worker/app/security.py`, `scraper.py`)
- Replaced process-local rate limiting with `DistributedRateLimiter` supporting Redis atomic Lua sliding-window counters + burst protection shared across API instances (and deterministic `SharedRateLimitStore` / non-production local fallback), enforcing `HTTP 429`, `Retry-After`, and `X-RateLimit-*` across 8 separate configurable categories (`auth_login`, `auth_register`, `auth_password_reset`, `video_generate`, `video_render_retry`, `product_scrape`, `file_download`, `billing_checkout`).
- Upgraded SSRF protection with `SSRFSafeNetworkBackend` (`httpcore.SyncBackend`) pinning DNS resolution strictly to validated global IPs at TCP socket connection time, blocking CGNAT (`100.64.0.0/10`), loopback/private/link-local/metadata/IPv6-mapped/6to4/Teredo and obfuscated IP literals, restricting internal ports, revalidating every redirect hop, capping response bytes (`Accept-Encoding: identity`), and enforcing `12s` wall-clock deadlines and Content-Type checks.

### Billing Reconciliation, Database RLS & Auth/RBAC Hardening (`billing.py`, `auth.py`, `main.py`, `schema.sql`)
- Reconciled out-of-order Stripe `charge.refunded` / `charge.dispute.created` webhooks automatically upon delayed `checkout.session.completed` / `async_payment_succeeded` delivery (`billing.py`), added `ON DELETE RESTRICT` + `trg_credit_ledger_no_delete` SQL trigger + ORM `before_delete`/`before_update` immutability guards, and exposed `GET /v1/workspaces/{workspace_id}/credits/reconcile`.
- Added PostgreSQL connection pool configuration (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`) and enabled `FORCE ROW LEVEL SECURITY` across all tables in `schema.sql` and migration `004`.
- Rejected valid JWTs belonging to locked accounts (`HTTP 403`) in `get_current_user()`, added `POST /v1/auth/logout-all` (and Studio BFF allowlist support), added `DELETE /v1/workspaces/{workspace_id}/members/{member_user_id}` enforcing owner/admin hierarchy, propagated `X-Request-ID` to `VideoJob.correlation_id`, enriched `GET /health`, and added `GET /v1/ops/metrics`.

### CI/CD, Testing, Benchmarks & Operational Runbooks
- Hardened `.github/workflows/ci.yml` (`permissions: contents: read`, `pip-audit --strict --desc`, schema migration smoke verification, `npm audit --omit=dev --audit-level=high`, secret pattern check) and added `[prod]`/`[dev]` extras in `services/worker/pyproject.toml`.
- Added regression suites in `services/worker/tests/test_hardening_phases.py` (`36` passing Python tests total), Studio BFF tests in `apps/studio/src/__tests__/studio.test.ts` (`9/9` passing), and concurrent benchmark runner `services/worker/scripts/run_benchmarks.py` (`0.0%` errors, `is_balanced: true`).
- Authored full audit and enterprise operational docs: `AUDIT/PRODUCTION_HARDENING_AUDIT.md`, `AUDIT/FINAL_PRODUCTION_READINESS_REPORT.md`, `PRODUCTION_READINESS.md`, `DEPLOYMENT_GUIDE.md`, `ENVIRONMENT_VARIABLES.md`, `DATABASE_MIGRATIONS.md`, `BACKGROUND_JOBS.md`, `INCIDENT_RESPONSE.md`, `BACKUP_AND_RECOVERY.md`, `MONITORING.md`, and `TESTING_GUIDE.md`.

## [2.0.0] — Commercial SaaS Hardening & Pipeline Repair

### Security & Multi-Tenant Architecture
- Implemented user accounts, salted PBKDF2-SHA256 authentication, JWT + rotating HttpOnly refresh token sessions, email verification, password reset flows, and account brute-force lockouts (`services/worker/app/auth.py`).
- Replaced shared hardcoded `DEFAULT_WORKSPACE_ID` (`00000000-0000-0000-0000-000000000001`) and `DEFAULT_OWNER_ID` across both backend and Studio frontend with tenant-isolated workspaces and `owner` / `admin` / `member` RBAC enforcement (`require_workspace_role`).
- Removed unauthenticated `/static/renders` static mount and Studio's fake MP4/preset/credit fallbacks; all downloads require JWT membership or HMAC-signed tokens (`services/worker/app/storage.py`).
- Added fail-closed startup configuration checks (`validate_production_config()`), sliding-window rate limiting, `413` body size limits, explicit CORS origin checks, `WORKER_API_KEY` enforcement, and redacted JSON audit logging (`services/worker/app/security.py`).
- Upgraded `next` in `apps/studio` from `14.2.25` to `14.2.35`.

### Billing & Credit Accounting
- Expanded `credit_ledger` into a full immutable transaction journal recording user, workspace, transaction type (`promo_grant`, `purchase`, `video_reservation`, `video_deduction`, `video_refund`, `admin_adjustment`, `payment_refund`), delta, previous balance, new balance, status, and payment/job references (`services/worker/app/db.py`).
- Added database migrations (`001_initial_schema.sql`, `002_saas_multi_tenant_auth_billing.sql`, `app/migrations.py`) supporting non-destructive SQLite upgrades and PostgreSQL RLS policies.
- Implemented server-authoritative Stripe Checkout (`pack_id` pricing resolved exclusively server-side), raw-body HMAC `Stripe-Signature` verification with replay window checks, idempotent `stripe_events` deduplication, and refund/dispute credit reversal (`services/worker/app/billing.py`).
- Guarded `dev-topup` strictly behind `not production and ENABLE_DEV_TOPUP=true` (`403` otherwise) and gated `admin-adjust` to platform administrators / `X-Admin-Secret`.

### AI Pipeline, Scraping & Video Rendering
- Removed fabricated storefront presets/prices (`CATALOG_PRESETS`, `$39.00`) from `scraper.py` and `tts.py`; implemented SSRF-guarded live extraction reporting explicit `verified_fields`, `missing_fields`, and `requires_user_confirmation`.
- Added strict validation, retries, base64 product image conditioning, and authenticated GCS object downloads in Vertex AI Veo client (`services/worker/app/veo.py`) and strict Cloud TTS error handling without live-mode fixture/oscillator fallbacks (`services/worker/app/tts.py`).
- Standardized job lifecycle states (`CREATED -> QUEUED -> PROCESSING -> RENDERING -> COMPLETED | FAILED | CANCELLED`), FFmpeg output stream/duration verification prior to finalizing credit deductions, customer cancel + retry endpoints, and crash recovery (`recover_interrupted_jobs()`).

### Creator Studio Frontend & CI/Docs
- Added `AuthModal.tsx`, workspace switcher/creation, uploaded product asset selector/uploader, aspect ratio (`9:16` / `16:9`) & clip duration (`4s` / `6s` / `8s`) selectors, honest storefront confirmation gate, signed link copy, cancel/retry buttons, and Stripe Checkout flow.
- Added automated frontend tests (`apps/studio/src/__tests__/studio.test.ts`), expanded worker security/billing/AI/concurrency test suite (`services/worker/tests/test_security_billing_ai.py`), GitHub Actions workflow (`.github/workflows/ci.yml`), and full operational/API/security documentation.
