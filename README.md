# Localized AI Video Ad Pipeline (Non-English D2C)

A multi-tenant commercial SaaS platform for generating localized vertical (`9:16`) and landscape (`16:9`) AI video ads in **Urdu (`ur`)**, **Arabic (`ar`)**, **Hindi (`hi`)**, and **English (`en`)**. Built with Next.js App Router, Remotion RTL/LTR compositions, FastAPI, SQLAlchemy / PostgreSQL (+ Supabase RLS migrations), Stripe Checkout & webhooks, Vertex AI Veo 3.1, Google Cloud Text-to-Speech, and FFmpeg video compositing.

---

## Architecture Overview

- **`services/worker`** — Python `3.12+` + FastAPI + Celery + SQLAlchemy + FFmpeg
  - **Authentication & RBAC (`app/auth.py`)**: PBKDF2-SHA256 (`260,000` iterations) password hashing, short-lived JWT access tokens (local HS256 & optional Supabase JWT verification), opaque SHA-256 refresh sessions with reuse replay revocation, email verification, password reset tokens, brute-force account lockout, and sliding-window rate limiting (`app/security.py`).
  - **Multi-Tenant Isolation (`app/db.py`, `app/migrations.py`, `migrations/`)**: Strict customer, workspace (`owner` / `admin` / `member`), asset, credit ledger, and video job ownership checks on every protected route. Non-destructive schema migrations and PostgreSQL RLS policies.
  - **Credit Accounting & Stripe Billing (`app/billing.py`)**: Double-entry `credit_ledger` transactions (`promo_grant`, `purchase`, `video_reservation`, `video_deduction`, `video_refund`, `admin_adjustment`, `payment_refund`), row-locked/atomic reservation + idempotent refund, Stripe Checkout session creation (`pack_id` priced strictly server-side), raw-body `Stripe-Signature` HMAC verification, idempotent `stripe_events` deduplication, and refund reversals.
  - **AI Pipeline (`app/scraper.py`, `app/veo.py`, `app/tts.py`, `app/compositor.py`, `app/storage.py`)**: SSRF-protected live storefront scraper returning explicit `verified_fields` and `missing_fields` (zero fabricated prices/claims), Vertex AI Veo 3.1 (`veo-3.1-generate-001`) long-running generation + GCS artifact download, Google Cloud Text-to-Speech synthesis, FFmpeg caption burn-in & audio muxing, FFmpeg stream/duration validation before settling credits, private workspace file storage, and HMAC-signed download URLs.
  - **Fail-Closed Production Guardrails (`app/config.py`)**: `validate_production_config()` aborts startup in `production` if `MOCK_VERTEX_VEO=true`, `MOCK_TTS=true`, SQLite `DATABASE_URL`, wildcard CORS, or weak/missing secrets are detected.

- **`packages/remotion`** (`@video-ad/remotion`) — TypeScript + Remotion
  - Parameterized ad composition supporting RTL (`Noto Nastaliq Urdu` at `1.85` line-height for `ur`, `Noto Sans Arabic` for `ar`) and LTR (`Noto Sans Devanagari` for `hi`, `Inter` for `en`), synchronized caption timelines, product image conditioning, and tabular price overlays.

- **`apps/studio`** (`@video-ad/studio`) — Next.js `14.2.35` + Tailwind CSS v4 + `@remotion/player`
  - Dark-mode creator studio (`#09090B` canvas, `#18181B` surface, `#27272A` borders, `#6366F1` Indigo accent) acting as an authenticated BFF proxy to the FastAPI worker with HttpOnly cookie & Bearer forwarding, workspace switcher, product asset uploader, honest unverified-field confirmation gate, Stripe Checkout redirect flow, and job cancel/retry/signed-link controls.

---

## Documentation Index

- [**INSTALLATION.md**](./INSTALLATION.md) — Prerequisites, local environment setup, migrations, running all services
- [**DEPLOYMENT.md**](./DEPLOYMENT.md) — Production topology, required secrets, PostgreSQL/Supabase RLS, Stripe webhook setup, scaling
- [**API_DOCUMENTATION.md**](./API_DOCUMENTATION.md) — Worker REST API & Studio BFF endpoints, auth model, status codes
- [**SECURITY.md**](./SECURITY.md) — Threat model, tenancy isolation, SSRF/HMAC controls, dependency advisory disclosures
- [**CHANGELOG.md**](./CHANGELOG.md) — Summary of architectural, security, billing, AI, and frontend fixes
- [**PRODUCTION_READINESS_REPORT.md**](./PRODUCTION_READINESS_REPORT.md) — Audit assessment, verified checks, limitations, and buyer handover checklist

---

## Verification Commands

```bash
# 1. Worker lint & tests
cd services/worker && ruff check . && pytest -v

# 2. Remotion package typecheck & lint
cd packages/remotion && npm run typecheck && npm run lint

# 3. Studio typecheck, lint, tests & production build
cd apps/studio && npm run typecheck && npm run lint && npm run test && npm run build
```
