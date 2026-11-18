# Security & Quality Audit Report (`AUDIT_REPORT.md`)

**Auditor Role:** Independent `/qa-gate` Security & Quality Review  
**Date:** 2026-11-19  
**Baseline Commit + Hardening Patchset:** `33a9948` + local QA-gate security/functional hardening fixes  

---

## 1. Scope: Entry Points & Sensitive Assets

### Entry Points Audited
- **FastAPI Worker API (`services/worker/app/main.py`):**
  - Public/Auth: `GET /health`, `POST /v1/auth/register`, `/login`, `/refresh`, `/logout`, `/verify-email`, `/password-reset/request`, `/password-reset/confirm`, `GET /v1/auth/me`
  - Workspaces/RBAC: `GET/POST /v1/workspaces`, `GET /v1/workspaces/{id}`, `POST /v1/workspaces/{id}/members`, `PATCH /v1/workspaces/{id}/members/{uid}`
  - Billing: `GET /v1/billing/packages`, `POST /v1/billing/webhooks/stripe`, `POST /v1/workspaces/{id}/credits/checkout`, `/admin-adjust`, `/dev-topup`
  - Assets/Scraper/Jobs: `POST/GET /v1/workspaces/{id}/assets`, `GET /v1/assets/{asset_id}`, `POST /v1/products/scrape`, `POST /v1/videos/generate`, `GET /v1/videos`, `GET /v1/videos/{id}`, `POST /v1/videos/{id}/cancel`, `/retry`, `GET /v1/videos/{id}/signed-url`, `GET /v1/videos/{id}/download`
- **Background Worker (`services/worker/app/tasks.py`):** Celery `worker.process_video_job` + startup `recover_interrupted_jobs()`
- **Next.js Studio BFF (`apps/studio/src/app/api/v1/**`):** Proxy routes relaying HttpOnly cookies, `X-Worker-API-Key`, and `Stripe-Signature`
- **Database Schema & Migrations:** `schema.sql`, `services/worker/migrations/001_*.sql`, `002_*.sql`, `app/migrations.py`, `app/db.py`

### Sensitive Assets Audited
- User passwords (`PBKDF2-HMAC-SHA256`), refresh session hashes (`auth_sessions`), reset/verify token hashes, JWT/signed URL HMAC secrets, `WORKER_API_KEY`, GCP OAuth/API keys, Stripe secrets, customer uploaded product assets & private rendered MP4s, and tenant credit balances/ledgers.

---

## 2. Security & Quality Checklist Results

| Domain | Status | Evidence & Notes |
|---|---|---|
| **Access Control & Tenant Isolation** | **PASS** (Worker) / **PASS** (Schema fixed) | `require_workspace_role` enforced on all protected routes (`test_cross_customer_isolation_across_all_protected_endpoints`); RLS recursion fixed via `SECURITY DEFINER` helpers (`AUDIT-001`) |
| **Injection & Input/File Safety** | **PASS** | Parameterized SQLAlchemy ORM/Core queries; SSRF IPv4/IPv6 + redirect validation with streaming byte caps (`AUDIT-003`); magic-byte image checks; FFmpeg `-i` validation; `font_family` ASS sanitized (`AUDIT-006`) |
| **Auth & Session Management** | **PASS** | `260k` PBKDF2-HMAC-SHA256, `hmac.compare_digest`, 5-attempt lockout, rotating SHA-256 refresh sessions with theft replay revocation, HttpOnly/SameSite cookies, auto UI refresh (`BUG-008`) |
| **Secrets & Git Hygiene** | **PASS** | Git history regex scan across all commits returned zero live `sk_live_`, `whsec_`, `AIza`, private keys, or JWTs; Google API keys moved from URL query string to `x-goog-api-key` header (`AUDIT-006`) |
| **Web Hardening** | **PASS** | `RequestContextMiddleware` enforces body cap (`413`), rate limit (`429`), `X-Worker-API-Key` (`401`/`503`), `X-Forwarded-For` trust gate (`AUDIT-002`); Next.js security headers configured (`AUDIT-005`) |
| **Billing & Webhooks** | **PASS** | Raw-body HMAC `Stripe-Signature` (300s replay tolerance), server-authoritative `pack_id` pricing, `stripe_events` dedup, `async_payment_succeeded`, cumulative partial refund accounting (`AUDIT-004`) |
| **Dependencies (`npm audit` / `pip-audit`)** | **PASS (PROD) — DEV MODERATE** | `npm audit --omit=dev` reports **`found 0 vulnerabilities`** after upgrading to React `19.3.1`, Next.js `16.4.6`, and Remotion `4.0.545` (`AUDIT-007` resolved; 6 moderate dev-only `minimatch` advisories remain in ESLint tooling) |
| **Quality, Performance & Operability** | **PASS** | Zero lint errors (`ruff check .`, `eslint --max-warnings 0`), strict TS, `next build` passes cleanly, indexed tenant queries, live `/health` DB + FFmpeg probes, non-blocking mobile modal scroll, accessible icon `aria-label`s |

---

## 3. Severity-Ranked Findings Register

### `AUDIT-001` [Critical] — FIXED & VERIFIED (Static SQL)
- **Location:** `schema.sql:154-231`, `services/worker/migrations/002_saas_multi_tenant_auth_billing.sql`
- **Evidence:** Original `workspace_members_select` policy queried `workspace_members` directly (`EXISTS (SELECT 1 FROM workspace_members wm ...)`), causing infinite recursion in PostgreSQL RLS when evaluated under non-superuser roles; additionally `users`, `auth_sessions`, `stripe_events`, and `schema_migrations` lacked `ENABLE ROW LEVEL SECURITY`.
- **Impact:** Under direct Supabase/PostgREST access, any authenticated query touching `workspace_members` would fail with `42P17 infinite recursion`, and sensitive auth/session/Stripe tables lacked PostgREST default-deny RLS.
- **Fix Applied & Verified:** Added `SECURITY DEFINER` helpers `public.is_workspace_member(UUID)` and `public.is_workspace_admin(UUID)` with `SET search_path = public` (executable only by `authenticated`/`service_role`), enabled RLS across all 9 public tables (default-deny on `users`, `auth_sessions`, `stripe_events`, `schema_migrations`), and made `002` idempotently guard helper creation on `auth.uid()` existence so vanilla Postgres migrations also succeed. *(Note: execute `schema.sql` against target Supabase Postgres during buyer DB provisioning to confirm runtime PostgREST behavior.)*

### `AUDIT-002` [High] — FIXED & VERIFIED
- **Location:** `services/worker/app/security.py:140-209`, `services/worker/app/config.py:165-315`
- **Evidence:** Middleware never enforced `WORKER_API_KEY` even when set in env, and `get_client_ip()` trusted client-supplied `X-Forwarded-For` leftmost IP unconditionally.
- **Impact:** Attackers reaching the worker directly could bypass BFF controls even when `WORKER_API_KEY` was configured, and spoof `X-Forwarded-For` per request to evade brute-force auth rate limits.
- **Fix Applied & Verified:** Middleware now enforces `X-Worker-API-Key` (`hmac.compare_digest`) across `/v1/*` whenever configured (or `503` in production if unset), exempting `/health`, `/v1/billing/webhooks/stripe`, and signed token `/download?token=...`. `get_client_ip()` ignores `X-Forwarded-For` unless `TRUST_PROXY_HEADERS=true` (and takes rightmost proxy-appended IP). Verified by `pytest` `test_worker_api_key_enforcement_and_xff_spoof_protection`.

### `AUDIT-003` [High] — FIXED & VERIFIED
- **Location:** `services/worker/app/scraper.py:327-444`, `services/worker/app/storage.py:76-82`, `services/worker/app/config.py:166`
- **Evidence:** `_fetch_with_ssrf_redirects` buffered unbounded response bodies (`client.get`), and `register_workspace_file` bounded rendered MP4s with `MAX_ASSET_UPLOAD_BYTES` (8 MB).
- **Impact:** Malicious URLs could cause worker OOM during scrape, while legitimate long HD MP4 renders >8 MB would fail with `StorageError` after expensive Veo generation.
- **Fix Applied & Verified:** Converted redirect fetcher to bounded streaming (`client.stream` + `Content-Length` precheck + running byte cap), added `MAX_RENDERED_VIDEO_BYTES` (`100 MiB` default), and verified via `test_production_guards_video_limit_ssrf_and_stale_recovery`.

### `AUDIT-004` [High] — FIXED & VERIFIED
- **Location:** `services/worker/app/billing.py:227-439`
- **Evidence:** `process_stripe_webhook` ignored `checkout.session.async_payment_succeeded` (used by delayed payment methods), lacked `IntegrityError` handling for concurrent duplicate deliveries, and recalculated cumulative `amount_refunded` from zero on subsequent partial `charge.refunded` webhooks.
- **Impact:** Delayed payments wouldn't credit users; concurrent webhook retries could return `500`; multiple partial refunds could over-revoke workspace credits.
- **Fix Applied & Verified:** Added `checkout.session.async_payment_succeeded`, cumulative already-revoked deduction math (`sum(-credits_delta)`), and `IntegrityError` duplicate handling. Verified by `test_async_payment_succeeded_and_multiple_partial_refunds`.

### `AUDIT-005` [Medium] — FIXED & VERIFIED
- **Location:** `apps/studio/next.config.mjs`, `services/worker/app/main.py:310-322`
- **Evidence:** Next.js responses lacked baseline security headers; FastAPI CORS allow-headers listed `X-Admin-Secret` even though admin adjustments are server-to-server.
- **Impact:** Weakened clickjacking/MIME-sniffing/referrer defense-in-depth on Studio frontend.
- **Fix Applied & Verified:** Added `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and `X-DNS-Prefetch-Control: off` in `next.config.mjs`; tightened CORS headers and disabled `allow_credentials` when `*` is present. Verified in `studio.test.ts`.

### `AUDIT-006` [Medium] — FIXED & VERIFIED
- **Location:** `services/worker/app/tts.py:346-358, 542-550`, `services/worker/app/compositor.py:45-47`
- **Evidence:** Google Gemini & Cloud TTS REST calls embedded `GOOGLE_API_KEY` directly in URL query string (`?key=...`), and `script_json["font_family"]` flowed un-sanitized into ASS subtitle headers.
- **Impact:** Query-string API keys risk exposure in proxy/HTTP client error logs; unexpected characters in `font_family` could break libass `[V4+ Styles]` lines.
- **Fix Applied & Verified:** Moved Google API key to `x-goog-api-key` HTTP header cleanly and sanitized `font_family` with strict `[A-Za-z0-9 _-]` whitelist. Verified via full worker test suite (`27 passed`).

### `AUDIT-007` [Critical — Upstream Dependency Risk] — FIXED & VERIFIED
- **Location:** `package-lock.json`, `apps/studio/package.json` (`next@^16.4.6`, `postcss@^8.5.33`), `packages/remotion/package.json` (`remotion@4.0.545`, `@remotion/player@4.0.545`, `react@^19.3.1`, `react-dom@^19.3.1`)
- **Evidence:** Prior `npm audit --omit=dev` flagged **4 advisories (3 Critical, 1 High)** across `next@14.2.35`, `postcss@<=8.5.22`, and `remotion@4.0.242` / `@remotion/player@4.0.242`.
- **Fix Applied & Verified:** Upgraded monorepo to React `19.3.1`, Next.js `16.4.6` (with async `Promise` dynamic `params` across all 10 App Router API route handlers), Remotion `4.0.545`, `lucide-react@^0.577.0`, `tailwindcss@^4.3.5`, and `postcss@^8.5.33`. Removed deprecated `eslint` config key from `apps/studio/next.config.mjs` and updated CI Node target to `22`.
- **Post-Fix Verification:** `npm audit --omit=dev` now returns **`found 0 vulnerabilities`**. `verify:remotion`, `verify:studio` (including `next build` under Turbopack + `5/5` tests), and live browser smoke testing (`http://127.0.0.1:3000`, `@remotion/player@4.0.545` playing frames `00/60 -> 50/60`, async `[id]`/`[jobId]` routes, UR/AR/HI/EN switching) passed cleanly with zero console/runtime/hydration errors. *(DevDependencies retain 6 moderate `minimatch` advisories under `@typescript-eslint` v7 only.)*
