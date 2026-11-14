# Production Readiness Report

**Product:** Localized AI Video Ad Pipeline (Non-English D2C SaaS)  
**Assessment Verdict:** **`CONDITIONALLY READY`**  
**Scope:** Application architecture, security & multi-tenant isolation, credit ledger & Stripe billing, AI & FFmpeg video pipeline, Next.js Creator Studio BFF + UI, database migrations/RLS, CI workflow, and automated verification.

---

## A. Executive Summary

The codebase has been upgraded from a single-tenant mock-first prototype into an isolated multi-tenant SaaS application with server-side authentication, workspace RBAC (`owner`/`admin`/`member`), transactional credit accounting, server-authoritative Stripe Checkout and signed webhook processing, SSRF-protected honest product scraping, strict live Vertex AI Veo / Cloud TTS integrations, private workspace media storage with signed downloads, and fail-closed production startup validation.

**Verdict — `CONDITIONALLY READY`:**  
All application code, security guardrails, database migrations, billing handlers, FFmpeg validation paths, and automated unit/integration tests pass locally (`24/24` worker tests, `4/4` studio tests, clean TypeScript/ESLint/Ruff checks, clean Next.js `14.2.35` production build). It is rated **CONDITIONALLY READY** rather than **UNCONDITIONALLY PRODUCTION READY** because:
1. Live cloud rendering (`Vertex AI Veo 3.1`, `Google Cloud Text-to-Speech`, `GCS`), live payment settlement (`Stripe Live Webhooks`), and managed `PostgreSQL / Supabase` RLS execution could only be tested via local SQLite/wal, local FFmpeg binaries, and mocked external HTTP contracts (no buyer live GCP/Stripe/Supabase credentials exist in this workspace).
2. Upstream npm packages constrained to React 18 compatibility (`next@14.2.35`, `remotion@4.0.242`) still carry published `npm audit` advisories requiring a coordinated major React 19 / Next 15–16 / Remotion 4.0.410+ upgrade prior to arbitrary multi-tenant public exposure (mitigated in the current architecture by disabling Server Actions, avoiding `next/image` remote proxy optimization, and running server-side video encoding directly via `ffmpeg`).

---

## B. Fixed Issues (Verified in Codebase)

1. **Authentication & Session Management (`services/worker/app/auth.py`, `apps/studio/src/components/AuthModal.tsx`)**
   - Implemented user registration, login, logout, email verification, single-use time-limited password reset tokens, PBKDF2-HMAC-SHA256 (`260,000` iterations) password hashing, HS256 JWT (plus Supabase JWT compat), opaque rotating SHA-256 refresh tokens with replay revocation, HttpOnly cookie delivery, and 5-attempt login lockout (`429`).
2. **Multi-Tenant Workspace Isolation & Authorization (`services/worker/app/main.py`, `apps/studio/src/lib/serverStore.ts`)**
   - Removed shared hardcoded `DEFAULT_WORKSPACE_ID` (`00000000-0000-0000-0000-000000000001`) and `DEFAULT_OWNER_ID` across backend and frontend.
   - Enforced `get_current_user` and `require_workspace_role` on every protected workspace, job, asset, billing, and download endpoint. Verified cross-customer `401`/`403` isolation across two distinct tenant accounts in automated tests.
3. **Worker API & BFF Proxy Security (`services/worker/app/security.py`, `services/worker/app/config.py`, `apps/studio/src/app/api/v1/`)**
   - Added `validate_production_config()` failing closed on startup if mocks are active, SQLite is configured, wildcard CORS `*` is set, or `WORKER_API_KEY` / JWT / signed URL secrets are weak or missing.
   - Added request body cap middleware (`413`), sliding-window rate limiting (`429`), and redacted JSON audit logging (`X-Request-ID`).
   - Replaced all unauthenticated Studio fake fallbacks (`createVideoJobFallback`, `topUpCreditsFallback`, `scrapeProductFallback`, synthetic MP4 header builder `getRenderMp4Buffer`) with fail-closed HTTP `503` / `401` BFF proxying.
4. **Transactional Credit Ledger & Stripe Billing (`services/worker/app/db.py`, `services/worker/app/billing.py`)**
   - Implemented immutable `credit_ledger` entries (`promo_grant`, `purchase`, `video_reservation`, `video_deduction`, `video_refund`, `admin_adjustment`, `payment_refund`), row-locked / conditional atomic reservations preventing negative balances under concurrency, and idempotent credit refunds on job failure or cancellation.
   - Added server-side Checkout (`pack_id` -> `STRIPE_PRICE_*`), raw-body `Stripe-Signature` HMAC verification with replay timestamp window, idempotent `stripe_events` deduplication, `charge.refunded` reversals, `403` guards blocking `dev-topup` in production, and admin secret checks for manual adjustments.
5. **Honest Scraping, Private Storage & Live AI Pipeline (`scraper.py`, `storage.py`, `veo.py`, `tts.py`, `compositor.py`, `tasks.py`)**
   - Removed fabricated product catalogs and fake prices (`CATALOG_PRESETS`, `$39.00`). Implemented SSRF IP/redirect validation and explicit `verified_fields` / `missing_fields` / `requires_user_confirmation` flags surfaced in Studio UI.
   - Removed public `/static/renders` mount. Files stay in workspace-scoped `STORAGE_ROOT/workspaces/{workspace_id}/...` with path containment, HMAC signed URLs, and FFmpeg stream/duration validation (`validate_mp4_file(require_audio=True)`) before finalizing credit deductions.
   - Removed silent live-mode fallback from Veo client and sine-wave oscillator fallback from Cloud TTS when `MOCK_* = false`; added retries and GCS `storage.googleapis.com` MP4 downloads.

---

## C. Remaining Known Limitations

1. **Upstream Node Package Advisories**: `npm audit --omit=dev` flags advisories on `next@14.2.35` / nested `postcss` (upstream recommends `next@16.4.6`) and `remotion@4.0.242` / `@remotion/player@4.0.242` (upstream recommends `>=4.0.410`). Upgrading to Next 15+/16+ requires a breaking migration to React 19 alongside testing `@remotion/player`.
2. **External Provider E2E Tests**: Vertex AI Veo 3.1, Google Cloud TTS, and Stripe Checkout/Webhook live cloud round-trips were verified using contract/protocol tests (`httpx` mocks and HMAC signatures) rather than live paid GCP/Stripe accounts.
3. **Typography & Multilingual Subtitling Fonts on Worker Container**: FFmpeg caption burn-in (`drawtext` / SRT / ASS subtitles) relies on RTL shaping libraries (`libass`, `harfbuzz`, `fribidi`) and system installation of `Noto Nastaliq Urdu`, `Noto Sans Arabic`, and `Noto Sans Devanagari` fonts inside the Linux worker container image.
4. **Synchronous vs Asynchronous Execution**: Local dev defaults to `CELERY_ALWAYS_EAGER=true`. Production deployments MUST run Redis + dedicated Celery worker processes with shared/GCS object storage (`STORAGE_ROOT` / `GCS_BUCKET`).

---

## D. Security Readiness

- **Authentication**: Complete (`PBKDF2`, JWT, rotating refresh cookies, lockout, reset/verify).
- **Authorization & Multi-Tenancy**: Enforced server-side via `require_workspace_role`; cross-tenant read/write/download/cancel/retry/checkout blocked with `403`/`401` and tested.
- **SSRF / Path Traversal / Rate Limiting / Redaction**: Implemented and covered by automated `pytest` assertions.
- **Gaps Before Launch**: Provision unique `>=32`-byte secrets in `.env` / Vault, deploy TLS reverse proxy, schedule upstream Next.js + Remotion major upgrade, and verify PostgreSQL RLS enforcement if enabling direct Supabase client queries.

---

## E. Payment Readiness

- **Stripe Checkout**: Server-side price lookup by `pack_id` only (`STRIPE_PRICE_STARTER_10`, `STRIPE_PRICE_GROWTH_50`, `STRIPE_PRICE_SCALE_200`); client-submitted prices/credits ignored.
- **Webhook Verification**: Verifies raw body HMAC `Stripe-Signature` within 300s tolerance and deduplicates `event.id` in `stripe_events`. Handles `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `payment_intent.payment_failed`, `charge.refunded`, and `charge.dispute.created`.
- **Action Required**: Create live Stripe Price IDs, configure `STRIPE_WEBHOOK_SECRET`, and run a `$1` Stripe test-mode + live-mode webhook smoke test (`stripe listen` / Stripe Dashboard).

---

## F. AI Integration Readiness

- **Vertex AI Veo 3.1 (`services/worker/app/veo.py`)**: Live path constructs real `:predictLongRunning` payloads, attaches base64 workspace product images, polls operation state with transient backoff, downloads MP4 from `storage.googleapis.com`, and validates via FFmpeg. Blocked from falling back to mock fixtures when `MOCK_VERTEX_VEO=false`.
- **Google Cloud Text-to-Speech (`services/worker/app/tts.py`)**: Live path calls Cloud TTS with regional voices (`ur-PK`, `ar-XA`, `hi-IN`, `en-US`) and validates WAV output; blocks oscillator fallback when `MOCK_TTS=false`.
- **Action Required**: Verify GCP project Vertex AI Veo quota (`veo-3.1-generate-001` allowlist in your GCP region) and service account IAM roles (`roles/aiplatform.user`, `roles/storage.objectAdmin`, Cloud Text-to-Speech API enabled).

---

## G. Database Readiness

- **Migrations**: Added `services/worker/migrations/001_initial_schema.sql`, `002_saas_multi_tenant_auth_billing.sql`, consolidated `schema.sql`, and cross-dialect idempotent upgrader `services/worker/app/migrations.py`.
- **Data Integrity**: Added FKs, non-null ownership fields, `ck_workspaces_non_negative_balance`, `ck_workspaces_non_negative_reserved`, atomic conditional reservations, and crash-recovery refund logic.
- **Action Required**: Apply `001` & `002` against production PostgreSQL 15+ / Supabase Postgres and configure automated daily PITR backups.

---

## H. Test Coverage Summary

| Scope | Command | Result Observed |
|---|---|---|
| Python Worker Lint | `services/worker`: `ruff check .` | Passed (`0` errors) |
| Python Worker Suite | `services/worker`: `pytest -v` | **24 passed, 0 failed, 0 skipped** (auth lifecycle, RBAC, 2-tenant isolation, concurrency ledger, Stripe checkout/HMAC webhook/refund, SSRF, prod config guard, Veo/TTS failure handling, SQLite upgrade, cancel/recovery, 4-language MP4 rendering) |
| Remotion Package | `packages/remotion`: `npm run typecheck && npm run lint` | Passed (`0` errors, `0` warnings) |
| Studio Frontend Tests | `apps/studio`: `npm run test` | **4 passed, 0 failed, 0 skipped** (auth cookie/header propagation, render download URL normalization, removal of shared defaults/fake fallbacks, RTL/LTR metadata) |
| Studio Build & Checks | `apps/studio`: `npm run typecheck && npm run lint && npm run build` | Passed (`0` TS errors, `0` ESLint warnings, compiled `Next.js 14.2.35` build across all 17 routes) |

---

## I. Buyer Handover Checklist

Before onboarding paying customers:
- [ ] Generate cryptographically random `AUTH_JWT_SECRET`, `SIGNED_URL_SECRET`, `WORKER_API_KEY`, and optional `ADMIN_ADJUST_SECRET`.
- [ ] Provision managed PostgreSQL 15+ (`DATABASE_URL`), apply migrations `001` and `002`, and configure backups + PgBouncer.
- [ ] Provision GCP Service Account JSON / Workload Identity with Vertex AI (`veo-3.1-generate-001`), Cloud Text-to-Speech, Gemini API (if using LLM script localization), and private GCS bucket (`GCS_BUCKET`).
- [ ] Create Stripe products/prices and webhook endpoint (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_*`).
- [ ] Configure `APP_ENV=production`, `MOCK_VERTEX_VEO=false`, `MOCK_TTS=false`, `INITIAL_PROMO_CREDITS`, `ENABLE_DEV_TOPUP=false`, and explicit `CORS_ORIGINS`.
- [ ] Build worker container with `ffmpeg`, `ffprobe`, `libass`/`harfbuzz`/`fribidi`, and Noto Nastaliq / Arabic / Devanagari fonts, plus Redis + Celery workers (`CELERY_ALWAYS_EAGER=false`).
- [ ] Execute live smoke test: Register -> Verify Email -> Stripe Checkout `$` test -> Upload PNG -> Scrape Live Store -> Confirm Facts -> Render Live Veo MP4 -> Download Signed MP4 -> Check Credit Ledger & Refund Flows.

---

## J. Final Verdict

**Status:** `CONDITIONALLY READY` — Core multi-tenant architecture, security isolation, transactional billing ledger, Stripe webhooks, SSRF protections, Studio UI/BFF refactor, and automated tests are complete and passing cleanly. Final go-live requires provisioning buyer cloud credentials (PostgreSQL, GCP Vertex AI + TTS, Stripe Live) and scheduling the React 19 / Next 15–16 / Remotion 4.0.410+ dependency upgrade.
