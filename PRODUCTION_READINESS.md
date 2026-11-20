# Production Readiness & Commercial Launch Gate Checklist

**Target Release:** `v2.2.0` (Final Production Hardening Pass on `production-final-hardening`)  
**Launch Verdict:** **Conditional Go — Ready for Staging Sign-Off**  
*(Local code, migrations `001`–`005`, transactional outbox, DB-clock atomic leases, security controls, worker & Studio unit/integration suites, Studio build, and concurrent benchmarks are verified locally; live staging cloud credentials are required for final PostgreSQL/Redis/Stripe/GCP staging sign-off prior to customer traffic.)*

---

## 1. Infrastructure & Fail-Closed Production Config

Verify the following settings in the target environment (`validate_production_config()` in [`services/worker/app/config.py`](./services/worker/app/config.py) aborts API/worker startup if any required control is violated):

- [ ] `APP_ENV=production`
- [ ] `DATABASE_URL` points to PostgreSQL 15+ (SQLite is forbidden; `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` tuned to DB capacity)
- [ ] `REDIS_URL` configured as `redis://` or `rediss://` and reachable over TCP (`REQUIRE_REDIS_BROKER=true` enforced automatically in production)
- [ ] `CELERY_ALWAYS_EAGER=false` (eager/in-memory fallback strictly forbidden)
- [ ] `REQUIRE_ACTIVE_CELERY_WORKER=true` recommended when dedicated Celery workers are online
- [ ] `WORKER_API_KEY` >= 24 characters matching between `apps/studio` and `services/worker`
- [ ] `AUTH_JWT_SECRET` >= 32 characters and `SIGNED_URL_SECRET` >= 32 characters (distinct high-entropy secrets)
- [ ] `CORS_ORIGINS` contains explicit HTTPS origins (wildcard `*` rejected in production) and `FRONTEND_APP_URL` matches the public Studio origin
- [ ] `TRUST_PROXY_HEADERS=true` **only** when deployed strictly behind a trusted reverse proxy / CDN stripping client-spoofed `X-Forwarded-For`
- [ ] `MOCK_VERTEX_VEO=false`, `MOCK_TTS=false`, `ENABLE_DEV_TOPUP=false`, `EXPOSE_DEV_AUTH_TOKENS=false`
- [ ] `GCP_PROJECT_ID`, `GCS_BUCKET`, and valid GCP credentials (`GOOGLE_APPLICATION_CREDENTIALS` or `VERTEX_ACCESS_TOKEN` or `GOOGLE_API_KEY`) provisioned
- [ ] `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `STRIPE_PRICE_STARTER_10` / `STRIPE_PRICE_GROWTH_50` / `STRIPE_PRICE_SCALE_200` set
- [ ] `REQUIRE_EMAIL_VERIFICATION=true` and transactional `SMTP_*` (or OAuth `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`) provisioned

---

## 2. Database Schema, RLS & Storage Readiness

- [ ] Apply [`schema.sql`](./schema.sql) and SQL migrations `001` through [`005_transactional_outbox_and_rls_hardening.sql`](./services/worker/migrations/005_transactional_outbox_and_rls_hardening.sql) (see [`DATABASE_MIGRATIONS.md`](./DATABASE_MIGRATIONS.md)).
- [ ] Verify `relrowsecurity = true` and `relforcerowsecurity = true` (`FORCE ROW LEVEL SECURITY`) on all 10 PostgreSQL tables (`schema_migrations`, `users`, `auth_sessions`, `stripe_events`, `workspaces`, `workspace_members`, `workspace_assets`, `video_jobs`, `credit_ledger`, `job_dispatch_outbox`).
- [ ] Confirm `trg_credit_ledger_no_delete` trigger is active on `credit_ledger` and application roles use `NOBYPASSRLS` (`pg_roles.rolbypassrls = false`).
- [ ] Confirm managed PostgreSQL PITR / WAL archiving and daily encrypted `pg_dump` backups are enabled (see [`BACKUP_AND_RECOVERY.md`](./BACKUP_AND_RECOVERY.md)).
- [ ] Confirm `STORAGE_ROOT` resides on persistent storage with private ACLs (and `GCS_BUCKET` versioning/lifecycle rules configured).

---

## 3. Background Workers, Leases & Observability

- [ ] Deploy dedicated Celery workers (`celery -A app.tasks.celery_app worker --concurrency=2 --prefetch-multiplier=1 -O fair --max-tasks-per-child=50`) — see [`BACKGROUND_JOBS.md`](./BACKGROUND_JOBS.md).
- [ ] Schedule periodic crash recovery every 60s calling `recover_interrupted_jobs(min_age_seconds=120)` (runs queued-safe `recover_expired_leases()` + `reconcile_dispatch_outbox()`).
- [ ] Confirm worker leases (`worker_id`, `lease_expires_at`, `heartbeat_at`, `fencing_token` via PostgreSQL `clock_timestamp()`) and timeouts (`JOB_SOFT_TIME_LIMIT_SECONDS=300`, `JOB_HARD_TIME_LIMIT_SECONDS=360`) behave cleanly under staging worker `SIGKILL`.
- [ ] Verify `GET /health` returns `HTTP 200` (`redis_broker=true`, `celery_eager_mode=false`, `ffmpeg_available=true`, `database="ok"`).
- [ ] Verify operator telemetry via `GET /v1/ops/metrics` (including `outbox` & `db_clock` diagnostics with `X-Admin-Secret` or platform admin JWT) and wire alert thresholds from [`MONITORING.md`](./MONITORING.md).

---

## 4. Security, SSRF, Multi-Tenant Auth & Billing Controls

- [x] **SSRF & Network Safety:** Verified connection-time IP pinning (`SSRFSafeNetworkBackend`), private/loopback/CGNAT/link-local/metadata/obfuscated-IP rejection, redirect hop revalidation, `Accept-Encoding: identity` + byte caps, `12s` wall-clock deadline, and Content-Type checks ([`scraper.py`](./services/worker/app/scraper.py)).
- [x] **Distributed Rate Limiting:** Verified Redis Lua sliding-window `DistributedRateLimiter` + shared counter semantics across instances, burst caps, and separate limits across 8 endpoint classes returning `429` + `Retry-After` ([`security.py`](./services/worker/app/security.py)).
- [x] **Auth & Workspace RBAC:** Verified `locked_until` rejection on existing access JWTs (`403`), `POST /v1/auth/logout-all`, BFF allowlist + HttpOnly cookies + same-origin CSRF checks + `X-Request-ID` echo, and `DELETE /v1/workspaces/{id}/members/{uid}` hierarchy guards ([`auth.py`](./services/worker/app/auth.py), [`main.py`](./services/worker/app/main.py)).
- [x] **Financial & Billing Ledger Integrity:** Verified Stripe HMAC signature + replay checks, idempotency, out-of-order `charge.refunded` -> `checkout.session.completed` reconciliation ([`billing.py`](./services/worker/app/billing.py)), ORM + SQL delete triggers, `ON DELETE RESTRICT`, and `GET /v1/workspaces/{id}/credits/reconcile` (`is_balanced: true` after concurrent load).
- [x] **CI/CD & Production Supply Chain:** Upgraded [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) to SHA-pinned Node 24 actions (`checkout`, `setup-python`, `setup-node`), added `mypy`, `postgres:16-alpine` + `redis:7-alpine` integration job, `pip-audit --strict --desc`, `npm audit --omit=dev --audit-level=high`, migration smoke check, and secret scan; `npm audit --omit=dev` verified `0 vulnerabilities`.

---

## 5. Pre-Launch Staging Go / No-Go Gates

All items below must pass in the staging environment before enabling real customer billing or production DNS:

1. **PostgreSQL 16+ Live RLS & Concurrency Verification:** Execute [`test_postgres_integration.py`](./services/worker/tests/test_postgres_integration.py) with `TEST_POSTGRES_URL` proving `NOBYPASSRLS` tenant isolation, `clock_timestamp()` lease races, and `trg_credit_ledger_no_delete`.
2. **Multi-Process Redis + Celery Worker Crash Drill:** Execute [`test_redis_celery_recovery.py`](./services/worker/tests/test_redis_celery_recovery.py) with `TEST_REDIS_URL` proving real Redis Lua limits, queued congestion preservation, duplicate delivery idempotency, `SIGKILL` lease recovery, and outbox relay recovery.
3. **Live Cloud Provider Smoke Tests:** Run [`test_staging_integrations.py`](./services/worker/tests/test_staging_integrations.py) with `STRIPE_STAGING_TEST=1` & `GCP_STAGING_TEST=1` against Stripe test mode, Vertex AI Veo 3.1, Google Cloud TTS, GCS bucket fetch, Google OAuth 2.0 consent exchange, and SMTP email delivery.
4. **Staging Load Benchmarks:** Execute `python scripts/run_staging_benchmarks.py --tiers 10,25,50,100` against real staging PostgreSQL + Redis and verify `0` errors with `credit_reconciliation_balanced: true`.
5. **See Consolidated Checklist & Evidence:** [`AUDIT/PRODUCTION_DEPLOYMENT_CHECKLIST.md`](./AUDIT/PRODUCTION_DEPLOYMENT_CHECKLIST.md), [`AUDIT/PRODUCTION_TEST_RESULTS.md`](./AUDIT/PRODUCTION_TEST_RESULTS.md), and [`AUDIT/FINAL_READINESS_SCORECARD.md`](./AUDIT/FINAL_READINESS_SCORECARD.md).
