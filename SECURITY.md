# Security Architecture & Vulnerability Disclosure

This document details the security controls enforced across **Localized AI Video Ad Pipeline** and known upstream dependency considerations.

---

## 1. Multi-Tenant Authentication & Session Management

- **Password Storage**: Salted `PBKDF2-HMAC-SHA256` (`260,000` iterations, `hashlib.pbkdf2_hmac`) compared in constant time via `hmac.compare_digest` (`services/worker/app/auth.py`).
- **Access & Refresh Tokens**:
  - Access JWTs use HMAC-SHA256 (`HS256`) with strict `exp`/`iat`/`sub` checks; supports optional verification of Supabase JWTs via `SUPABASE_JWT_SECRET`.
  - Refresh tokens are `secrets.token_urlsafe(48)` stored hashed (SHA-256) in `auth_sessions`. Every refresh rotates the token and revokes the previous row. Replaying a revoked refresh token immediately revokes all active sessions for that user.
  - Auth tokens are delivered via `HttpOnly; SameSite=Lax` cookies (`Secure=true` when `APP_ENV=production`) as well as JSON responses for programmatic API clients.
- **Brute-Force & Distributed Rate Limiting**:
  - Account-level lockout (`AUTH_LOCKOUT_MAX_ATTEMPTS`, default 5 failed logins locks for 15 minutes); active lockouts also reject existing JWT access tokens (`HTTP 403`) in `get_current_user()`.
  - `POST /v1/auth/logout-all` revokes every active refresh session across devices.
  - Redis-backed distributed sliding-window rate limiter (`DistributedRateLimiter`) using atomic Lua counters shared across all API instances (with burst protection and separate configurable limits for login, registration, password reset, video generation, retries, scraping, downloads, and billing checkout), returning `HTTP 429` with `Retry-After` and `X-RateLimit-*` headers.

---

## 2. Multi-Tenant Workspace Isolation & RBAC

- **Zero Default Shared Tenant**: Removed `DEFAULT_WORKSPACE_ID` (`00000000-0000-0000-0000-000000000001`), `DEFAULT_OWNER_ID`, and all automatic shared workspace seeding across both `services/worker` and `apps/studio`.
- **Membership Enforcement**: Every protected workspace, job, billing, asset, and download endpoint invokes `require_workspace_role(db, workspace_id=..., user=current_user, minimum_role=...)`. `DELETE /v1/workspaces/{id}/members/{uid}` forbids removing workspace owners or allowing non-owners to remove admins.
- **Database Row-Level Security (RLS)**: [schema.sql](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/schema.sql) and migrations `002` + `004` enable and `FORCE ROW LEVEL SECURITY` across `schema_migrations`, `users`, `auth_sessions`, `stripe_events`, `workspaces`, `workspace_members`, `workspace_assets`, `video_jobs`, and `credit_ledger`.

---

## 3. Billing & Stripe Webhook Security

- **Server-Authoritative Pricing**: `POST /v1/workspaces/{id}/credits/checkout` accepts only `pack_id` (`starter_10`, `growth_50`, `scale_200`); Stripe price IDs (`STRIPE_PRICE_*`) and credit amounts are resolved exclusively on the server.
- **Signature & Replay Protection**: `POST /v1/billing/webhooks/stripe` verifies the raw HTTP body against `Stripe-Signature` HMAC-SHA256 (`v1` signature) with a 300-second timestamp tolerance window.
- **Idempotency, Out-of-Order Reconciliation & Ledger Immutability**: Processed `event.id` records are committed in `stripe_events` via unique constraint, out-of-order `charge.refunded` events arriving prior to `checkout.session.completed` are automatically reconciled upon purchase settlement, ORM + SQL triggers (`trg_credit_ledger_no_delete`) prevent deleting/tampering with `credit_ledger` rows, and `GET /v1/workspaces/{id}/credits/reconcile` verifies ledger-to-balance invariants.
- **Restricted Adjustments**: `POST /v1/workspaces/{id}/credits/dev-topup` returns HTTP `403` whenever `APP_ENV=production` or `ENABLE_DEV_TOPUP!=true`; `admin-adjust` requires platform admin authorization or `X-Admin-Secret`.

---

## 4. Private Media Storage, Signed URLs & SSRF Defense

- **Private Storage Containment**: Rendered videos and uploaded images reside strictly under `STORAGE_ROOT/workspaces/{workspace_id}/...` with path traversal containment (`resolve_workspace_rel_path`). The legacy unauthenticated `/static/renders` mount and Studio's synthetic MP4 buffer fallback have been removed completely.
- **Time-Limited Signed URLs**: `GET /v1/videos/{job_id}/signed-url` signs `(job_id, workspace_id, exp)` using HMAC-SHA256 (`SIGNED_URL_SECRET`).
- **Connection-Pinned SSRF Defense**: `services/worker/app/scraper.py` blocks private, loopback, link-local (`169.254.169.254`), CGNAT (`100.64.0.0/10`), IPv6 loopback/mapped (`::1`, `::ffff:127.0.0.1`), obfuscated numeric/hex/octal IPs, internal ports, embedded credentials, and revalidates every redirect hop (`max 5`), using `SSRFSafeNetworkBackend` to pin validated global IPs directly into `httpcore` socket connect (`connect_tcp`) and defeat DNS rebinding TOCTOU. Outbound fetches enforce explicit timeouts, wall-clock duration limits (`12s`), `Accept-Encoding: identity` + byte caps, and Content-Type checks.
- **Upload Magic-Byte Validation**: Uploaded product assets validate magic signatures (`PNG`, `JPEG`, `WebP`, `GIF`) and cap payload size cleanly (`MAX_REQUEST_BODY_BYTES`, `MAX_UPLOAD_IMAGE_BYTES`).

---

## 5. Logging, Error Sanitization & Fail-Closed Startup

- `RequestContextMiddleware` (`services/worker/app/security.py`) attaches `X-Request-ID` headers, enforces request body caps (`413`), and structured JSON audit logs redact sensitive keys (`password`, `token`, `secret`, `authorization`, `cookie`, `stripe_signature`, `api_key`).
- `validate_production_config()` blocks production startup if mocks are active, SQLite is selected, `WORKER_API_KEY` or signing secrets are weak/missing, or wildcard CORS (`*`) is set.

---

## 6. Dependency Audit Status (`npm audit --omit=dev`)

Following the monorepo upgrade to `react@19.3.1`, `react-dom@19.3.1`, `next@16.4.6`, `postcss@8.5.33`, and `remotion@4.0.545` / `@remotion/player@4.0.545`:

- **Production Dependencies (`npm audit --omit=dev`):** **`found 0 vulnerabilities`** (0 critical, 0 high, 0 moderate, 0 low).
- **Development Dependencies:** 6 moderate advisories remain on `minimatch` inside `@typescript-eslint` v7 lint tooling (not bundled into production runtime artifacts).
- **Continuous Hygiene:** Keep scheduled `pip-audit` and `npm audit --omit=dev` checks active in CI prior to releases.
