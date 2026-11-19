# Production Readiness & Commercial Launch Gate Checklist

**Target Release:** `v2.1.0` (Enterprise Hardening Pass on `main`)  
**Launch Verdict:** **Conditional Go — Ready for Staging Sign-Off**  
*(Local code, schema/migrations, security controls, worker unit/integration suites, Studio build, and concurrent benchmarks are verified; live buyer cloud credentials are required for final staging sign-off prior to customer traffic.)*

---

## 1. Infrastructure & Fail-Closed Production Config

Verify the following settings in the target environment (`validate_production_config()` in [config.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/app/config.py) aborts API/worker startup if any required control is violated):

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

- [ ] Apply [schema.sql](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/schema.sql) and SQL migrations `001` through [004_job_leases_and_immutability.sql](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/migrations/004_job_leases_and_immutability.sql) (see [DATABASE_MIGRATIONS.md](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/DATABASE_MIGRATIONS.md)).
- [ ] Verify `rowsecurity = true` and `FORCE ROW LEVEL SECURITY` on all 9 PostgreSQL tables (`schema_migrations`, `users`, `auth_sessions`, `stripe_events`, `workspaces`, `workspace_members`, `workspace_assets`, `video_jobs`, `credit_ledger`).
- [ ] Confirm `trg_credit_ledger_no_delete` trigger is active on `credit_ledger`.
- [ ] Confirm managed PostgreSQL PITR / WAL archiving and daily encrypted `pg_dump` backups are enabled (see [BACKUP_AND_RECOVERY.md](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/BACKUP_AND_RECOVERY.md)).
- [ ] Confirm `STORAGE_ROOT` resides on persistent storage with private ACLs (and `GCS_BUCKET` versioning/lifecycle rules configured).

---

## 3. Background Workers, Leases & Observability

- [ ] Deploy dedicated Celery workers (`celery -A app.tasks.celery_app worker --concurrency=2 --prefetch-multiplier=1 -O fair --max-tasks-per-child=50`) — see [BACKGROUND_JOBS.md](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/BACKGROUND_JOBS.md).
- [ ] Schedule periodic crash recovery every 60s calling `recover_interrupted_jobs(min_age_seconds=120)`.
- [ ] Confirm worker leases (`worker_id`, `lease_expires_at`, `heartbeat_at`, `fencing_token`) and timeouts (`JOB_SOFT_TIME_LIMIT_SECONDS=300`, `JOB_HARD_TIME_LIMIT_SECONDS=360`) behave cleanly under staging worker `SIGKILL`.
- [ ] Verify `GET /health` returns `HTTP 200` (`redis_broker=true`, `celery_eager_mode=false`, `ffmpeg_available=true`, `database="ok"`).
- [ ] Verify operator telemetry via `GET /v1/ops/metrics` (with `X-Admin-Secret` or platform admin JWT) and wire alert thresholds from [MONITORING.md](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/MONITORING.md).

---

## 4. Security, SSRF, Multi-Tenant Auth & Billing Controls

- [x] **SSRF & Network Safety:** Verified connection-time IP pinning (`SSRFSafeNetworkBackend`), private/loopback/CGNAT/link-local/metadata/obfuscated-IP rejection, redirect hop revalidation, `Accept-Encoding: identity` + byte caps, `12s` wall-clock deadline, and Content-Type checks ([scraper.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/app/scraper.py)).
- [x] **Distributed Rate Limiting:** Verified Redis Lua sliding-window `DistributedRateLimiter` + shared counter semantics across instances, burst caps, and separate limits across 8 endpoint classes returning `429` + `Retry-After` ([security.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/app/security.py)).
- [x] **Auth & Workspace RBAC:** Verified `locked_until` rejection on existing access JWTs (`403`), `POST /v1/auth/logout-all`, BFF allowlist + HttpOnly cookies + same-origin CSRF checks, and `DELETE /v1/workspaces/{id}/members/{uid}` hierarchy guards ([auth.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/app/auth.py), [main.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/app/main.py)).
- [x] **Financial & Billing Ledger Integrity:** Verified Stripe HMAC signature + replay checks, idempotency, out-of-order `charge.refunded` -> `checkout.session.completed` reconciliation ([billing.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/app/billing.py)), ORM + SQL delete triggers, and `GET /v1/workspaces/{id}/credits/reconcile` (`is_balanced: true` after concurrent load).
- [x] **CI/CD & Production Supply Chain:** Hardened [.github/workflows/ci.yml](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/.github/workflows/ci.yml) (`permissions: contents: read`, `pip-audit`, `npm audit --omit=dev --audit-level=high`, migration smoke check, secret scan); `npm audit --omit=dev` verified `0 vulnerabilities`.

---

## 5. Pre-Launch Staging Go / No-Go Gates

All items below must pass in the staging environment before enabling real customer billing or production DNS:

1. **PostgreSQL 15+ Live RLS Verification:** Execute real SQL queries under `SET ROLE authenticated` (non-owner role) to verify cross-tenant `workspaces`, `video_jobs`, `credit_ledger`, and `workspace_assets` isolation.
2. **Multi-Process Redis + Celery Worker Crash Drill:** Start API + 2 Celery worker processes against real Redis, kill a busy worker via `SIGKILL`, verify lease renewal stops, confirm `recover_interrupted_jobs()` refunds once after `lease_expires_at`, and confirm no duplicate render/charge occurs if a stalled worker resumes.
3. **Live Cloud Provider Smoke Tests:** Run end-to-end staging tests against Vertex AI Veo 3.1, Google Cloud TTS, GCS bucket fetch, Google OAuth 2.0 consent exchange, SMTP email verification delivery, and Stripe test-mode webhooks (`stripe listen`).
4. **Post-Hardening Live Browser Regression Pass:** Re-run full end-to-end Creator Studio browser verification against the hardened stack (local Stage 9 browser subagent failed to start due to host socket `connectex` error; pre-hardening E2E passed and post-hardening `npm run verify:studio` passed `9/9` + clean Next.js `16.4.6` production build).
5. **CI `pip-audit` Execution:** Confirm GitHub Actions Linux runner passes `pip-audit --strict --desc` cleanly with zero unpatched Critical/High Python CVEs.
