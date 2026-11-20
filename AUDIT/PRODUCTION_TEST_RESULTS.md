# Production Test & Verification Results

**Branch:** `production-final-hardening`  
**Execution Date:** `2026-11-20`  
**Rule of Record:** Only commands actually executed after final code edits on `production-final-hardening` are reported below as passed. Every external integration that lacked local runtime infrastructure or staging credentials is explicitly listed as **`NOT VERIFIED`**.

---

## 1. Summary Matrix

| Suite / Check | Status | Scope Executed & Exact Counts |
|---|---|---|
| `ruff check .` (`services/worker`) | **PASS** | `All checks passed!` (`0` warnings/errors) |
| `uvx --python 3.12 mypy app --ignore-missing-imports` | **PASS** | `Success: no issues found in 14 source files` |
| `pytest -v` (`services/worker`) | **PASS (4 skipped)** | **`43 passed, 4 skipped, 1 warning in 78.50s`** (`0` failed) |
| Third-party `pip-audit` (frozen reqs) | **PASS** | `No known vulnerabilities found` (`45` third-party packages audited) |
| `npm run verify:remotion` | **PASS** | Exit `0` (`tsc --noEmit` + `eslint --max-warnings 0`) |
| `npm run verify:studio` | **PASS** | Exit `0` (`tsc --noEmit`, `eslint --max-warnings 0`, **`10/10` tests pass**, `next build` v16.4.6 Turbopack clean) |
| `npm audit --omit=dev --audit-level=high` | **PASS** | `found 0 vulnerabilities` (Exit `0`) |
| `run_staging_benchmarks.py --local-dry-run --tiers 10,25` | **PASS (DRY-RUN)** | SQLite/in-process ONLY: Tier 10 (`0` err, `15.45 ops/s`), Tier 25 (`0` err, `17.87 ops/s`), `credit_reconciliation_balanced: true`, Peak `2.325 MiB` |
| Customer Journey Browser E2E (`127.0.0.1:3000`) | **PASS** | Host-verified origin `http://127.0.0.1:3000`, `0` console/page/500 errors, full customer flow verified |
| Live PostgreSQL 16 + `NOBYPASSRLS` (`test_postgres_integration.py`) | **`NOT VERIFIED`** | Module skipped (`TEST_POSTGRES_URL` unset locally; no local Docker/`psql`; Supabase MCP DB auth `28P01`) |
| Live Redis 7 + Celery Subprocesses (`test_redis_celery_recovery.py`) | **`NOT VERIFIED`** | Module skipped (`TEST_REDIS_URL` unset locally; no local `redis-server`) |
| Live Stripe Test-Mode API (`STRIPE_STAGING_TEST=1`) | **`NOT VERIFIED`** | Test skipped (`STRIPE_STAGING_TEST!=1`; no staging Stripe test keys) |
| Live GCP Vertex Veo / Cloud TTS / GCS (`GCP_STAGING_TEST=1`) | **`NOT VERIFIED`** | Test skipped (`GCP_STAGING_TEST!=1`; `gcloud auth list` has no active credentials) |
| Multi-Tier Staging Postgres+Redis Benchmarks | **`NOT VERIFIED`** | Not executed without live staging PostgreSQL + Redis infrastructure |

---

## 2. Exact Executed Local Commands & Verbatim Outcomes

### 2.1 Worker Lint, Static Types & Supply-Chain CVE Scan (`services/worker`)
1. **Ruff Lint:**
   ```powershell
   ruff check .
   ```
   Output: `All checks passed!` (`exit 0`)

2. **mypy Static Type Check:**
   ```powershell
   uvx --python 3.12 mypy app --ignore-missing-imports
   ```
   Output: `Success: no issues found in 14 source files` (`exit 0`)

3. **Python Third-Party CVE Audit:**
   ```powershell
   uv pip freeze --python "C:\Users\Admin\AppData\Roaming\uv\tools\pytest\Scripts\python.exe" --exclude-editable |
     Select-String -NotMatch -Pattern "^(localized[-_]video[-_]ad[-_]worker([= <>~!@]|$)|.*@ file://)" |
     Set-Content -Path $reqFile -Encoding utf8
   uvx --python 3.12 pip-audit --no-deps --disable-pip --strict --desc -r $reqFile
   ```
   Output (`45` frozen packages including `fastapi==0.162.7`, `celery==5.7.0`, `sqlalchemy==2.1.8`, `starlette==1.10.0`, `pydantic==2.14.3`, `httpx==0.28.1`, `uvicorn==0.54.0`, `beautifulsoup4==4.15.0`, `imageio-ffmpeg==0.8.1`):
   `No known vulnerabilities found` (`exit 0`)

---

### 2.2 Full Worker Pytest Suite (`services/worker`)
```powershell
C:\Users\Admin\AppData\Roaming\uv\tools\pytest\Scripts\python.exe -m pytest -v
```
Result: **`43 passed, 4 skipped, 1 warning in 78.50s (0:01:18)`** (`exit 0`).  
*(Single warning is upstream third-party `StarletteDeprecationWarning` inside `fastapi/testclient.py`.)*

Breakdown of executed & skipped tests:
- `tests/test_hardening_phases.py` — **7 passed** (broker fail-closed `503` + refund, retries with jittered backoff, lease/heartbeat/fencing barriers, multi-instance Redis Lua counter semantics, connection-pinned SSRF blocking, out-of-order refund reconciliation + immutability triggers, locked-JWT/logout-all/member-delete RBAC, 10-thread concurrency stress, failure boundary modes).
- `tests/test_queued_and_lease_races.py` — **4 passed**:
  - `test_queued_job_waiting_beyond_recovery_threshold_is_never_failed` (**PASSED**)
  - `test_queued_congestion_and_abandoned_active_job_recovery_isolation` (**PASSED**)
  - `test_transactional_outbox_retry_recovery_and_cancel` (**PASSED**)
  - `test_heartbeat_vs_recovery_concurrency_and_fencing_invariants` (**PASSED** — barrier-synchronized heartbeat vs recovery, dual recovery, competing workers, stale completion rejection)
- `tests/test_security_billing_ai.py` — **18 passed** (auth/refresh/lockout, 2-tenant isolation, RBAC, concurrent credit reservation overdraft prevention, Stripe HMAC/idempotency/cumulative partial refunds, production startup validation, Veo/TTS/GCS error boundaries, SSRF targets, SQLite v1 non-destructive upgrade, `WORKER_API_KEY` + XFF spoof protection, rate-limiter eviction, Google OAuth PKCE `S256` & disposable email blocking).
- `tests/test_worker.py` — **11 passed** (`/health`, 4 languages `ur`/`ar`/`hi`/`en` + private MP4 download + FFmpeg validation, `402` zero balance guard, pipeline failure refund atomicity, `Idempotency-Key` deduplication, honest scraper, `422` invalid language, custom props + real composited MP4).
- `tests/test_staging_integrations.py` — **3 passed, 2 skipped**:
  - `test_stripe_webhook_tamper_replay_duplicate_and_refund_reconciliation` (**PASSED**)
  - `test_stripe_checkout_and_gcp_clients_fail_closed_without_credentials` (**PASSED**)
  - `test_retryable_vs_permanent_provider_exception_classification` (**PASSED**)
  - `test_live_stripe_staging_checkout_session_creation` (**SKIPPED**: `STRIPE_STAGING_TEST!=1`)
  - `test_live_gcp_staging_tts_and_veo_generation` (**SKIPPED**: `GCP_STAGING_TEST!=1`)
- `tests/test_postgres_integration.py` — **SKIPPED** at module level (`TEST_POSTGRES_URL not set; skipping live PostgreSQL integration suite.`).
- `tests/test_redis_celery_recovery.py` — **SKIPPED** at module level (`TEST_REDIS_URL not set; skipping live Redis & Celery worker integration suite.`).

---

### 2.3 Monorepo TypeScript, Remotion, Next.js Studio Build & NPM Audit
1. **Remotion Verification (`npm run verify:remotion`):**
   - `@video-ad/remotion` `tsc --noEmit` + `eslint "src/**/*.{ts,tsx}" --max-warnings 0` -> **`exit 0`**.
2. **Next.js Studio Verification (`npm run verify:studio`):**
   - `tsc --noEmit` (`0` TS errors) + `eslint "src/**/*.{ts,tsx}" --max-warnings 0` (`0` warnings).
   - Node TAP Test Runner (`studio.test.ts`): **`10/10` tests passed (`fail 0`, `skipped 0`)**, including test #10 verifying `forwardWorkerJsonResponse` echoes `x-request-id` to browser responses.
   - `next build` (`Next.js 16.4.6` Turbopack): Compiled cleanly across all 19 routes (`/`, `/_not-found`, 17 `/api/v1/*` BFF endpoints) -> **`exit 0`**.
3. **Production NPM Dependency Audit (`npm audit --omit=dev --audit-level=high`):**
   - Output: `found 0 vulnerabilities` (`exit 0`).

---

### 2.4 Local Dry-Run Benchmark (`run_staging_benchmarks.py`)
> **IMPORTANT:** Executed strictly as a **LOCAL SQLITE / IN-PROCESS DRY-RUN**. Do **NOT** interpret SQLite numbers as staging PostgreSQL / Redis / Celery multi-worker capacity.

```powershell
C:\Users\Admin\AppData\Roaming\uv\tools\pytest\Scripts\python.exe scripts/run_staging_benchmarks.py --local-dry-run --tiers 10,25
```

| Tier (`concurrency`) | Completed Ops | Errors | Wall Time | Throughput | p50 (ms) | p95 (ms) | p99 (ms) | Credit Reconciliation |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `10` threads | `10` | `0` | `0.6473s` | `15.45 ops/s` | `347.397` | `579.217` | `621.784` | `true` (`100%`) |
| `25` threads | `25` | `0` | `1.399s` | `17.87 ops/s` | `756.756` | `1249.922` | `1348.386` | `true` (`100%`) |

- Peak traced Python heap: **`2.325 MiB`** (`BENCH_EXIT=0`).

---

### 2.5 Customer Journey Browser E2E (`http://127.0.0.1:3000`, Production Studio Build)
Executed cleanly against isolated temporary FastAPI (`:8000`, `MOCK_VERTEX_VEO=true`, `MOCK_TTS=true`, `CELERY_ALWAYS_EAGER=true`, `REQUIRE_EMAIL_VERIFICATION=true`, `EXPOSE_DEV_AUTH_TOKENS=true`) and production-built Next.js Studio (`:3000`, `NODE_ENV=production`) with host-verified origin (`BROWSER_HOST_FACTS`: `visited_origins: http://127.0.0.1:3000`, `blocked_origins: none`), visual screenshot inspection (`final_step_28.png` — creamy-white `#FAF7F2` / botanical green `#15803D` UI cleanly rendered), and teardown completed afterward:
- **Runtime Errors:** **`0` console errors**, **`0` page errors**, **`0` HTTP >= 500 responses**.
- **Auth & Verification:** Google OAuth buttons visible; registered `zainab.finalqa@luminabotanics.com` (`POST /api/v1/auth/register` -> `201`, `x-request-id` echoed), verified email with dev token (`POST /api/v1/auth/verify-email` -> `200`), authenticated with `3 Credits`.
- **Workspace Management:** Created second workspace `Lumina Branch Studio` via `+ New` (`POST /api/v1/workspaces` -> `201`, `0` credits), switched back to primary workspace (`3` credits).
- **Render, Playback, Download & Correlation:** Submitted `https://luminabotanics.com/products/botanical-elixir` -> `POST /api/v1/videos/generate` returned `202` (`x-request-id: b405b8dd-76ed-49b7-afb1-58c194c619a0`); job reached `COMPLETED`; Remotion Player advanced frames (`46/60 -> 51/60`); `GET /api/v1/renders/f04784c8-8beb-4cbd-a8f9-81286d229a0b` returned **`HTTP 200`**, `video/mp4`, **`77,298` bytes**, and echoed **`x-request-id: ceaae046-4976-4feb-b7fd-a66d9ae38b46`**.
- **SSRF Error Handling & Credit Preservation:** Submitted `http://127.0.0.1/internal` -> `POST /api/v1/products/scrape` returned `HTTP 400` with safe error banner (`"Couldn't import that URL · Blocked private or non-routable IP address: 127.0.0.1"`), preserving balance at **`2` Credits**. *(Minor observability note: `x-request-id` header was absent on this specific BFF `400` catch response in `scrape/route.ts`.)*
- **Billing & Sign Out:** Opened Credits & Billing modal showing `2 Credits` and 3 balanced ledger entries (`initial_promo +3`, `reservation -1`, `deduction 0`); signed out (`POST /api/v1/auth/logout` -> `200`), returned to Sign In modal, and verified `fetch('/api/v1/auth/me')` returned **`HTTP 401`** (`x-request-id` echoed).

---

## 3. `NOT VERIFIED` External Staging Integrations (Must Execute Before Live Launch)

| Verification Item | Reason `NOT VERIFIED` Locally | Command / Gate to Execute Before Production Cutover |
|---|---|---|
| **Live PostgreSQL 16 + `NOBYPASSRLS` + `clock_timestamp()`** (`tests/test_postgres_integration.py`) | Local workstation lacks Docker/`psql`; managed Supabase MCP database queries returned `FATAL: 28P01: password authentication failed`. | Runs automatically in GitHub Actions `postgres-redis-integration` (`postgres:16-alpine`), or run against staging DB with `TEST_POSTGRES_URL=... pytest -v tests/test_postgres_integration.py`. |
| **Live Redis 7 Lua + Celery Subprocess Crash/Recovery** (`tests/test_redis_celery_recovery.py`) | Local workstation lacks `redis-server`; multi-process Celery worker `SIGKILL` & redelivery require live Redis. | Runs automatically in GitHub Actions `postgres-redis-integration` (`redis:7-alpine`), or run with `TEST_REDIS_URL=... pytest -v tests/test_redis_celery_recovery.py`. |
| **Live Stripe Test-Mode Checkout & Webhooks** (`STRIPE_STAGING_TEST=1`) | No staging Stripe `sk_test_*` / `price_*` credentials provisioned locally. | Run `STRIPE_STAGING_TEST=1 STRIPE_SECRET_KEY=sk_test_... STRIPE_PRICE_STARTER_10=price_... pytest -v tests/test_staging_integrations.py -k stripe` + `stripe listen` webhook delivery check. |
| **Live GCP Vertex Veo 3.1, Cloud TTS & GCS Delivery** (`GCP_STAGING_TEST=1`) | `gcloud auth list` shows `No credentialed accounts.`; live API calls unavailable. | Run `GCP_STAGING_TEST=1 GCP_PROJECT_ID=... GCS_BUCKET=gs://... GOOGLE_APPLICATION_CREDENTIALS=... pytest -v tests/test_staging_integrations.py -k gcp`. |
| **Multi-Tier Staging Concurrency Benchmarks (`10,25,50,100`)** | Live staging PostgreSQL + Redis cluster required for meaningful multi-replica numbers. | Run `python scripts/run_staging_benchmarks.py --tiers 10,25,50,100 --database-url ... --redis-url ... --output-json staging_bench.json`. |
