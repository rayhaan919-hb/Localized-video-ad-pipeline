# Changelog

## [2.0.0] — Commercial SaaS Hardening & Pipeline Repair

### Security & Multi-Tenant Architecture
- Implemented user accounts, salted PBKDF2-SHA256 authentication, JWT + rotating HttpOnly refresh token sessions, email verification, password reset flows, and account brute-force lockouts (`services/worker/app/auth.py`).
- Replaced shared hardcoded `DEFAULT_WORKSPACE_ID` (`00000000-0000-0000-0000-000000000001`) and `DEFAULT_OWNER_ID` across both backend and Studio frontend with tenant-isolated workspaces and `owner` / `admin` / `member` RBAC enforcement (`require_workspace_role`).
- Removed unauthenticated `/static/renders` static mount and Studio's fake MP4/preset/credit fallbacks; all downloads require JWT membership or HMAC-signed tokens (`services/worker/app/storage.py`).
- Added fail-closed startup configuration checks (`validate_production_config()`), sliding-window rate limiting, `413` body size limits, explicit CORS origin checks, `WORKER_API_KEY` enforcement, and redacted JSON audit logging (`services/worker/app/security.py`).
- Upgraded `next` in `apps/studio` from `14.2.25` to `14.2.35`.

### Billing & Credit Accounting
- Expanded `credit_ledger` into a full immutable transaction journal recording user, workspace, transaction type (`promo_grant`, `purchase`, `video_reservation`, `video_deduction`, `video_refund`, `admin_adjustment`, `payment_refund`), delta, previous balance, new balance, status, and payment/job references (`services/worker/app/db.py`).
- Added database migrations (`001_initial_schema.sql`, `002_saas_multi_tenant_auth_billing.sql`, `app/migrations.py`) supporting non-destructive SQLite upgrades and PostgreSQL RLS policies.
- Implemented server-authoritative Stripe Checkout (`pack_id` pricing resolved exclusively server-side), raw-body HMAC `Stripe-Signature` verification with replay window checks, idempotent `stripe_events` deduplication, and refund/dispute credit reversal (`services/worker/app/billing.py`).
- Guarded `dev-topup` strictly behind `not production and ENABLE_DEV_TOPUP=true` (`403` otherwise) and gated `admin-adjust` to platform administrators / `X-Admin-Secret`.

### AI Pipeline, Scraping & Video Rendering
- Removed fabricated storefront presets/prices (`CATALOG_PRESETS`, `$39.00`) from `scraper.py` and `tts.py`; implemented SSRF-guarded live extraction reporting explicit `verified_fields`, `missing_fields`, and `requires_user_confirmation`.
- Added strict validation, retries, base64 product image conditioning, and authenticated GCS object downloads in Vertex AI Veo client (`services/worker/app/veo.py`) and strict Cloud TTS error handling without live-mode fixture/oscillator fallbacks (`services/worker/app/tts.py`).
- Standardized job lifecycle states (`CREATED -> QUEUED -> PROCESSING -> RENDERING -> COMPLETED | FAILED | CANCELLED`), FFmpeg output stream/duration verification prior to finalizing credit deductions, customer cancel + retry endpoints, and crash recovery (`recover_interrupted_jobs()`).

### Creator Studio Frontend & CI/Docs
- Added `AuthModal.tsx`, workspace switcher/creation, uploaded product asset selector/uploader, aspect ratio (`9:16` / `16:9`) & clip duration (`4s` / `6s` / `8s`) selectors, honest storefront confirmation gate, signed link copy, cancel/retry buttons, and Stripe Checkout flow.
- Added automated frontend tests (`apps/studio/src/__tests__/studio.test.ts`), expanded worker security/billing/AI/concurrency test suite (`services/worker/tests/test_security_billing_ai.py`), GitHub Actions workflow (`.github/workflows/ci.yml`), and full operational/API/security documentation.
