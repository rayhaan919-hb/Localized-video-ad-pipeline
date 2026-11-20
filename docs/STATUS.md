# Project Status (`STATUS.md`)

**Project:** Localized AI Video Ad Pipeline (Non-English D2C SaaS)  
**Current Phase:** Enterprise Production Hardening Complete (Phases 1–15) — Ready for Staging Validation  
**Last Updated:** 2026-11-20  
**Latest Verified Code State:** Enterprise Hardening Pass on `main` (uncommitted working tree above `dcf344d`)  

---

## Done (Verified)
- **Enterprise Production Hardening Pass Complete (Phases 1–15):**
  - **Audit Revalidation (Phase 1):** Verified live codebase and produced [AUDIT/PRODUCTION_HARDENING_AUDIT.md](../AUDIT/PRODUCTION_HARDENING_AUDIT.md) classifying `3` P0, `4` P1, and `3` P2 gaps alongside existing strengths.
  - **Background Job Reliability & Safe Recovery (Phases 2–3):** Removed silent production fallbacks to `memory://` and `CELERY_ALWAYS_EAGER=true`; added fail-closed `validate_production_config()` and `dispatch_video_job()` (`HTTP 503` + credit refund when Redis is down), Celery timeouts (`300s`/`360s`), `acks_late=True`, `TransientJobError` vs `PermanentJobError` classification with jittered exponential backoff, exclusive worker leases (`worker_id`, `lease_expires_at`, `heartbeat_at`, monotonic `fencing_token`), `_LeaseHeartbeatThread`, `StaleWorkerLeaseError` write barriers, and lease-aware `recover_interrupted_jobs()`. Fixed a parallel `ensure_sample_fixture()` write race in `veo.py` discovered during load testing (`_FIXTURE_LOCK` + atomic `os.replace()`).
  - **Distributed Rate Limiting & Connection-Pinned SSRF Defense (Phases 4–5):** Implemented Redis atomic Lua sliding-window `DistributedRateLimiter` (burst protection + 8 per-category limits + `429`/`Retry-After`), `SSRFSafeNetworkBackend` (`httpcore.SyncBackend`) pinning validated global IPs at TCP socket connection time to eliminate DNS rebinding TOCTOU, blocking CGNAT/loopback/private/metadata/IPv6-mapped/obfuscated IPs, internal ports, unsafe redirects, compressed bombs (`Accept-Encoding: identity`), and exceeding `12s` wall-clock or Content-Type limits.
  - **Billing, DB RLS, Auth/RBAC, CI & Observability (Phases 6–11):** Added out-of-order Stripe refund-then-purchase reconciliation, `ON DELETE RESTRICT`, ORM + SQL `trg_credit_ledger_no_delete` triggers, `GET /v1/workspaces/{id}/credits/reconcile`, PostgreSQL connection pool tuning, `FORCE ROW LEVEL SECURITY` in `schema.sql` & migration `004_job_leases_and_immutability.sql`, locked-account JWT rejection (`403`), `POST /v1/auth/logout-all` (+ BFF route support), `DELETE /v1/workspaces/{id}/members/{uid}` hierarchy guards, `X-Request-ID` -> `VideoJob.correlation_id`, enriched `/health`, `GET /v1/ops/metrics`, and hardened `.github/workflows/ci.yml` (`permissions: contents: read`, `pip-audit`, `npm audit --omit=dev --audit-level=high`, migration smoke check, secret scan).
  - **Full Enterprise Documentation Suite (Phase 15):** Created [PRODUCTION_READINESS.md](../PRODUCTION_READINESS.md), [DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md), [ENVIRONMENT_VARIABLES.md](../ENVIRONMENT_VARIABLES.md), [DATABASE_MIGRATIONS.md](../DATABASE_MIGRATIONS.md), [BACKGROUND_JOBS.md](../BACKGROUND_JOBS.md), [INCIDENT_RESPONSE.md](../INCIDENT_RESPONSE.md), [BACKUP_AND_RECOVERY.md](../BACKUP_AND_RECOVERY.md), [MONITORING.md](../MONITORING.md), [TESTING_GUIDE.md](../TESTING_GUIDE.md), [AUDIT/FINAL_PRODUCTION_READINESS_REPORT.md](../AUDIT/FINAL_PRODUCTION_READINESS_REPORT.md), and updated [SECURITY.md](../SECURITY.md) & [CHANGELOG.md](../CHANGELOG.md).
- **Verified Automated Test & Benchmark Runs (Post-Final-Edit):**
  - `services/worker`: `ruff check .` -> `All checks passed!`; `pytest -v` -> **`36 passed, 1 warning`** (`0` failed, `0` skipped — `7` hardening suites, `18` security/billing/AI items, `11` pipeline/language items).
  - `packages/remotion` + `apps/studio`: `npm run verify:remotion` -> exit `0`; `npm run verify:studio` -> exit `0` (`tsc --noEmit`, `eslint --max-warnings 0`, **`9/9` Studio tests**, Next.js `16.4.6` production build); `npm audit --omit=dev` -> **`found 0 vulnerabilities`**.
  - Phase 12 Concurrent Benchmark (`python scripts/run_benchmarks.py`, exit `0`, **`0.0%` error rate across all 4 scenarios**, peak traced heap `6.07 MB`):
    - `concurrent_register_20` (8 threads): `20` reqs, `0` err, `3.462s`, `5.78 rps`, `p50=1072.23ms`, `p95=1801.9ms`, `p99=1905.83ms`
    - `concurrent_credit_reservations_30` (12 threads): `30` reqs, `0` err, `0.882s`, `34.0 rps`, `p50=76.39ms`, `p95=717.82ms`, `p99=828.27ms`
    - `concurrent_e2e_video_render_6` (4 threads, mock Veo/TTS + real FFmpeg): `6` reqs, `0` err, `62.994s`, `0.1 rps`, `p50=44174.6ms`, `p95=44349.67ms`, `p99=44349.67ms`
    - `concurrent_signed_downloads_20` (8 threads): `20` reqs, `0` err, `1.735s`, `11.53 rps`, `p50=553.79ms`, `p95=1092.33ms`, `p99=1224.09ms`
    - Post-load reconciliation: `credit_balance=14`, `reserved_balance=30`, `ledger_net_credits=14`, `pending_reservations=30`, `ledger_entries=43`, `balance_discrepancy=0`, `reserved_discrepancy=0`, **`is_balanced=true`**.
  - Post-Hardening Live Browser E2E Regression (`http://127.0.0.1:3000`, `NODE_ENV=production`, `1280x800`): **PASS** (host-verified visited origin `http://127.0.0.1:3000`, evidence `final_step_24.png` (external QA artifact)). Verified `0` console/page/CSP errors, `0` HTTP `>= 500` responses, Google OAuth buttons present, registration (`HTTP 201`) -> email verification (`HTTP 200` with `HttpOnly` cookies & stripped JSON tokens), `3 Credits -> 2 Credits`, visible `#custom-prompt-input`, `POST /api/v1/videos/generate` (`HTTP 202` -> `COMPLETED`), `GET /api/v1/renders/[jobId]` (`HTTP 200`, `77,557` bytes, `video/mp4`), and billing ledger (`3` rows). Note: `X-Request-ID` is generated/persisted by FastAPI (`VideoJob.correlation_id`), though Studio BFF responses (`apps/studio/src/lib/serverStore.ts`) currently omit echoing `X-Request-ID` back to the browser.
- **Prior Verified Milestones (Preserved Baseline through `dcf344d`):**
  - Creamy White (`#FAF7F2`) + Botanical Green (`#15803D`) editorial redesign (`docs/DESIGN.md`, WCAG 2.2 AA), independent Security Audit (`docs/audit/AUDIT_REPORT.md` — `AUDIT-008`..`AUDIT-015`), React `19.3.1` + Next.js `16.4.6` + Remotion `4.0.545` upgrade, Google OAuth PKCE S256 + disposable email blocking + main-menu custom prompt (`veo_prompt`), and prior live browser E2E checks at `1280x800` and mobile breakpoints (`0` CSP/console/page errors).

## Next
- Review [AUDIT/FINAL_PRODUCTION_READINESS_REPORT.md](../AUDIT/FINAL_PRODUCTION_READINESS_REPORT.md) and decide whether to commit & push the hardened changes on `main`.
- Provision staging cloud infrastructure (PostgreSQL 15+, Redis 7+, Celery worker pool, GCP Veo/TTS/GCS, Stripe test mode, Google OAuth, SMTP) and run the Staging Go/No-Go checklist in [PRODUCTION_READINESS.md](../PRODUCTION_READINESS.md).

## Known Gaps / Deferred Blockers
1. **External Cloud Staging Validation Required:** Live PostgreSQL 15+ `SET ROLE authenticated` RLS testing, multi-process Redis + Celery worker `SIGKILL` lease recovery, Vertex AI Veo 3.1 / Cloud TTS / GCS bucket fetch, Stripe test-mode webhook delivery, Google OAuth 2.0 exchange, and transactional `SMTP_*` delivery require buyer staging credentials and were verified locally via SQLite/mocks/simulations.
2. **Studio BFF `X-Request-ID` Response Echo (Minor Observability Note):** Studio's `buildWorkerForwardHeaders()` forwards inbound `X-Request-ID` to FastAPI (where it is echoed and stored on `VideoJob.correlation_id`), while `forwardWorkerJsonResponse()` / `/api/v1/renders/[jobId]` do not copy `X-Request-ID` back onto Next.js browser responses.
3. **Local Python Optional Dependencies (`redis-py`, `pip-audit`):** Not pre-installed in the local Windows Python test interpreter; both are declared in [services/worker/pyproject.toml](../services/worker/pyproject.toml) (`[prod]` / `[dev]`) and executed by GitHub Actions CI ([.github/workflows/ci.yml](../.github/workflows/ci.yml)).

## How to Run Locally
1. **Worker (`services/worker`):**
   - Configure `.env` with `APP_ENV=development`, `MOCK_VERTEX_VEO=true`, `MOCK_TTS=true`, `CELERY_ALWAYS_EAGER=true`.
   - Start API: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
2. **Studio (`apps/studio`):**
   - Run dev (`npm run dev`) or production build (`npm run build; npx next start -H 127.0.0.1 -p 3000`) with `WORKER_API_URL=http://127.0.0.1:8000` and matching `WORKER_API_KEY`.
