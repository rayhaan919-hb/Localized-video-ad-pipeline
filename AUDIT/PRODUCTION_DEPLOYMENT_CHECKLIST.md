# Production Deployment & Launch Sign-Off Checklist

**Project:** Localized Video Ad Pipeline  
**Release Target:** `v2.2.0` (`production-final-hardening` -> `main`)  
**Scope:** Staging Validation Gates, Database & RLS Rollout, Worker/Outbox Topology, Observability, Rollback, and Commercial Cutover Sign-Off.

---

## 1. Environment & Secret Configuration Gate (`validate_production_config()`)

API and Celery workers automatically abort startup if any production invariant below is violated:

- [ ] **`APP_ENV=production`**
- [ ] **`DATABASE_URL`**: Managed PostgreSQL 15/16+ (`postgresql://` or `postgresql+psycopg://`); SQLite forbidden. Configure `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` to match PgBouncer/DB pool limits.
- [ ] **`REDIS_URL`**: Persistent `redis://` or `rediss://` reachable over TCP; **`CELERY_ALWAYS_EAGER=false`** (strictly enforced).
- [ ] **`REQUIRE_REDIS_BROKER=true`** and **`REQUIRE_ACTIVE_CELERY_WORKER=true`** (once worker pool is online).
- [ ] **Unique Cryptographic Secrets (`>= 32` chars):**
  - `AUTH_JWT_SECRET`
  - `SIGNED_URL_SECRET` (distinct from `AUTH_JWT_SECRET`)
  - `WORKER_API_KEY` (`>= 24` chars, shared identically between `apps/studio` BFF and `services/worker`)
  - `ADMIN_ADJUST_SECRET` (for `/v1/ops/metrics` & admin credit adjustments)
- [ ] **Mock & Dev Flags Disabled:**
  - `MOCK_VERTEX_VEO=false`, `MOCK_TTS=false`, `ENABLE_DEV_TOPUP=false`, `EXPOSE_DEV_AUTH_TOKENS=false`, `REQUIRE_EMAIL_VERIFICATION=true`
- [ ] **Origins & Proxy Trust:**
  - `CORS_ORIGINS`: Explicit HTTPS Studio origins only (no `*`).
  - `FRONTEND_APP_URL`: Public HTTPS Studio URL.
  - `TRUST_PROXY_HEADERS=true` **only** behind a trusted CDN/reverse proxy overwriting `X-Forwarded-For`.
- [ ] **External Provider Credentials:**
  - GCP: `GCP_PROJECT_ID`, `GCS_BUCKET` (`gs://...`), `VERTEX_LOCATION`, `GOOGLE_APPLICATION_CREDENTIALS` (or Workload Identity / ADC).
  - Stripe Live: `STRIPE_SECRET_KEY=sk_live_...`, `STRIPE_WEBHOOK_SECRET=whsec_...`, `STRIPE_PRICE_STARTER_10`, `STRIPE_PRICE_GROWTH_50`, `STRIPE_PRICE_SCALE_200`.
  - Email / OAuth: Valid `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM_EMAIL` and optionally `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.

---

## 2. Database Migration & Multi-Tenant RLS Rollout

1. [ ] Capture a pre-deployment PostgreSQL snapshot / verify continuous PITR WAL archiving is healthy.
2. [ ] Apply SQL migrations cleanly in numeric order (`ON_ERROR_STOP=1`):
   - `001_initial_schema.sql` (if fresh DB; or ensure baseline applied)
   - `002_saas_multi_tenant_auth_billing.sql`
   - `003_google_oauth_identity.sql`
   - `004_job_leases_and_immutability.sql`
   - `005_transactional_outbox_and_rls_hardening.sql`
3. [ ] Verify database invariants via SQL:
   ```sql
   SELECT version, applied_at FROM schema_migrations ORDER BY applied_at;

   SELECT relname, relrowsecurity, relforcerowsecurity
   FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND relkind = 'r';

   SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname IN ('authenticated', 'anon', 'app_user');
   ```
   - Confirm `005_transactional_outbox_and_rls_hardening` is applied.
   - Confirm `relrowsecurity = true` AND `relforcerowsecurity = true` across all 10 tables (`schema_migrations`, `users`, `auth_sessions`, `stripe_events`, `workspaces`, `workspace_members`, `workspace_assets`, `video_jobs`, `credit_ledger`, `job_dispatch_outbox`).
   - Confirm application/PostgREST query role has **`rolbypassrls = false` (`NOBYPASSRLS`)**.
   - Confirm `trg_credit_ledger_no_delete` trigger is active on `credit_ledger`.

---

## 3. Infrastructure & Service Topology

1. [ ] **Next.js Studio (`apps/studio`):** Node.js 22 (`next build` + `next start`), `WORKER_API_URL` and `WORKER_API_KEY` injected server-side ONLY (never `NEXT_PUBLIC_*`).
2. [ ] **FastAPI API (`services/worker`):** Install with `pip install -e ".[prod]"`; run behind TLS proxy (`uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`).
3. [ ] **Celery Worker Pool (`services/worker`):** Container image includes `ffmpeg`, `ffprobe`, `libass`/`harfbuzz`/`fribidi`, and Noto Nastaliq Urdu / Noto Sans Arabic / Noto Sans Devanagari fonts:
   ```bash
   celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2 --prefetch-multiplier=1 -O fair --max-tasks-per-child=50
   ```
4. [ ] **Periodic Recovery & Outbox Reconciliation Cron/Beat (Every 60s):**
   ```bash
   python -c "from app.tasks import recover_interrupted_jobs; print(recover_interrupted_jobs(min_age_seconds=120))"
   ```
   - Recovers genuinely expired active-worker leases (`ACTIVE_EXECUTION_STATUSES`) using DB clock `clock_timestamp()` + `FOR UPDATE SKIP LOCKED` + atomic CAS without touching legitimate queued jobs.
   - Relays any pending/stale `job_dispatch_outbox` events safely.
5. [ ] **Private Storage:** Shared persistent encrypted volume for `STORAGE_ROOT` (API + Worker) or GCS private delivery; confirm no unauthenticated static mount exists.

---

## 4. Mandatory Staging Pre-Cutover Verification Gates

**Do NOT route live paying customers until every CI and staging check below is green:**

- [ ] **GitHub Actions CI Green (`postgres-redis-integration` + `worker-verify` + `studio-and-remotion-verify`):**
  - Confirm `postgres:16-alpine` executes `tests/test_postgres_integration.py` (migrations `001`–`005`, `NOBYPASSRLS` Tenant A/B isolation, 12-thread reservation contention, `clock_timestamp()` heartbeat-vs-recovery races).
  - Confirm `redis:7-alpine` executes `tests/test_redis_celery_recovery.py` (shared Lua rate limits, queued congestion preservation, duplicate task protection, worker `SIGKILL` lease recovery, outbox relay recovery).
  - Confirm Node 24 SHA-pinned workflow actions run cleanly with `0` Node 20 deprecation warnings.
- [ ] **Staging Live Stripe Check:** Run `STRIPE_STAGING_TEST=1 pytest -v tests/test_staging_integrations.py -k stripe` + verify `stripe listen` webhook delivery credits balance once and `charge.refunded` reverses cleanly (`GET /v1/workspaces/{id}/credits/reconcile` -> `is_balanced: true`).
- [ ] **Staging Live GCP Veo 3.1 + Cloud TTS Check:** Run `GCP_STAGING_TEST=1 pytest -v tests/test_staging_integrations.py -k gcp` confirming real MP4 generation from Vertex AI, Cloud TTS WAV synthesis, GCS download, and FFmpeg compositing (`ur` RTL + `en` LTR).
- [ ] **Staging Multi-Tier Benchmark (`10,25,50,100`):** Run `python scripts/run_staging_benchmarks.py --tiers 10,25,50,100 --database-url ... --redis-url ...` confirming `0` errors and `credit_reconciliation_balanced: true`.
- [ ] **Live SMTP + Google OAuth Smoke Check:** Register an external email, confirm verification email arrives out-of-band, and test real Google OAuth consent callback.

---

## 5. Observability & Rollback Procedure

- **Liveness / Readiness:** Monitor `GET /health` (`database_connected=true`, `redis_broker=true`, `celery_eager_mode=false`, `ffmpeg_available=true`).
- **Telemetry:** Monitor `GET /v1/ops/metrics` (`X-Admin-Secret`) for `jobs.expired_leases`, `outbox.failed`, `rate_limiter_backend="redis"`, `db_clock`, and `stage.*` latencies.
- **Zero-Data-Loss Rollback:**
  1. Migrations `002`–`005` are strictly additive (`ADD COLUMN IF NOT EXISTS` / new table `job_dispatch_outbox`). Roll back API/Worker/Studio containers to prior known-good image tags without schema destruction.
  2. Run `recover_interrupted_jobs(min_age_seconds=120)` after roll-back stabilizes so orphaned leases refund cleanly once.
  3. Only restore PostgreSQL PITR / snapshot if data corruption occurred, and re-verify `credit_ledger` reconciliation before reopening traffic.
