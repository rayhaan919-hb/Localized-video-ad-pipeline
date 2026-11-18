# Security & Quality Audit Report (`AUDIT_REPORT.md`)

**Auditor Role:** Independent Phase 5 Auditor (`/security-and-quality-audit`)  
**Date:** 2026-11-19  
**Scope Revision:** Commit `c5628f0` + Creamy White / Botanical Green UI/UX pass + Audit Hardening Patchset (`AUDIT-008`–`AUDIT-013` fixed & verified)  
**Release Gate Decision:** **PASS** — **0 Open Critical, 0 Open High, 0 Open Medium**

---

## 1. Scope: Entry Points & Sensitive Assets

### Entry Points Audited
- **FastAPI Worker API (`services/worker/app/main.py`):**
  - Public/Auth: `GET /health`, `POST /v1/auth/register`, `/login`, `/refresh`, `/logout`, `/verify-email`, `/password-reset/request`, `/password-reset/confirm`, `GET /v1/auth/me`
  - Workspaces/RBAC: `GET/POST /v1/workspaces`, `GET /v1/workspaces/{id}`, `POST /v1/workspaces/{id}/members`, `PATCH /v1/workspaces/{id}/members/{uid}`
  - Billing: `GET /v1/billing/packages`, `POST /v1/billing/webhooks/stripe`, `POST /v1/workspaces/{id}/credits/checkout`, `/admin-adjust`, `/dev-topup`
  - Assets/Scraper/Jobs: `POST/GET /v1/workspaces/{id}/assets`, `GET /v1/assets/{asset_id}`, `POST /v1/products/scrape`, `POST /v1/videos/generate`, `GET /v1/videos`, `GET /v1/videos/{id}`, `POST /v1/videos/{id}/cancel`, `/retry`, `GET /v1/videos/{id}/signed-url`, `GET /v1/videos/{id}/download`
- **Background Worker (`services/worker/app/tasks.py`):** Celery `worker.process_video_job` + startup `recover_interrupted_jobs()`
- **Next.js Studio BFF & Security Headers (`apps/studio/src/app/api/v1/**`, `apps/studio/src/lib/serverStore.ts`, `apps/studio/next.config.mjs`):** CSRF-protected same-origin BFF routes, `HttpOnly` token stripping, UUID boundary guards, streaming media proxies, and CSP/HSTS headers
- **Database Schema & Migrations (`schema.sql`, `services/worker/migrations/001_*.sql`, `002_*.sql`, `app/migrations.py`, `app/db.py`)**

### Sensitive Assets Audited
- User passwords (`PBKDF2-HMAC-SHA256`), refresh session hashes (`auth_sessions`), reset/verify token hashes, JWT/signed URL HMAC secrets, `WORKER_API_KEY`, GCP OAuth/API keys, Stripe secrets, customer uploaded product assets & private rendered MP4s, and tenant credit balances/ledgers.

---

## 2. Security & Quality Checklist Results

| Domain | Status | Evidence & Notes |
|---|---|---|
| **Access Control & Tenant Isolation** | **PASS** | `require_workspace_role` enforced across every protected endpoint (`test_cross_customer_isolation_across_all_protected_endpoints`); RLS non-recursive `SECURITY DEFINER` policies (`AUDIT-001`) |
| **Injection & Input/File Safety** | **PASS** | Parameterized SQLAlchemy queries; zero `dangerouslySetInnerHTML`/`eval` sinks in Studio; strict BFF `isValidUuid` checks (`AUDIT-010`); sanitized multipart `Content-Type` (`AUDIT-013`); SSRF streaming limits (`AUDIT-003`) |
| **Auth, Sessions & CSRF** | **PASS** | `260k` PBKDF2-HMAC-SHA256, `hmac.compare_digest`, 5-attempt lockout, rotating SHA-256 refresh sessions; Studio BFF strips raw JWT/refresh tokens from JSON (`AUDIT-008`) and enforces same-origin CSRF checks on all cookie-authenticated mutations (`AUDIT-009`) |
| **Secrets & Git Hygiene** | **PASS** | Secret scan confirms zero live Stripe/GCP/private key literals in source/client bundles; `NEXT_PUBLIC_*` contains only optional Supabase URL/anon key and worker base URL fallback |
| **Web Hardening & Headers** | **PASS** | Next.js serves strict `Content-Security-Policy`, production `Strict-Transport-Security`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy` (`AUDIT-005`, `AUDIT-011`), plus `RequestContextMiddleware` (`AUDIT-002`) |
| **Abuse & Resource Bounds** | **PASS** | Bounded `SlidingWindowRateLimiter` eviction + workspace/member/asset rate limits (`AUDIT-012`); `list_workspace_assets` capped at 100 (`AUDIT-013`); streaming MP4/asset proxy delivery (`AUDIT-010`) |
| **Billing & Webhooks** | **PASS** | Raw-body HMAC `Stripe-Signature` (300s replay tolerance), server-authoritative `pack_id` pricing, `stripe_events` dedup, `async_payment_succeeded`, cumulative partial refund math (`AUDIT-004`) |
| **Dependencies (`npm audit` / Python)** | **PASS (PROD)** | `npm audit --omit=dev` returns **`found 0 vulnerabilities`** (6 moderate dev-only `minimatch` advisories in ESLint tooling, `AUDIT-015`). `pip-audit` not installed in environment (`AUDIT-015`). |
| **Accessibility & UI Quality** | **PASS** | WCAG 2.2 AA creamy-white `#FAF7F2` / botanical-green `#15803D` palette verified across `320px/375px/768px/1280px`; zero lint/TS warnings (`ruff check .`, `eslint --max-warnings 0`), **28/28** pytest, **7/7** Studio tests |

---

## 3. Severity-Ranked Findings Register

### `AUDIT-001` [Critical] — FIXED & VERIFIED (Static SQL)
- **Location:** `schema.sql:154-231`, `services/worker/migrations/002_saas_multi_tenant_auth_billing.sql`
- **Summary:** Fixed recursive `workspace_members` RLS policy via `SECURITY DEFINER` helpers `public.is_workspace_member(UUID)` and `public.is_workspace_admin(UUID)` with `SET search_path = public`, and enabled RLS across all 9 public tables.

### `AUDIT-002` [High] — FIXED & VERIFIED
- **Location:** `services/worker/app/security.py`, `services/worker/app/config.py`
- **Summary:** Enforced `X-Worker-API-Key` across `/v1/*` (`hmac.compare_digest`, fail-closed `503` in prod if unset) and gated `X-Forwarded-For` parsing behind `TRUST_PROXY_HEADERS=true`.

### `AUDIT-003` [High] — FIXED & VERIFIED
- **Location:** `services/worker/app/scraper.py`, `services/worker/app/storage.py`, `services/worker/app/config.py`
- **Summary:** Converted SSRF scraper fetcher to bounded streaming (`2 MiB`) and separated `MAX_RENDERED_VIDEO_BYTES` (`100 MiB`) from image upload limits (`8 MiB`).

### `AUDIT-004` [High] — FIXED & VERIFIED
- **Location:** `services/worker/app/billing.py`
- **Summary:** Added `checkout.session.async_payment_succeeded`, `IntegrityError` duplicate handling, and cumulative already-revoked deduction math for multiple partial refunds.

### `AUDIT-005` [Medium] — FIXED & VERIFIED
- **Location:** `apps/studio/next.config.mjs`, `services/worker/app/main.py`
- **Summary:** Added baseline browser security headers and tightened CORS header allowlist.

### `AUDIT-006` [Medium] — FIXED & VERIFIED
- **Location:** `services/worker/app/tts.py`, `services/worker/app/compositor.py`
- **Summary:** Moved Google API key to `x-goog-api-key` header and sanitized ASS `font_family`.

### `AUDIT-007` [Critical — Upstream Dependency Risk] — FIXED & VERIFIED
- **Location:** `package-lock.json`, `apps/studio/package.json`, `packages/remotion/package.json`
- **Summary:** Upgraded React `19.3.1`, Next.js `16.4.6`, Remotion `4.0.545`, Tailwind CSS `4.3.5`, and PostCSS `8.5.33`; `npm audit --omit=dev` -> `0 vulnerabilities`.

---

### `AUDIT-008` [High] — FIXED & VERIFIED
- **Location:** `apps/studio/src/app/api/v1/auth/[...path]/route.ts`, `apps/studio/src/lib/serverStore.ts`
- **Evidence:** FastAPI auth endpoints return JSON `access_token` and `refresh_token` alongside `Set-Cookie: HttpOnly` cookies (needed for headless API/CLI tests), and the Next.js Studio BFF forwarded the entire JSON payload unmodified to browser clients.
- **Impact:** Any future XSS bug or third-party script running in the browser could read raw session JWTs and long-lived refresh tokens directly out of `/api/v1/auth/login` or `/register` responses, defeating `HttpOnly` cookie isolation.
- **Fix Applied & Verified:** Added `stripAuthTokensFromPayload` in `apps/studio/src/lib/serverStore.ts` and wired it into `forwardWorkerJsonResponse` on `POST /api/v1/auth/[...path]/route.ts` while retaining `forwardCookies: true`. Browser UI continues signing in cleanly via `HttpOnly` cookies with zero `access_token`/`refresh_token` in JS payloads. Verified in `studio.test.ts` #7 and live `POST /api/v1/auth/register` browser check (`HTTP 201`, raw tokens absent from JSON body).

### `AUDIT-009` [High] — FIXED & VERIFIED
- **Location:** `apps/studio/src/lib/serverStore.ts`, `apps/studio/src/app/api/v1/{auth/[...path],products/scrape,videos/generate,videos/[jobId]/cancel,videos/[jobId]/retry,workspaces,workspaces/[id]/assets,workspaces/[id]/credits,workspaces/[id]/credits/dev-topup,workspaces/[id]/members}/route.ts`
- **Evidence:** Session cookies (`lva_access_token` / `lva_refresh_token`) use `SameSite=Lax`, and cookie-authenticated mutating `POST` routes at the Next.js BFF lacked explicit `Origin` / `Referer` / `Sec-Fetch-Site` enforcement.
- **Impact:** Defense-in-depth gap against cross-site request forgery if a user triggers cross-site navigation, sibling subdomain requests, or browser policy edge cases on authenticated `POST` endpoints (credit consumption, job creation, workspace changes).
- **Fix Applied & Verified:** Implemented `assertSameOriginRequest(request)` in `apps/studio/src/lib/serverStore.ts` (blocking `Sec-Fetch-Site: cross-site`, `Origin: null`, cross-origin `Origin`/`Referer`, and cookie-only `POST`s missing both `Origin` and `Referer` with `403`, while permitting legitimate same-origin browser calls and non-cookie Bearer API clients), and applied it at the entry of all 10 mutating Studio BFF handlers (keeping `POST /api/v1/billing/webhooks/stripe` exempt for Stripe-signed webhooks). Verified by `studio.test.ts` #7 and live browser generation flow (`HTTP 202`).

### `AUDIT-010` [Medium] — FIXED & VERIFIED
- **Location:** `apps/studio/src/app/api/v1/renders/[jobId]/route.ts`, `apps/studio/src/app/api/v1/assets/[assetId]/route.ts`, `apps/studio/src/app/api/v1/videos/[jobId]/signed-url/route.ts`, `apps/studio/src/app/api/v1/workspaces/[id]/*/route.ts`
- **Evidence:** Render/asset proxy routes buffered full payloads via `await workerRes.arrayBuffer()` (up to `100 MiB` per request), forwarded upstream `Content-Type` unchecked on assets without `nosniff`, and did not reject non-UUID IDs before forwarding to the worker.
- **Impact:** Concurrent video downloads risk Node.js BFF memory exhaustion/OOM; arbitrary MIME reflection without `nosniff` and sandbox CSP weakens file-serving isolation.
- **Fix Applied & Verified:** Added `isValidUuid` boundary validation (`400`/`422`) on all dynamic UUID route parameters and body `workspace_id`, switched render and asset proxies to stream `workerRes.body` directly (`Content-Length` preserved), whitelisted asset MIME types to `image/png`, `image/jpeg`, `image/webp` (`application/octet-stream` fallback), and added `X-Content-Type-Options: nosniff` + `Content-Security-Policy: default-src 'none'; sandbox` on assets. Verified via `studio.test.ts` #7 and live browser MP4 streaming download (`HTTP 200`, `77,386` bytes).

### `AUDIT-011` [Medium] — FIXED & VERIFIED
- **Location:** `apps/studio/next.config.mjs`
- **Evidence:** Prior Next.js headers lacked `Content-Security-Policy` and production `Strict-Transport-Security`.
- **Impact:** Reduced protection against inline script injection, untrusted frame embedding (`frame-ancestors 'none'`), unexpected form targets, and SSL stripping over HTTPS.
- **Fix Applied & Verified:** Added strict `Content-Security-Policy` (`default-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self' https://checkout.stripe.com`, `worker-src 'self' blob:` for Remotion) and production `Strict-Transport-Security: max-age=63072000; includeSubDomains`. Verified by `studio.test.ts` #7 and live production Next.js + Remotion `<Player>` verification with `0` CSP violations.

### `AUDIT-012` [Medium] — FIXED & VERIFIED
- **Location:** `services/worker/app/security.py`, `services/worker/app/main.py`
- **Evidence:** `SlidingWindowRateLimiter._events` never evicted expired IP/user keys, growing unboundedly under rotating traffic; additionally, `create_workspace` (`POST /v1/workspaces`), `add_workspace_member` (`POST /v1/workspaces/{id}/members` — account existence probe vector returning `404` vs `201`), and `upload_workspace_asset` (`POST /v1/workspaces/{id}/assets`) lacked rate limits.
- **Impact:** Long-running worker processes faced unbounded memory growth, and authenticated attackers could rapidly enumerate registered emails or spam workspace/asset storage.
- **Fix Applied & Verified:** Bounded `SlidingWindowRateLimiter(max_keys=10_000)` with periodic stale sweep and oldest-timestamp eviction, and enforced per-user rate limits (`20/min` on workspace creation and member invites, `30/min` on asset uploads). Verified via `test_rate_limiter_eviction_member_limits_and_multipart_sanitization` (`429` + `Retry-After` on 21st member probe).

### `AUDIT-013` [Medium] — FIXED & VERIFIED
- **Location:** `services/worker/app/main.py` (`_extract_uploaded_asset_payload`, `list_workspace_assets`)
- **Evidence:** Multipart parsing interpolated raw `content_type` directly before `.encode("latin-1")`, allowing CRLF or non-latin-1 characters to trigger `500 UnicodeEncodeError` or malformed MIME header parsing; `list_workspace_assets` returned unbounded rows.
- **Impact:** Untrusted `Content-Type` headers could cause unhandled exceptions (`500`), and large workspaces could trigger heavy DB/JSON serialization responses.
- **Fix Applied & Verified:** Stripped `\r`/`\n` and ignored non-latin-1 characters on `content_type` before parsing, and bounded `list_workspace_assets` with `.limit(100)`. Verified by `test_rate_limiter_eviction_member_limits_and_multipart_sanitization`.

---

### `AUDIT-014` [Low — Accepted Operational Boundary]
- **Location:** `services/worker/app/security.py` (`SlidingWindowRateLimiter`), `services/worker/app/auth.py`
- **Evidence:** In-process `SlidingWindowRateLimiter` uses process-local threading memory.
- **Impact:** Single-worker deployments behave consistently, whereas multi-replica horizontal worker deployments would divide per-process rate limits across replicas.
- **Recommendation:** Back `SlidingWindowRateLimiter` with Redis (`REDIS_URL`) before scaling API replicas horizontally.

### `AUDIT-015` [Low — Dependency Tooling Hygiene]
- **Location:** `package-lock.json` (`devDependencies`), Python environment
- **Evidence:** `npm audit` full tree reports 6 moderate `minimatch` advisories strictly under `devDependencies` (ESLint tooling), while production dependencies (`npm audit --omit=dev`) have **`0` vulnerabilities**. `pip-audit` binary was unavailable locally to scan Python packages (`fastapi==0.162.7`, `starlette==1.10.0`, `uvicorn==0.54.0`, `pydantic==2.14.3`, `sqlalchemy==2.1.8`, `httpx==0.28.1`, `celery==5.7.0`).
- **Recommendation:** Upgrade ESLint toolchain to v9 when convenient and install/run `pip-audit` in CI on `services/worker` before production releases.
