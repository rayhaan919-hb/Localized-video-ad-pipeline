# Security Architecture & Vulnerability Disclosure

This document details the security controls enforced across **Localized AI Video Ad Pipeline** and known upstream dependency considerations.

---

## 1. Multi-Tenant Authentication & Session Management

- **Password Storage**: Salted `PBKDF2-HMAC-SHA256` (`260,000` iterations, `hashlib.pbkdf2_hmac`) compared in constant time via `hmac.compare_digest` (`services/worker/app/auth.py`).
- **Access & Refresh Tokens**:
  - Access JWTs use HMAC-SHA256 (`HS256`) with strict `exp`/`iat`/`sub` checks; supports optional verification of Supabase JWTs via `SUPABASE_JWT_SECRET`.
  - Refresh tokens are `secrets.token_urlsafe(48)` stored hashed (SHA-256) in `auth_sessions`. Every refresh rotates the token and revokes the previous row. Replaying a revoked refresh token immediately revokes all active sessions for that user.
  - Auth tokens are delivered via `HttpOnly; SameSite=Lax` cookies (`Secure=true` when `APP_ENV=production`) as well as JSON responses for programmatic API clients.
- **Brute-Force & Rate Limiting**:
  - Account-level lockout (`AUTH_LOCKOUT_MAX_ATTEMPTS`, default 5 failed logins locks for 15 minutes).
  - Sliding-window per-IP / per-subject rate limiter (`SlidingWindowRateLimiter`) returning `429 Too Many Requests` with `Retry-After` on `/v1/auth/*`, `/v1/products/scrape`, and `/v1/videos/generate`.

---

## 2. Multi-Tenant Workspace Isolation & RBAC

- **Zero Default Shared Tenant**: Removed `DEFAULT_WORKSPACE_ID` (`00000000-0000-0000-0000-000000000001`), `DEFAULT_OWNER_ID`, and all automatic shared workspace seeding across both `services/worker` and `apps/studio`.
- **Membership Enforcement**: Every protected workspace, job, billing, asset, and download endpoint invokes `require_workspace_role(db, workspace_id=..., user=current_user, minimum_role=...)`.
- **Database Row-Level Security (RLS)**: `schema.sql` and `services/worker/migrations/002_saas_multi_tenant_auth_billing.sql` enable PostgreSQL RLS across `workspaces`, `workspace_members`, `workspace_assets`, `video_jobs`, and `credit_ledger`.

---

## 3. Billing & Stripe Webhook Security

- **Server-Authoritative Pricing**: `POST /v1/workspaces/{id}/credits/checkout` accepts only `pack_id` (`starter_10`, `growth_50`, `scale_200`); Stripe price IDs (`STRIPE_PRICE_*`) and credit amounts are resolved exclusively on the server.
- **Signature & Replay Protection**: `POST /v1/billing/webhooks/stripe` verifies the raw HTTP body against `Stripe-Signature` HMAC-SHA256 (`v1` signature) with a 300-second timestamp tolerance window.
- **Idempotency & Dispute Handling**: Processed `event.id` records are committed in `stripe_events` via unique primary key constraint so duplicate deliveries cannot double-credit a workspace. `charge.refunded` and `charge.dispute.created` create offsetting ledger debits.
- **Restricted Adjustments**: `POST /v1/workspaces/{id}/credits/dev-topup` returns HTTP `403` whenever `APP_ENV=production` or `ENABLE_DEV_TOPUP!=true`; `admin-adjust` requires platform admin authorization or `X-Admin-Secret`.

---

## 4. Private Media Storage, Signed URLs & SSRF Defense

- **Private Storage Containment**: Rendered videos and uploaded images reside strictly under `STORAGE_ROOT/workspaces/{workspace_id}/...` with path traversal containment (`resolve_workspace_rel_path`). The legacy unauthenticated `/static/renders` mount and Studio's synthetic MP4 buffer fallback have been removed completely.
- **Time-Limited Signed URLs**: `GET /v1/videos/{job_id}/signed-url` signs `(job_id, workspace_id, exp)` using HMAC-SHA256 (`SIGNED_URL_SECRET`).
- **SSRF Blocklist**: `services/worker/app/scraper.py` validates hostnames, resolved IPv4/IPv6 addresses, and every HTTP redirect hop against private, loopback, link-local (`169.254.169.254`), reserved, and multicast ranges.
- **Upload Magic-Byte Validation**: Uploaded product assets validate magic signatures (`PNG`, `JPEG`, `WebP`, `GIF`) and cap payload size cleanly (`MAX_REQUEST_BODY_BYTES`, `MAX_UPLOAD_IMAGE_BYTES`).

---

## 5. Logging, Error Sanitization & Fail-Closed Startup

- `RequestContextMiddleware` (`services/worker/app/security.py`) attaches `X-Request-ID` headers, enforces request body caps (`413`), and structured JSON audit logs redact sensitive keys (`password`, `token`, `secret`, `authorization`, `cookie`, `stripe_signature`, `api_key`).
- `validate_production_config()` blocks production startup if mocks are active, SQLite is selected, `WORKER_API_KEY` or signing secrets are weak/missing, or wildcard CORS (`*`) is set.

---

## 6. Known Upstream Dependency Advisories (Disclosed)

Running `npm audit --omit=dev` against `apps/studio` after patching `next` from `14.2.25` to `14.2.35` reports upstream advisories whose remediations require major-version upgrades outside the current React 18 / `@remotion/player@4.0.242` lock:

1. **`next@14.2.35` & nested `postcss`**: Advisories list fixes only in Next.js `16.x` (React 19 breaking upgrade). Mitigation notes: Studio enables zero Server Actions, configures no `next/image` `remotePatterns` image optimization proxy, uses App Router BFF handlers rather than middleware rewrites, and sits behind TLS reverse proxy controls; plan a dedicated React 19 + Next 15/16 + Remotion 4.0.410+ upgrade milestone prior to exposing self-hosted Next.js directly on Windows or untrusted public traffic.
2. **`remotion@4.0.242` / `@remotion/player@4.0.242`**: Upstream audit lists advisories for `<=4.0.409` fixed in `>=4.0.410` (Studio currently runs only `@remotion/player` client-side composition preview with trusted props; server-side video compositing in `services/worker` uses direct validated FFmpeg subprocess arguments, not untrusted Remotion CLI server rendering).
3. **`fast-xml-parser` / Python advisories**: Keep scheduled `pip-audit` and `npm audit` gates active in CI before production releases.
