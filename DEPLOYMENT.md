# Production Deployment Guide

This checklist covers deploying **Localized AI Video Ad Pipeline** to a live production environment.

---

## 1. Fail-Closed Production Guardrails (`APP_ENV=production`)

When `APP_ENV=production`, `services/worker/app/config.py` (`validate_production_config()`) aborts FastAPI startup unless **all** of the following hold:

1. `MOCK_VERTEX_VEO=false` and `MOCK_TTS=false` (mock providers are strictly disallowed in production).
2. `GCP_PROJECT_ID` and `GCS_BUCKET` (`gs://...`) are set, along with Vertex/Cloud TTS authentication (`GOOGLE_APPLICATION_CREDENTIALS`, ADC workload identity, or `VERTEX_ACCESS_TOKEN`).
3. `DATABASE_URL` points to PostgreSQL (`postgresql://...` or `postgresql+psycopg://...`) — SQLite is rejected in production.
4. `AUTH_JWT_SECRET` (or `SUPABASE_JWT_SECRET`) and `SIGNED_URL_SECRET` are strong secrets (`>= 32` characters, non-placeholder).
5. `WORKER_API_KEY` is configured and strong (all Studio BFF -> Worker traffic and internal routes validate it).
6. `CORS_ORIGINS` is set to explicit HTTPS frontend origins (wildcard `*` is rejected).
7. `ENABLE_DEV_TOPUP=false` (dev top-up endpoints always return HTTP `403` in production regardless of flags).

---

## 2. Database & Migrations (PostgreSQL / Supabase)

1. Provision PostgreSQL 15+ (e.g., Supabase Postgres, AWS RDS, Cloud SQL).
2. Enable `pgcrypto` and apply:
   - `services/worker/migrations/001_initial_schema.sql`
   - `services/worker/migrations/002_saas_multi_tenant_auth_billing.sql`
3. Verify RLS policies are enabled if exposing Supabase REST/PostgREST directly alongside the FastAPI API.
4. Configure connection pooling (PgBouncer / Supabase Transaction Pooler) and scheduled automated backups.

---

## 3. Private Object & Render Storage

- Mount a persistent private volume for `STORAGE_ROOT` (shared across FastAPI API and Celery worker containers so the API can stream MP4s and private product images written by the worker), **or** upload final artifacts directly to your private GCS bucket (`GCS_BUCKET`) and front downloads with signed URLs.
- **Never** expose `STORAGE_ROOT` over unauthenticated static file hosting (`nginx`, S3 public ACL, or FastAPI `StaticFiles`). All downloads must go through `GET /v1/videos/{job_id}/download` (JWT RBAC check or HMAC signed token) or `GET /v1/assets/{asset_id}`.

---

## 4. Stripe Live Webhook Configuration

1. Create three one-time credit pack Products/Prices in Stripe Live Mode (`starter_10`, `growth_50`, `scale_200`) and copy their `price_...` IDs into:
   - `STRIPE_PRICE_STARTER_10`
   - `STRIPE_PRICE_GROWTH_50`
   - `STRIPE_PRICE_SCALE_200`
2. Configure `STRIPE_SECRET_KEY=sk_live_...`, `STRIPE_CURRENCY=usd`, `STRIPE_CHECKOUT_SUCCESS_URL=https://app.yourdomain.com/?checkout=success`, `STRIPE_CHECKOUT_CANCEL_URL=https://app.yourdomain.com/?checkout=cancelled`.
3. Register webhook endpoint in Stripe Dashboard:
   - URL: `https://api.yourdomain.com/v1/billing/webhooks/stripe` (or Next.js proxy `https://app.yourdomain.com/api/v1/billing/webhooks/stripe`)
   - Events:
     - `checkout.session.completed`
     - `checkout.session.async_payment_succeeded`
     - `payment_intent.payment_failed`
     - `charge.refunded`
     - `charge.dispute.created`
4. Copy the signing secret (`whsec_...`) into `STRIPE_WEBHOOK_SECRET`.

---

## 5. Worker, Queue & Frontend Topology

- **Frontend (`apps/studio`)**:
  - Build with `npm run build` and run via `npm run start` behind HTTPS TLS termination (Vercel, Cloud Run, Fly.io, or Docker + Nginx).
  - Set `[SERVER-ONLY]` variables (`WORKER_API_URL`, `WORKER_API_KEY`) strictly in server runtime env — never with `NEXT_PUBLIC_`.
- **FastAPI API (`services/worker`)**:
  - Run behind a reverse proxy with HTTPS termination, `X-Forwarded-For` trusted appropriately, and Uvicorn/Gunicorn workers:
    `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`
- **Celery Background Workers**:
  - Set `CELERY_ALWAYS_EAGER=false` and `REDIS_URL=redis://...` (or `rediss://...`).
  - Run `celery -A app.tasks.celery_app worker --concurrency=2 --loglevel=info` with FFmpeg + FFprobe installed in the container image and Google Fonts / Noto Nastaliq / Noto Sans Arabic / Noto Sans Devanagari fonts present for any drawtext fallback rendering.
  - On worker boot, `recover_interrupted_jobs()` marks stale in-progress jobs as `FAILED` and atomically refunds reserved credits.

---

## 6. Operational Health Checks & Secret Rotation

- **Readiness / Liveness Probe**: `GET /health` returns service status, environment, FFmpeg availability, mock flags, and database connectivity (`status: "ok"` vs `"degraded"`).
- **Secret Rotation**:
  - Rotating `AUTH_JWT_SECRET` invalidates existing short-lived access tokens (`ACCESS_TOKEN_TTL_SECONDS`, default 1 hour); active users seamlessly re-authenticate or refresh.
  - Rotating `SIGNED_URL_SECRET` immediately invalidates previously issued timed download tokens (`SIGNED_URL_TTL_SECONDS`).
  - Rotating `WORKER_API_KEY` should be staged cleanly between Next.js Studio and FastAPI instances during zero-downtime rollout.
