# Environment Variables Reference

All runtime settings are loaded by Pydantic (`services/worker/app/config.py`) and Next.js server-only BFF helpers (`apps/studio/src/lib/serverStore.ts`). Never expose `[SERVER-ONLY]` variables in `NEXT_PUBLIC_*` keys.

---

## 1. Core Application & Database

| Variable | Required in Prod | Default (`dev`) | Description |
| :--- | :---: | :--- | :--- |
| `APP_ENV` | Yes (`production`) | `development` | Environment mode (`development`, `test`, `staging`, `production`). Enables fail-closed startup validation in `production`. |
| `DATABASE_URL` | Yes (PostgreSQL) | Local SQLite fallback in dev | `postgresql://...` (or `postgres://...`). SQLite is forbidden when `APP_ENV=production`. |
| `DB_POOL_SIZE` | No | `10` | SQLAlchemy PostgreSQL connection pool size (`_build_engine`). |
| `DB_MAX_OVERFLOW` | No | `20` | Additional overflow connections beyond `DB_POOL_SIZE`. |
| `DB_POOL_TIMEOUT` | No | `30` | Seconds to wait before timing out on pool exhaustion. |
| `DB_POOL_RECYCLE` | No | `1800` | Connection recycle interval in seconds (mitigates stale firewall/DB connections). |

---

## 2. Authentication, OAuth & Security Secrets

| Variable | Required in Prod | Default | Description |
| :--- | :---: | :--- | :--- |
| `AUTH_JWT_SECRET` | Yes (`>= 32` chars) | Ephemeral dev secret | HS256 signing secret for access tokens and HMAC OAuth state cookies (`build_google_oauth_start`). |
| `SIGNED_URL_SECRET` | Yes (or via JWT secret) | Falls back to `AUTH_JWT_SECRET` | HMAC secret signing short-lived `/v1/videos/{id}/download` tokens. |
| `WORKER_API_KEY` | Yes (`>= 24` chars) | Optional in dev | Shared internal key (`X-Worker-API-Key`) required between Next.js BFF and FastAPI worker. |
| `ADMIN_ADJUST_SECRET` | Recommended | `""` | Header secret (`X-Admin-Secret`) for platform admin credit adjustments and `/v1/ops/metrics`. |
| `CORS_ORIGINS` | Yes (explicit origins) | `http://localhost:3000` | Comma-separated allowed origins. Wildcard `*` is rejected in `production`. |
| `FRONTEND_APP_URL` | Yes | `http://localhost:3000` | Public Studio origin used for OAuth callbacks, verification links, and Stripe redirect validation. |
| `TRUST_PROXY_HEADERS` | Behind reverse proxy | `false` | When `true`, `get_client_ip()` reads the rightmost proxy-appended `X-Forwarded-For` IP. |
| `REQUIRE_EMAIL_VERIFICATION` | Yes (`true`) | `true` (`false` in `APP_ENV=test`) | Blocks unverified password logins (`403`) and gates initial session issuance until verified. |
| `EXPOSE_DEV_AUTH_TOKENS` | Must be `false` | `false` (`true` in `APP_ENV=test`) | Hard-disabled in `production` regardless of env value. |
| `GOOGLE_OAUTH_CLIENT_ID` | For Google login | `""` | Google OAuth 2.0 Web Client ID for Authorization Code + PKCE `S256`. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | For Google login | `""` | Google OAuth 2.0 Client Secret. |
| `GOOGLE_OAUTH_REDIRECT_URI` | Optional override | `{FRONTEND_APP_URL}/api/v1/auth/google/callback` | Registered Google OAuth redirect URI. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS` | Recommended | `""` / `587` / `true` | Outbound SMTP credentials used by `send_verification_email()`. |

---

## 3. Background Jobs, Redis Broker & Worker Leases

| Variable | Required in Prod | Default | Description |
| :--- | :---: | :--- | :--- |
| `REDIS_URL` | Yes (`redis://` or `rediss://`) | `redis://localhost:6379/0` | Mandatory Celery broker, result backend, and distributed rate-limit store in `production`. |
| `CELERY_ALWAYS_EAGER` | **Forbidden (`false`)** | `false` (or `true` in `.env.example` local) | Strictly forbidden in `production`. `validate_production_config()` aborts startup if enabled. |
| `REQUIRE_REDIS_BROKER` | Implicit `true` in prod | `false` | When `true`, `/v1/videos/generate` fails closed with `HTTP 503` if Redis is unreachable. |
| `REQUIRE_ACTIVE_CELERY_WORKER` | Recommended | `false` | When `true`, verifies active Celery worker ping via `inspect().ping()` before queueing. |
| `JOB_LEASE_DURATION_SECONDS` | No | `120` | Worker lease duration before an unrenewed job becomes eligible for crash recovery. |
| `JOB_HEARTBEAT_INTERVAL_SECONDS` | No | `30` | Interval at which `_LeaseHeartbeatThread` extends `lease_expires_at` and `heartbeat_at`. |
| `JOB_UNCLAIMED_GRACE_SECONDS` | No | `120` | Grace window for legacy/unleased queued jobs during startup recovery. |
| `JOB_SOFT_TIME_LIMIT_SECONDS` | No | `300` | Celery soft execution limit (`SoftTimeLimitExceeded`, treated as transient). |
| `JOB_HARD_TIME_LIMIT_SECONDS` | No | `360` | Celery hard kill limit (`SIGKILL`) protecting worker pool capacity. |
| `JOB_MAX_RETRIES` | No | `3` | Maximum automatic retries for transient failures using exponential backoff + jitter. |
| `JOB_RETRY_BASE_DELAY_SECONDS` | No | `2.0` | Base delay in seconds for retry backoff. |
| `JOB_RETRY_MAX_DELAY_SECONDS` | No | `60.0` | Maximum retry backoff cap in seconds. |

---

## 4. Rate Limiting & Resource Limits

| Variable | Default (`req/min`) | Scope |
| :--- | :---: | :--- |
| `RATE_LIMIT_LOGIN_PER_MINUTE` | `15` | `/v1/auth/login` (falls back to `RATE_LIMIT_AUTH_PER_MINUTE` if customized) |
| `RATE_LIMIT_REGISTER_PER_MINUTE` | `10` | `/v1/auth/register` |
| `RATE_LIMIT_PASSWORD_RESET_PER_MINUTE` | `10` | `/v1/auth/password-reset/*` |
| `RATE_LIMIT_GENERATE_PER_MINUTE` | `30` | `/v1/videos/generate` (with burst protection) |
| `RATE_LIMIT_RENDER_RETRY_PER_MINUTE` | `20` | `/v1/videos/{job_id}/retry` |
| `RATE_LIMIT_SCRAPE_PER_MINUTE` | `60` | `/v1/products/scrape` (with burst protection) |
| `RATE_LIMIT_DOWNLOAD_PER_MINUTE` | `120` | `/v1/videos/{job_id}/download`, `/signed-url`, `/v1/assets/{asset_id}` |
| `RATE_LIMIT_BILLING_PER_MINUTE` | `20` | `/v1/workspaces/{id}/credits/checkout` |
| `RATE_LIMIT_BURST_WINDOW_SECONDS` | `10` | Short-window burst evaluation interval |
| `MAX_REQUEST_BODY_BYTES` | `10485760` (10 MiB) | Request body limit enforced in `RequestContextMiddleware` |
| `MAX_ASSET_UPLOAD_BYTES` | `8388608` (8 MiB) | Maximum uploaded/fetched product image size |
| `MAX_RENDERED_VIDEO_BYTES` | `104857600` (100 MiB) | Maximum rendered MP4 size persisted in workspace storage |

---

## 5. Stripe Billing, Google Cloud AI & Storage

| Variable | Required in Prod | Default | Description |
| :--- | :---: | :--- | :--- |
| `STRIPE_SECRET_KEY` | Yes | `""` | Server-only Stripe API secret key (`sk_test_*` in staging, `sk_live_*` in prod). |
| `STRIPE_WEBHOOK_SECRET` | Yes | `""` | Webhook HMAC signing secret (`whsec_*`). |
| `STRIPE_PRICE_STARTER_10`, `STRIPE_PRICE_GROWTH_50`, `STRIPE_PRICE_SCALE_200` | Yes for checkout | `""` | Server-authoritative Stripe Price IDs per credit pack. |
| `INITIAL_PROMO_CREDITS` | Configured (`0` in prod) | `3` | Free signup credits granted once per newly registered user workspace. |
| `ENABLE_DEV_TOPUP` | Must be `false` | `false` | Hard-disabled when `APP_ENV=production`. |
| `MOCK_VERTEX_VEO`, `MOCK_TTS` | **Must be `false`** | `false` | Forbidden in `production`. |
| `GCP_PROJECT_ID`, `GCS_BUCKET`, `VERTEX_LOCATION` | Yes | `""` / `us-central1` | Vertex AI Veo project, regional endpoint, and GCS bucket URI (`gs://...`). |
| `GOOGLE_APPLICATION_CREDENTIALS` / `VERTEX_ACCESS_TOKEN` / `GOOGLE_API_KEY` | Yes (at least 1) | `""` | Google Cloud authentication for Vertex AI Veo 3.1 and Cloud TTS v1. |
| `STORAGE_ROOT` | Yes | `services/worker/storage` | Private local/mounted storage directory for workspace assets and rendered MP4s. |

---

## 6. Next.js Studio BFF (`apps/studio`)

| Variable | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| `WORKER_API_URL` | Yes | `http://127.0.0.1:8000` | Internal network URL of the FastAPI worker (server-side only). |
| `WORKER_API_KEY` | Yes in prod | `""` | Matches FastAPI `WORKER_API_KEY`; sent by BFF via `X-Worker-API-Key`. |
