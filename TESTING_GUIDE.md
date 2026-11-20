# Testing, Benchmarking & Staging Verification Guide

This guide lists the exact commands used to verify **Localized AI Video Ad Pipeline** across backend worker logic, database migrations, frontend BFF/UI, security scans, concurrent load benchmarks, and external staging dependencies.

---

## 1. Python Worker Lint, Typecheck & Automated Test Suite (`services/worker`)

Run linting, static type checks, and automated suites:

```bash
cd services/worker
ruff check .
mypy app --ignore-missing-imports
pytest -v
```

*(On Windows with standalone `uv` pytest toolchain: `C:\Users\Admin\AppData\Roaming\uv\tools\pytest\Scripts\python.exe -m pytest -v`.)*

### Test Suite Coverage (`43` local passing tests + `6` env-gated external integration tests)
1. [`test_hardening_phases.py`](./services/worker/tests/test_hardening_phases.py) (**7 tests**): Fail-closed broker checks, lease heartbeat & fencing barriers, distributed Redis Lua counter semantics, connection-pinned SSRF blocking, out-of-order Stripe refund reconciliation, locked-JWT/logout-all/member-delete RBAC, 10-thread concurrency stress, and transient/config boundaries.
2. [`test_queued_and_lease_races.py`](./services/worker/tests/test_queued_and_lease_races.py) (**4 tests**): Queued job preservation beyond recovery thresholds, heavy queue congestion survival, transactional dispatch outbox retry/reconciliation/cancel guards, and barrier-synchronized DB-clock heartbeat-vs-recovery & dual-recovery race tests.
3. [`test_staging_integrations.py`](./services/worker/tests/test_staging_integrations.py) (**3 local contract tests + 2 env-gated staging tests**): Stripe webhook HMAC tamper/replay/idempotency/refund contracts, fail-closed missing-credential checks for Stripe/Veo/TTS, retryable vs permanent error classification, plus `STRIPE_STAGING_TEST=1` & `GCP_STAGING_TEST=1` live smoke checks.
4. [`test_postgres_integration.py`](./services/worker/tests/test_postgres_integration.py) (**env-gated `TEST_POSTGRES_URL`, 5 tests**): Live PostgreSQL 16 migrations `001`–`005`, `FORCE ROW LEVEL SECURITY` catalog checks, trigger/FK delete blocks, 12-thread concurrent reservation contention, `clock_timestamp()` + `FOR UPDATE SKIP LOCKED` lease races, and temporary `NOBYPASSRLS` role audit + Tenant A/B/anon RLS verification.
5. [`test_redis_celery_recovery.py`](./services/worker/tests/test_redis_celery_recovery.py) (**env-gated `TEST_REDIS_URL`, 3 tests**): Live Redis Lua distributed rate limiting across instances, real Celery worker subprocess queued congestion + duplicate delivery protection, and `SIGKILL` worker lease expiry + outbox relay recovery.
6. [`test_security_billing_ai.py`](./services/worker/tests/test_security_billing_ai.py) (**18 items**): Multi-tenant auth, refresh reuse revocation, lockout, cross-workspace isolation, RBAC, concurrent credit reservation races, Stripe HMAC webhook signatures/idempotency/partial refunds, fail-closed startup checks, live GCS/Veo/TTS error boundaries, SSRF targets, legacy SQLite non-destructive upgrade, Google OAuth PKCE S256, and disposable email blocking.
7. [`test_worker.py`](./services/worker/tests/test_worker.py) (**11 items**): `/health`, all 4 languages (`ur`, `ar`, `hi`, `en`) + RTL typography, `402` insufficient credits, failure refund atomicity, idempotency key deduplication, honest scraping without fabricated prices, and real FFmpeg composited MP4 + custom props verification.

---

## 2. Database Migration Smoke Verification

Verify schema creation and idempotent migrations (`001` through `005`) against an isolated SQLite database:

```bash
cd services/worker
APP_ENV=test DATABASE_URL="sqlite:///./migration_smoke.db" python -c "from app.db import init_db, SessionLocal; from app.migrations import get_applied_migrations; init_db(); s=SessionLocal(); print(get_applied_migrations(s)); s.close()"
rm -f migration_smoke.db
```

Expected applied versions: `002_saas_multi_tenant_auth_billing`, `003_google_oauth_identity`, `004_job_leases_and_immutability`, `005_transactional_outbox_and_rls_hardening`.

---

## 3. Remotion & Next.js Studio Verification (`packages/remotion`, `apps/studio`)

Run from repository root:

```bash
npm run verify:remotion
npm run verify:studio
```

`verify:studio` runs `tsc --noEmit`, `eslint "src/**/*.{ts,tsx}" --max-warnings 0`, [`studio.test.ts`](./apps/studio/src/__tests__/studio.test.ts) (`10/10` Node unit/BFF security & `X-Request-ID` tests), and a full Next.js `16.4.6` production build.

---

## 4. Supply-Chain & Security Scans

```bash
# Production NPM dependency audit (high/critical gate)
npm audit --omit=dev --audit-level=high

# Python CVE audit (excludes local editable package; enforces third-party CVEs)
cd services/worker
python -m pip freeze --exclude-editable | grep -ivE '^(localized[-_]video[-_]ad[-_]worker([= <>~!@]|$)|.*@ file://)' > /tmp/pip-audit-reqs.txt
test -s /tmp/pip-audit-reqs.txt
pip-audit --no-deps --disable-pip --strict --desc -r /tmp/pip-audit-reqs.txt
rm -f /tmp/pip-audit-reqs.txt
```

CI ([`.github/workflows/ci.yml`](./.github/workflows/ci.yml)) runs SHA-pinned Node 24 actions, `mypy`, live PostgreSQL 16 + Redis 7 service integration tests, and secret pattern scanning across `apps/`, `packages/`, `services/`, and `schema.sql`.

---

## 5. Concurrency & Staging Benchmarks (`run_benchmarks.py` / `run_staging_benchmarks.py`)

Execute reproducible multi-threaded benchmarks with `tracemalloc` memory tracking and automatic post-load credit ledger reconciliation:

```bash
cd services/worker
# Legacy single-host SQLite + FFmpeg benchmark
python scripts/run_benchmarks.py

# Multi-tier staging benchmark (requires PostgreSQL + Redis in staging, or --local-dry-run for SQLite)
python scripts/run_staging_benchmarks.py --local-dry-run --tiers 10,25
```

---

## 6. External Staging Integration Tests (Requires Buyer Cloud Credentials)

Run these against a provisioned staging environment before production DNS cutover:

1. **Staging Health Probe:**
   ```bash
   STAGING_LIVE_TESTS=1 STAGING_WORKER_URL="https://staging-api.example.com" pytest tests/test_hardening_phases.py -k test_phase10 -v
   ```
2. **PostgreSQL 15+ Multi-Role RLS Verification:** Connect as a non-superuser role (`SET ROLE authenticated;`), set `request.jwt.claim.sub` via `set_config`, and verify queries against another tenant's `workspaces`, `video_jobs`, `credit_ledger`, and `workspace_assets` return `0` rows while `DELETE FROM credit_ledger` triggers `trg_credit_ledger_no_delete`.
3. **Live Redis + Multi-Process Celery `SIGKILL` Crash Recovery:** Start API + 2 Celery worker processes connected to staging Redis, enqueue a render job, send `kill -9` to the worker holding `worker_id`, confirm heartbeat renewal ceases, run `recover_interrupted_jobs()`, and verify a single credit refund with `credit_ledger` balanced.
4. **Live Provider & Payment Flows:** Verify real Stripe test-mode Checkout + webhook signature delivery (`stripe listen`), Vertex AI Veo 3.1 + Cloud TTS + GCS signed fetch, Google OAuth 2.0 callback exchange, and SMTP email verification delivery.
