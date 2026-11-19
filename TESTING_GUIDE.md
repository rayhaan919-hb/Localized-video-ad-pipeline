# Testing, Benchmarking & Staging Verification Guide

This guide lists the exact commands used to verify **Localized AI Video Ad Pipeline** across backend worker logic, database migrations, frontend BFF/UI, security scans, concurrent load benchmarks, and external staging dependencies.

---

## 1. Python Worker Lint & Automated Test Suite (`services/worker`)

Run linting and all 36 automated tests:

```bash
cd services/worker
ruff check .
pytest -v
```

*(On Windows with standalone `uv` pytest toolchain: `C:\Users\Admin\AppData\Roaming\uv\tools\pytest\Scripts\python.exe -m pytest -v`.)*

### Test Suite Coverage (`36` collected items)
1. [test_hardening_phases.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/tests/test_hardening_phases.py) (**7 tests**):
   - Phase 2: Fail-closed `validate_production_config()`, forbid silent `memory://` / eager fallback in production, `503` + clean credit refund when Redis is down, transient vs permanent classification, jittered exponential backoff (`compute_retry_countdown`), retry -> success without duplicate charges.
   - Phase 3: Worker leases (`acquire_job_lease`, `renew_job_lease`), `_LeaseHeartbeatThread`, fencing token enforcement (`StaleWorkerLeaseError`), long-running active lease preservation under `recover_interrupted_jobs()`, expired lease reclamation + single idempotent refund, duplicate delivery prevention.
   - Phase 4: Distributed multi-instance rate limiting (`DistributedRateLimiter` + shared store semantics across independent instances), burst protection, and `429` + `Retry-After` across endpoints.
   - Phase 5: Connection-pinned SSRF protection (`SSRFSafeNetworkBackend`), private/loopback/CGNAT/link-local/metadata/IPv6-mapped/obfuscated-IP blocking, DNS rebinding simulation, redirect chain revalidation, stream byte caps (`Accept-Encoding: identity`), and Content-Type validation.
   - Phases 6–11: Out-of-order `charge.refunded` -> `checkout.session.completed` reconciliation, ORM/SQL `credit_ledger` immutability, `reconcile_workspace_credits`, PostgreSQL engine pool config, locked-account JWT rejection (`403`), `POST /v1/auth/logout-all`, `DELETE /v1/workspaces/{id}/members/{uid}` hierarchy RBAC, `X-Request-ID` -> `VideoJob.correlation_id`, `/health`, `/v1/ops/metrics`.
   - Concurrency Stress: 10-thread parallel generation + lease/credit invariant check (`credit_balance == 0`, `reserved_balance == 0`, `is_balanced == True`).
   - Phase 10 Failure Modes: Live Veo configuration errors, expired credential `401` handling, and gated `STAGING_LIVE_TESTS=1` probe.
2. [test_security_billing_ai.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/tests/test_security_billing_ai.py) (**18 items**): Multi-tenant auth, refresh reuse revocation, lockout, cross-workspace isolation, RBAC, concurrent credit reservation races, Stripe HMAC webhook signatures/idempotency/partial refunds, fail-closed startup checks, live GCS/Veo/TTS error boundaries, SSRF targets, legacy SQLite non-destructive upgrade, Google OAuth PKCE S256, and disposable email blocking.
3. [test_worker.py](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/services/worker/tests/test_worker.py) (**11 items**): `/health`, all 4 languages (`ur`, `ar`, `hi`, `en`) + RTL typography, `402` insufficient credits, failure refund atomicity, idempotency key deduplication, honest scraping without fabricated prices, and real FFmpeg composited MP4 + custom props verification.

---

## 2. Database Migration Smoke Verification

Verify schema creation and idempotent migrations (`001` through `004`) against an isolated SQLite database:

```bash
cd services/worker
APP_ENV=test DATABASE_URL="sqlite:///./migration_smoke.db" python -c "from app.db import init_db, SessionLocal; from app.migrations import get_applied_migrations; init_db(); s=SessionLocal(); print(get_applied_migrations(s)); s.close()"
rm -f migration_smoke.db
```

Expected applied versions: `001_initial_schema`, `002_saas_multi_tenant_auth_billing`, `003_google_oauth_identity`, `004_job_leases_and_immutability`.

---

## 3. Remotion & Next.js Studio Verification (`packages/remotion`, `apps/studio`)

Run from repository root:

```bash
npm run verify:remotion
npm run verify:studio
```

`verify:studio` runs `tsc --noEmit`, `eslint "src/**/*.{ts,tsx}" --max-warnings 0`, [studio.test.ts](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/apps/studio/src/__tests__/studio.test.ts) (`9/9` Node unit/BFF security tests), and a full Next.js `16.4.6` production build.

---

## 4. Supply-Chain & Security Scans

```bash
# Production NPM dependency audit (high/critical gate)
npm audit --omit=dev --audit-level=high

# Python CVE audit (requires dev extras installed, enforced in CI)
cd services/worker
pip-audit --strict --desc
```

CI ([.github/workflows/ci.yml](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/.github/workflows/ci.yml)) additionally runs secret pattern scanning across `apps/`, `packages/`, `services/`, and `schema.sql`.

---

## 5. Performance & Concurrency Benchmark Suite (`services/worker/scripts/run_benchmarks.py`)

Execute reproducible multi-threaded benchmarks with `tracemalloc` memory tracking and automatic post-load credit ledger reconciliation:

```bash
cd services/worker
python scripts/run_benchmarks.py
```

Latest verified baseline (Windows host, `0.0%` errors across all 4 scenarios, `is_balanced: true`, peak traced heap `6.07 MB`):
- `concurrent_register_20` (8 threads, PBKDF2 260k): `20` reqs, `0` errors, `5.78 rps`, `p50=1072.23ms`, `p95=1801.9ms`
- `concurrent_credit_reservations_30` (12 threads): `30` reqs, `0` errors, `34.0 rps`, `p50=76.39ms`, `p95=717.82ms`
- `concurrent_e2e_video_render_6` (4 threads, mock Veo + WAV TTS + real FFmpeg): `6` reqs, `0` errors, `p50=44174.6ms`, `p95=44349.67ms`
- `concurrent_signed_downloads_20` (8 threads): `20` reqs, `0` errors, `11.53 rps`, `p50=553.79ms`, `p95=1092.33ms`

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
