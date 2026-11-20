# API Documentation

This document describes all backend **FastAPI Worker** (`/v1/*`) endpoints (`services/worker/app/main.py`) and corresponding **Next.js Studio BFF Proxy** (`/api/v1/*`) routes (`apps/studio/src/app/api/v1/`).

---

## Authentication & Authorization Model

- **User Identity**: Short-lived JWT Bearer token (`Authorization: Bearer <token>`) or `HttpOnly` cookie `lva_access_token` verified on every protected endpoint via `get_current_user`.
- **Refresh Sessions**: `HttpOnly` cookie `lva_refresh_token` or JSON `refresh_token` rotated on `/v1/auth/refresh`; replaying a rotated token revokes all sessions for that user.
- **Internal Service Key**: When `WORKER_API_KEY` is configured (mandatory in production), callers to protected worker routes must pass `X-Worker-API-Key: <WORKER_API_KEY>`.
- **Workspace RBAC Hierarchy**: `owner > admin > member`. Every workspace, video, billing checkout, and asset operation validates server-side membership against `workspace_members`.
- **Standard Error Codes**:
  - `401 Unauthorized` — Missing/invalid/expired JWT or worker service key
  - `402 Payment Required` — Insufficient workspace credit balance to reserve 1 credit
  - `403 Forbidden` — Authenticated user lacks membership or required role in workspace
  - `404 Not Found` — Resource does not exist
  - `409 Conflict` — Duplicate email/member or invalid state transition (e.g., cancelling a `COMPLETED` job)
  - `413 Payload Too Large` — Request exceeds `MAX_REQUEST_BODY_BYTES`
  - `429 Too Many Requests` — Brute-force login lockout or rate limit exceeded (includes `Retry-After`)
  - `503 Service Unavailable` — Required external provider (Stripe/Veo/TTS/Worker) misconfigured or unreachable

---

## 1. System Health & Observability

### `GET /health`
Returns service diagnostics without exposing secrets:
- `status`: `"ok"` or `"degraded"`
- `app_env`, `database_dialect`, `database_connected`
- `ffmpeg_available`, `ffprobe_available`
- `mock_vertex_veo`, `mock_tts`
- `worker_api_key_required`, `stripe_configured`
- `queue_health` (`redis_broker`, `celery_eager_mode`, `require_redis_broker`)

### `GET /v1/ops/metrics` (`X-Admin-Secret` or platform admin JWT)
Returns operational counters, stage latencies (`stage.*`), `rate_limiter.backend_mode`, `database` stats (`db_clock`), `queue_health` (with Celery ping inspection), `outbox` state counts, and recent job failure breakdown. Every response echoes `X-Request-ID`.

---

## 2. Authentication (`/v1/auth/*` | BFF: `/api/v1/auth/*`)

| Method | Path | Auth Required | Description |
|---|---|---|---|
| `GET` | `/v1/auth/providers` | Public | Advertise available auth modes (`password`, `google_oauth_enabled`, email verification flag). |
| `POST` | `/v1/auth/register` | Public (rate-limited) | Register user, create primary workspace, optionally grant server-configured promo credits (`INITIAL_PROMO_CREDITS`), issue verification token & JWT + refresh cookies. |
| `POST` | `/v1/auth/login` | Public (rate-limited + lockout) | Authenticate email/password, issue JWT + refresh cookies. Locks after `AUTH_LOCKOUT_MAX_ATTEMPTS`. |
| `POST` | `/v1/auth/refresh` | Refresh Token | Rotate refresh session token and detect replay reuse. |
| `POST` | `/v1/auth/logout` | Optional | Revoke refresh session and clear auth cookies. |
| `POST` | `/v1/auth/logout-all` | JWT | Revoke all active refresh sessions across every device for caller. |
| `GET` | `/v1/auth/me` | JWT | Return authenticated user profile and list of authorized workspaces with roles & balances. |
| `POST` | `/v1/auth/verify-email` | Token | Verify user email using issued verification token. |
| `POST` | `/v1/auth/password-reset/request` | Public (rate-limited) | Issue single-use time-limited password reset token hash. |
| `POST` | `/v1/auth/password-reset/confirm` | Token | Set new password and revoke all active refresh sessions. |
| `GET` | `/v1/auth/google/start` | Public | Initiate Google OAuth 2.0 Authorization Code + PKCE (`S256`) flow with HMAC-signed state cookie. |
| `POST` | `/v1/auth/google/callback` | Public | Exchange authorization code + PKCE verifier, link/provision verified Google user, issue session cookies. |

---

## 3. Workspaces & Members (`/v1/workspaces/*` | BFF: `/api/v1/workspaces/*`)

| Method | Path | Min Role | Description |
|---|---|---|---|
| `GET` | `/v1/workspaces` | User | List workspaces where authenticated user is a member. |
| `POST` | `/v1/workspaces` | User | Create a new workspace owned by the caller (starts with `0` credits; never auto-grants promotional credits). |
| `GET` | `/v1/workspaces/{workspace_id}` | `member` | Return workspace balances, member roster, and last 50 immutable `credit_ledger` entries. |
| `POST` | `/v1/workspaces/{workspace_id}/members` | `admin` (`owner` to grant `admin`) | Invite/add an existing registered user to workspace with role `member` or `admin`. |
| `PATCH` | `/v1/workspaces/{workspace_id}/members/{member_user_id}` | `owner` | Change an existing member's role. |
| `DELETE` | `/v1/workspaces/{workspace_id}/members/{member_user_id}` | `admin` (`owner` for admin removal) | Remove a member from workspace while protecting workspace owners and enforcing RBAC hierarchy. |
| `GET` | `/v1/workspaces/{workspace_id}/credits/reconcile` | `member` | Verify workspace balance/reserved totals against immutable `credit_ledger` entries (`is_balanced`). |

---

## 4. Private Workspace Assets (`/v1/workspaces/{id}/assets`, `/v1/assets/{id}`)

| Method | Path | Min Role | Description |
|---|---|---|---|
| `POST` | `/v1/workspaces/{workspace_id}/assets` | `member` | Upload & validate PNG/JPEG/WebP/GIF product image via `multipart/form-data`, raw binary (`X-Filename`), or JSON `{ filename, content_base64 }`. Stored in private workspace storage with SHA-256 checksum. |
| `GET` | `/v1/workspaces/{workspace_id}/assets` | `member` | List workspace-scoped uploaded assets. |
| `GET` | `/v1/assets/{asset_id}` | `member` | Download private asset bytes after workspace membership verification. |

---

## 5. Credit Billing, Stripe Checkout & Webhooks

| Method | Path | Auth / Min Role | Description |
|---|---|---|---|
| `GET` | `/v1/billing/packages` | Public | List server-defined credit packs (`starter_10`, `growth_50`, `scale_200`) and USD pricing. |
| `POST` | `/v1/workspaces/{workspace_id}/credits/checkout` | `member` | Create server-side Stripe Checkout Session for `{ pack_id, success_url?, cancel_url? }`. Client prices/amounts/credit counts are not accepted. Returns `{ checkout_url, session_id }`. |
| `POST` | `/v1/billing/webhooks/stripe` | `Stripe-Signature` HMAC | Verify raw-body Stripe HMAC signature + replay timestamp tolerance, deduplicate by `event.id` (`stripe_events`), and atomically credit/reverse workspace balances on verified events. |
| `POST` | `/v1/workspaces/{workspace_id}/credits/admin-adjust` | Platform Admin (`is_admin` or `X-Admin-Secret`) | Audited operator adjustment `{ delta, reason }`. Returns `403` for ordinary workspace owners/members. |
| `POST` | `/v1/workspaces/{workspace_id}/credits/dev-topup` | `member` + Dev-Only Guard | Explicitly blocked (`403`) whenever `APP_ENV=production` or `ENABLE_DEV_TOPUP!=true`. |

---

## 6. Product Storefront Scraper (`/v1/products/scrape`)

- **Request**: `{ "product_url": "https://...", "target_language": "ur" | "ar" | "hi" | "en" }`
- **Protection**: Rejects loopback, RFC1918 private networks, link-local / cloud metadata IPs (`169.254.169.254`, `metadata.google.internal`), and validates every HTTP redirect hop (`SSRF`).
- **Response (`200`)**:
  - `scrape_status`: `"verified"` | `"partial"` | `"unreachable"`
  - `title`, `brand`, `price`, `original_price`, `discount_badge`, `currency`, `features`, `image_url`, `image_candidates`
  - `verified_fields`: list of fields extracted cleanly from OpenGraph/JSON-LD/HTML
  - `missing_fields`: list of required fields not found on page
  - `requires_user_confirmation`: `true` whenever factual fields are unverified/incomplete (zero fabricated fallbacks)

---

## 7. Video Generation, Status, Cancellation, Retry & Private Downloads

| Method | Path | Min Role / Auth | Description |
|---|---|---|---|
| `POST` | `/v1/videos/generate` | `member` | Supports `Idempotency-Key` header. Atomically reserves `1` credit and queues video job in status `CREATED` -> `QUEUED` -> `PROCESSING` -> `RENDERING` -> `COMPLETED` / `FAILED`. Accepts `aspect_ratio` (`"9:16"` or `"16:9"`), `duration_seconds`, `target_language`, `ad_angle`, and `custom_props`. |
| `GET` | `/v1/videos` | User (scoped to member workspaces) | List up to 100 jobs belonging strictly to authenticated caller's workspaces (optionally filtered by `?workspace_id=...` after RBAC verification). |
| `GET` | `/v1/videos/{job_id}` | `member` | Retrieve single job status, stage progress, and error telemetry if workspace-authorized. |
| `POST` | `/v1/videos/{job_id}/cancel` | `member` | Cancel non-terminal job and atomically refund reserved credit. |
| `POST` | `/v1/videos/{job_id}/retry` | `member` | Re-dispatch a `FAILED` or `CANCELLED` job as a new queued job. |
| `GET` | `/v1/videos/{job_id}/signed-url` | `member` | Issue short-lived HMAC-signed download URL path (`/v1/videos/{id}/download?token=...`) for a `COMPLETED` video. |
| `GET` | `/v1/videos/{job_id}/download` | `member` OR valid `?token=...` | Stream validated MP4 bytes from private workspace storage after verifying workspace membership or signed HMAC token + path-traversal containment. |

> **BFF Download Proxy**: Studio exposes `GET /api/v1/renders/{jobId}` (supporting session cookies and optional `?token=...`) which proxies strictly to `/v1/videos/{jobId}/download` with no unauthenticated or synthetic MP4 fallback.
