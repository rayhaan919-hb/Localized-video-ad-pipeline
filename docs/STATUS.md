# Project Status (`STATUS.md`)

**Project:** Localized AI Video Ad Pipeline (Non-English D2C SaaS)  
**Current Phase:** Phase 5 Independent Security & Quality Audit Complete (`/security-and-quality-audit` Verified)  
**Last Updated:** 2026-11-19  
**Latest Verified Code State:** Commit `c5628f0` + Creamy White / Green UI/UX refresh + Audit Hardening (`AUDIT-008`–`AUDIT-013` fixed & verified)  

---

## Done (Verified)
- **Phase 1–5 Hardening, QA Gate & Dependency Upgrade Complete:**
  - Multi-tenant auth (`PBKDF2-HMAC-SHA256`, HS256 JWT, rotating hashed refresh sessions with theft detection, lockout, reset/verify) + silent Studio `401` token refresh.
  - Strict workspace RBAC (`owner` / `admin` / `member`) + non-recursive `SECURITY DEFINER` Supabase RLS helpers + default-deny RLS on sensitive tables (`schema.sql`, `migrations/002`).
  - `RequestContextMiddleware` enforcing `X-Worker-API-Key`, body caps (`413`), unspoofable rate limits (`TRUST_PROXY_HEADERS=false`), and redacted JSON audit logs.
  - Transactional credit ledger with SQL `CASE` atomic safety, idempotency `IntegrityError` handling, `async_payment_succeeded`, cumulative partial refund accounting, and fail-closed prod validation.
  - SSRF-safe streaming HTML scraper & image validator, private workspace storage (`MAX_RENDERED_VIDEO_BYTES`), HMAC signed downloads, live `/health` DB + FFmpeg probes, Next.js security headers, and accessible/mobile-responsive UI modals.
  - Upgraded monorepo to React `19.3.1`, Next.js `16.4.6` (async `Promise` dynamic `params`), Remotion `4.0.545`, Tailwind CSS `4.3.5`, and PostCSS `8.5.33` (`npm audit --omit=dev` -> **`0 vulnerabilities`**).
- **Phase 2 UI/UX Design (`/ui-ux-design` Creamy White + Botanical Green Redesign) Complete & Verified:**
  - Authored [docs/DESIGN.md](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/docs/DESIGN.md) specifying the calm editorial visual direction, WCAG 2.2 AA palette (`#FAF7F2` creamy-white canvas, `#FFFFFF` cards, `#E6E0D5` borders, `#15803D` botanical-green pill CTAs with white text, `#166534` green icons/prices, `#1C1917` / `#57534E` / `#6E6A63` neutrals), rounded-pill radii scale (`full` / `xl` / `2xl` / `3xl`), and clutter-reduction architecture.
  - Updated `apps/studio/src/app/layout.tsx`, `apps/studio/src/app/globals.css` (`:focus-visible`, `@media (prefers-reduced-motion: reduce)`, rounded `.skip-link`, `.font-script-ur { line-height: 1.9 }`), and all 7 Studio components (`StudioWorkspace.tsx`, `StudioHeader.tsx`, `ProductScraperPanel.tsx`, `RemotionPreviewStage.tsx`, `RenderQueueGallery.tsx`, `CreditCheckoutModal.tsx`, `AuthModal.tsx`).
  - Reduced visual clutter via progressive disclosure (`Customize script, captions & promo` collapsible drawer), streamlined header (removed `VEO 3.1 + REMOTION`, `Renders X/Y` pill, and workspace hex IDs), removed duplicate `Live Preview` Generate button and 4-box telemetry wall, and hid raw GCS paths and inactive 4-step pipeline tracks on completed/failed video cards.
  - Kept full functionality and WCAG 2.2 AA safeguards: `onBlur` inline `<p role="alert">` validation preserving entered input, enlarged `32px`–`44px` targets, singular/plural copy (`1 video` / `2 Credits` / `3 transactions`), and soft-green rounded Nastaliq highlight pills (`30.5px` height, unclipped).
- **Phase 5 Security & Quality Audit (`/security-and-quality-audit`) Complete & Verified:**
  - Updated [docs/audit/AUDIT_REPORT.md](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/docs/audit/AUDIT_REPORT.md) with independent findings `AUDIT-008`–`AUDIT-015` (**0 open Critical, 0 open High, 0 open Medium**; 2 Low/Operational items documented).
  - Hardened Studio BFF ([serverStore.ts](file:///C:/Users/Admin/.gemini/antigravity/scratch/localized-video-ad-pipeline/apps/studio/src/lib/serverStore.ts), all 10 mutating routes, streaming media proxies, and `next.config.mjs`): stripped raw `access_token`/`refresh_token` from auth JSON (`HttpOnly` cookies preserved), enforced same-origin CSRF checks (`403` on cross-site/missing-Origin cookie mutations), validated dynamic UUID params, streamed MP4/asset responses with MIME whitelist + `nosniff` + sandbox headers, and added strict `Content-Security-Policy` & production `Strict-Transport-Security`.
  - Hardened FastAPI Worker (`services/worker/app/security.py`, `services/worker/app/main.py`): added bounded key eviction (`max_keys=10_000`) to `SlidingWindowRateLimiter`, enforced per-user rate limits on workspace create (`20/min`), member invites (`20/min`), and asset uploads (`30/min`), sanitized multipart `Content-Type` header encoding, and capped asset listings at 100 items.
- **Automated Verification:**
  - `services/worker`: `ruff check .` -> `All checks passed!`; `pytest -v` -> **`28 passed, 1 warning`** (after final Python security edits).
  - `packages/remotion`: `npm run verify:remotion` -> exit `0` (`tsc --noEmit` + `eslint --max-warnings 0`).
  - `apps/studio`: `npm run verify:studio` -> exit `0` (`tsc --noEmit` + `eslint --max-warnings 0` + **`7/7` node tests** + clean Next.js `16.4.6` Turbopack `next build`).
  - `npm audit --omit=dev` -> `found 0 vulnerabilities` (6 moderate dev-only `minimatch` advisories remain in ESLint tooling).
- **Live Browser Verification (`http://127.0.0.1:3000`, `NODE_ENV=production`):**
  - Multi-breakpoint verification (`1280x800`, `768x1024`, `375x812`, `320x568`) confirmed creamy-white `#FAF7F2`, green rounded `#15803D` pills, progressive disclosure, `onBlur` validation, zero horizontal overflow, and unclipped Nastaliq highlights.
  - Post-audit production CSP/CSRF/HttpOnly check (`1280x800`) confirmed `0` CSP violations, `0` console/page/hydration errors, `0` HTTP `>=500` responses, raw tokens stripped from `POST /api/v1/auth/register` (`HTTP 201`), Remotion playback, same-origin `POST /api/v1/videos/generate` (`HTTP 202`), streamed `GET /api/v1/renders/[jobId]` (`HTTP 200`, `77,386` bytes, `video/mp4`, `nosniff`), and Billing ledger (`2 Credits`, `3 transactions`).

## Next
- Commit and push all verified UI/UX + security audit changes on `main` (`docs/DESIGN.md`, `apps/studio/*`, `services/worker/*`, `docs/audit/AUDIT_REPORT.md`, `docs/STATUS.md`) alongside existing local commits when ready.
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
