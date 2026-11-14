# Installation & Local Development Guide

This guide covers setting up **Localized AI Video Ad Pipeline** cleanly for local development and testing.

---

## 1. Prerequisites

| Dependency | Minimum Version | Purpose |
|---|---|---|
| Python | `3.12+` | FastAPI worker, Celery tasks, AI/billing/auth services |
| Node.js | `20.x` LTS | Next.js Creator Studio & Remotion workspace |
| npm | `10.x` | Monorepo workspace installation (`packages/*`, `apps/*`) |
| FFmpeg & FFprobe | `6.0+` | Video/audio compositing and MP4 stream validation (`PATH` must expose `ffmpeg` and `ffprobe`) |
| PostgreSQL (Prod/Staging) | `15+` | Recommended multi-tenant database (SQLite `local_dev.db` works for local dev/tests only) |
| Redis (Optional async) | `7+` | Celery broker/result backend when `CELERY_ALWAYS_EAGER=false` |

Verify CLI tools before installing packages:

```bash
python --version
node --version
npm --version
ffmpeg -version
ffprobe -version
```

---

## 2. Clone & Install Dependencies

```bash
# From repository root:
npm install

# Install Python worker in editable mode with dev/test dependencies:
cd services/worker
python -m venv .venv

# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

> **Note (Windows):** Core worker dependencies (`fastapi`, `sqlalchemy`, `httpx`, `pytest`, `ruff`) are pure Python or ship prebuilt wheels; no C/C++ build compiler is required.

---

## 3. Configure Environment Variables

Copy `.env.example` to `.env` at the repository root (and/or `services/worker/.env` / `apps/studio/.env.local`):

```bash
cp .env.example .env
```

Minimum variables for **offline local development** (mocked AI providers):

```env
APP_ENV=development
DATABASE_URL=sqlite:///./local_dev.db
AUTH_JWT_SECRET=local-dev-jwt-secret-change-in-production-32bytes
SIGNED_URL_SECRET=local-dev-signed-url-secret-change-in-prod-32b
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
MOCK_VERTEX_VEO=true
MOCK_TTS=true
CELERY_ALWAYS_EAGER=true
INITIAL_PROMO_CREDITS=3
ENABLE_DEV_TOPUP=true
STORAGE_ROOT=./storage
WORKER_API_URL=http://127.0.0.1:8000
```

Minimum additions for **live AI & Stripe testing locally**:

1. Set `MOCK_VERTEX_VEO=false` and configure `GCP_PROJECT_ID`, `GCP_LOCATION`, `GCS_BUCKET`, and `GOOGLE_APPLICATION_CREDENTIALS` (or `VERTEX_ACCESS_TOKEN`).
2. Set `MOCK_TTS=false` and configure `GOOGLE_API_KEY` or `GOOGLE_APPLICATION_CREDENTIALS` (+ optional `GEMINI_API_KEY` for dynamic LLM localization).
3. Configure `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_STARTER_10`, `STRIPE_PRICE_GROWTH_50`, and `STRIPE_PRICE_SCALE_200`. Forward Stripe webhooks locally with the Stripe CLI:
   ```bash
   stripe listen --forward-to localhost:8000/v1/billing/webhooks/stripe
   ```

---

## 4. Database Initialization & Migrations

- **Local SQLite / Dev:** Starting the FastAPI worker automatically executes `init_db()` and `run_migrations()`, cleanly upgrading any legacy tables non-destructively.
- **PostgreSQL / Supabase:** Apply the SQL migrations in order before starting production instances:
  1. `services/worker/migrations/001_initial_schema.sql`
  2. `services/worker/migrations/002_saas_multi_tenant_auth_billing.sql`
  (Or inspect `schema.sql` for the complete consolidated schema + RLS policies.)

---

## 5. Run Services Locally

Open two terminals:

**Terminal 1 — FastAPI Video Worker (Port `8000`):**

```bash
cd services/worker
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2 — Next.js Creator Studio (Port `3000`):**

```bash
cd apps/studio
npm run dev
```

*(Optional Terminal 3 — Celery Worker when `CELERY_ALWAYS_EAGER=false` and Redis is running):*

```bash
cd services/worker
celery -A app.tasks.celery_app worker --loglevel=info
```

Open [http://localhost:3000](http://localhost:3000), click **Create Account**, and start testing multi-tenant workspaces, scraping, rendering, and MP4 downloads.

---

## 6. Run Test & Verification Suites

```bash
# Worker lint + pytest
cd services/worker
ruff check .
pytest -v

# Remotion template typecheck + lint
cd packages/remotion
npm run typecheck
npm run lint

# Creator Studio typecheck + lint + unit tests + production build
cd apps/studio
npm run typecheck
npm run lint
npm run test
npm run build
```
