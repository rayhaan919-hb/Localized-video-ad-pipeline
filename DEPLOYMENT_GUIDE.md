# Enterprise Production Deployment Guide

## 1. Required Production Architecture

Do not co-locate production execution inside single-process dev modes. A compliant commercial deployment runs 5 distinct components:

1. **Next.js Studio Web App (`apps/studio`)** — Node.js 22 (`next start`), terminating TLS behind a trusted CDN/reverse proxy, forwarding API calls server-to-server with `X-Worker-API-Key` and managing `HttpOnly` auth cookies.
2. **FastAPI API Service (`services/worker/app/main.py`)** — Stateless horizontally scalable ASGI replicas (`uvicorn` / `gunicorn -k uvicorn.workers.UvicornWorker`), `TRUST_PROXY_HEADERS=true` when behind a reverse proxy.
3. **Celery Background Workers (`services/worker/app/tasks.py`)** — Dedicated worker processes (`--concurrency=2 -O fair --prefetch-multiplier=1`) executing Vertex AI Veo, Google Cloud TTS, and FFmpeg compositing, renewing DB leases via periodic heartbeats.
4. **PostgreSQL 15+ (Primary + RLS + PITR)** — Hosts multi-tenant data, immutable financial `credit_ledger`, Stripe webhook deduplication, and job leases.
5. **Redis 7+ (Persistent Broker + Distributed Rate Limiter)** — Required in production (`REDIS_URL`). Shares sliding-window rate-limit counters across all FastAPI instances and dispatches Celery jobs reliably.

---

## 2. Pre-Deploy Security & Config Gate

Every production startup runs `validate_production_config()`. Startup aborts immediately unless ALL of the following hold:
- `APP_ENV=production`
- `MOCK_VERTEX_VEO=false` and `MOCK_TTS=false`
- `ENABLE_DEV_TOPUP=false` and `EXPOSE_DEV_AUTH_TOKENS=false`
- `CELERY_ALWAYS_EAGER=false`
- `REDIS_URL=redis://...` (or `rediss://...`) and reachable via TCP
- `DATABASE_URL=postgresql://...` (SQLite strictly forbidden)
- `WORKER_API_KEY` >= 24 chars
- `AUTH_JWT_SECRET` >= 32 chars (and `SIGNED_URL_SECRET` >= 32 chars)
- `CORS_ORIGINS` contains explicit origins (no `*`)
- `GCP_PROJECT_ID`, `GCS_BUCKET`, and valid GCP credentials (`GOOGLE_APPLICATION_CREDENTIALS` or `GOOGLE_API_KEY`)
- `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` configured

---

## 3. Step-by-Step Deployment

1. **Apply Database Migrations:**
   Run migrations `002`, `003`, `004`, and `005` cleanly (see [`DATABASE_MIGRATIONS.md`](./DATABASE_MIGRATIONS.md)).
2. **Build & Verify Applications:**
   ```bash
   # Backend checks
   cd services/worker
   pip install -e ".[prod]"
   ruff check .
   pytest -v

   # Frontend & Remotion build
   cd ../..
   npm ci
   npm run verify:remotion
   npm run verify:studio
   ```
3. **Start FastAPI API Service:**
   ```bash
   cd services/worker
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
   ```
4. **Start Dedicated Celery Worker Pool:**
   ```bash
   cd services/worker
   celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2 --prefetch-multiplier=1 -O fair --max-tasks-per-child=50
   ```
5. **Schedule Periodic Lease Recovery (Cron / Celery Beat):**
   Execute every 60 seconds:
   ```bash
   python -c "from app.tasks import recover_interrupted_jobs; recover_interrupted_jobs(min_age_seconds=120)"
   ```
6. **Start Next.js Studio Server:**
   ```bash
   cd apps/studio
   npx next start -H 0.0.0.0 -p 3000
   ```
7. **Post-Deploy Verification:**
   - Confirm `GET /health` returns `200` with `"database": "ok"`, `"redis_broker": true`, `"celery_eager_mode": false`, `"ffmpeg_available": true`.
   - Trigger one Stripe test-mode webhook delivery or test-mode checkout and verify `/v1/workspaces/{id}/credits/reconcile` returns `"is_balanced": true`.

---

## 4. Rollback Procedure

- **Application Rollback:** Shift traffic back to the prior API/Worker/Studio container images. Migrations `002`–`005` are additive and non-destructive, permitting safe minor-version code rollback.
- **Database Rollback:** Restore the pre-deploy PostgreSQL snapshot / PITR target if data recovery is required, then run `recover_interrupted_jobs(min_age_seconds=0)` before resuming traffic.
