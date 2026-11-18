# Project Status (`STATUS.md`)

**Project:** Localized AI Video Ad Pipeline (Non-English D2C SaaS)  
**Current Phase:** Phase 4 & 5 Complete (`/qa-gate` Verification & Audit Completed)  
**Last Updated:** 2026-11-19  
**Latest Verified Code State:** Commit `749b41e` + React `19.3.1` / Next.js `16.4.6` / Remotion `4.0.545` upgrade (`AUDIT-007` resolved)  

---

## Done (Verified)
- **Phase 1–5 Hardening, QA Gate & Dependency Upgrade Complete:**
  - Multi-tenant auth (`PBKDF2-HMAC-SHA256`, HS256 JWT, rotating hashed refresh sessions with theft detection, lockout, reset/verify) + silent Studio `401` token refresh.
  - Strict workspace RBAC (`owner` / `admin` / `member`) + non-recursive `SECURITY DEFINER` Supabase RLS helpers + default-deny RLS on sensitive tables (`schema.sql`, `migrations/002`).
  - `RequestContextMiddleware` enforcing `X-Worker-API-Key`, body caps (`413`), unspoofable rate limits (`TRUST_PROXY_HEADERS=false`), and redacted JSON audit logs.
  - Transactional credit ledger with SQL `CASE` atomic safety, idempotency `IntegrityError` handling, `async_payment_succeeded`, cumulative partial refund accounting, and fail-closed prod validation.
  - SSRF-safe streaming HTML scraper & image validator, private workspace storage (`MAX_RENDERED_VIDEO_BYTES`), HMAC signed downloads, live `/health` DB + FFmpeg probes, Next.js security headers, and accessible/mobile-responsive UI modals.
  - Upgraded monorepo to React `19.3.1`, Next.js `16.4.6` (async `Promise` dynamic `params`), Remotion `4.0.545`, Tailwind CSS `4.3.5`, and PostCSS `8.5.33` (`npm audit --omit=dev` -> **`0 vulnerabilities`**).
- **Automated Verification:**
  - `services/worker`: `ruff check .` -> `All checks passed!`; `pytest -v` -> `27 passed, 1 warning` (all security, concurrency, Stripe, SSRF, prod-guard, 4-language MP4 & validation cases).
  - `packages/remotion`: `npm run verify:remotion` -> exit `0` (`tsc --noEmit` + `eslint --max-warnings 0`).
  - `apps/studio`: `npm run verify:studio` -> exit `0` (`tsc --noEmit` + `eslint --max-warnings 0` + `5/5` node tests + clean Next.js `16.4.6` Turbopack `next build`).
  - `npm audit --omit=dev` -> `found 0 vulnerabilities`.
- **Live Browser Walkthrough (`http://127.0.0.1:3000`):**
  - Desktop (`1280x800`) & Mobile (`375x812`) full flow verified cleanly, plus React 19 + Next.js `16.4.6` + Remotion `4.0.545` live playback (`00/60 -> 50/60`), async dynamic API routes, UR/AR/HI/EN switching, MP4 render (`3 -> 2` credits), ledger modal, and sign-out with 0 console/hydration errors.

## Next
- Push local `main` commits (`749b41e` + React 19 upgrade commit) to `origin/main` when ready.
- Provision buyer cloud credentials (`DATABASE_URL` Postgres 15+, `GCP_PROJECT_ID`/`GCS_BUCKET`/ADC, live `STRIPE_*` keys, transactional SMTP) and run final cloud live smoke test (`Phase 6`).

## Known Gaps / Deferred Blockers
1. **External Cloud Live Smoke Tests:** Vertex AI Veo 3.1, Google Cloud TTS, live Stripe webhooks, and Supabase Postgres RLS policy execution were tested via SQL/HTTP mocks, local SQLite, and local FFmpeg binaries (live buyer cloud accounts not present in workspace).
2. **`BUG-010` (Transactional Email Transport):** Email verification and password reset tokens are suppressed cleanly in production API responses (`APP_ENV=production`) and require wiring to a buyer SMTP/email provider (e.g. Resend/Postmark) for self-serve onboarding.
3. **Python Dependency CVE Scan (`pip-audit`):** Not completed in this pass; keep scheduled `pip-audit` and `npm audit` gates active in CI before production releases.

## How to Run Locally
1. **Worker (`services/worker`):**
   - Configure `.env` with `APP_ENV=development`, `MOCK_VERTEX_VEO=true`, `MOCK_TTS=true`, `CELERY_ALWAYS_EAGER=true`.
   - Start API: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
2. **Studio (`apps/studio`):**
   - Run dev (`npm run dev`) or production build (`npm run build; npx next start -H 127.0.0.1 -p 3000`) with `WORKER_API_URL=http://127.0.0.1:8000` and matching `WORKER_API_KEY`.
