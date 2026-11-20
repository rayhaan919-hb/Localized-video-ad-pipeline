# QA Bug Tracker (`BUGS.md`)

Tracked during the `/qa-gate` independent QA and security verification pass (`2026-11-19`, baseline commit `33a9948` + QA-gate fixes).

---

```text
BUG-001 [S1 critical]
Title: Missing WORKER_API_KEY middleware gate on /v1/*, spoofable X-Forwarded-For rate limits, and rendered MP4 size limit coupled to image upload limit
Steps to reproduce:
1. Configure WORKER_API_KEY in FastAPI worker and send unauthenticated request without X-Worker-API-Key to /v1/auth/me or /v1/videos.
2. Rotate arbitrary X-Forwarded-For headers across /v1/auth/login attempts without a trusted proxy.
3. Persist a >8 MB rendered_video MP4 artifact into private workspace storage.
Expected vs actual:
Expected: /v1/* (except Stripe webhook and signed download tokens) rejects missing/wrong X-Worker-API-Key, X-Forwarded-For is ignored unless TRUST_PROXY_HEADERS=true, and rendered videos use MAX_RENDERED_VIDEO_BYTES (100 MB) instead of image limit (8 MB).
Actual: Only unused auth dependency functions checked X-Worker-API-Key; get_client_ip() trusted client X-Forwarded-For unconditionally; register_workspace_file() applied MAX_ASSET_UPLOAD_BYTES to rendered MP4s.
Evidence: services/worker/app/security.py, config.py, storage.py; fixed & verified by pytest test_worker_api_key_enforcement_and_xff_spoof_protection and test_production_guards_video_limit_ssrf_and_stale_recovery.
Environment: branch main, baseline 33a9948, Python 3.12 pytest
Status: verified
```

```text
BUG-002 [S1 critical]
Title: API server startup runs recover_interrupted_jobs() with zero age threshold, killing active Celery jobs in multi-worker deployments
Steps to reproduce:
1. Deploy Redis + dedicated Celery worker alongside Uvicorn web API workers.
2. Restart or scale up a FastAPI web worker while another Celery worker is mid-render (PROCESSING / RENDERING).
3. FastAPI lifespan hook invokes recover_interrupted_jobs() without checking job staleness.
Expected vs actual:
Expected: Only stale interrupted jobs (e.g., updated_at older than 900s in async Redis mode) are recovered on API restart; eagerly executed dev tests recover immediately (min_age_seconds=0).
Actual: All PROCESSING/RENDERING jobs were marked FAILED/WORKER_INTERRUPTED and refunded immediately while still executing in Celery.
Evidence: services/worker/app/main.py lifespan() & services/worker/app/tasks.py recover_interrupted_jobs(); fixed & verified by test_production_guards_video_limit_ssrf_and_stale_recovery.
Environment: branch main, baseline 33a9948
Status: verified
```

```text
BUG-003 [S1 critical]
Title: Race condition between customer /cancel and Celery worker completion overwrite + non-atomic reserved_balance floor in db.py
Steps to reproduce:
1. Customer calls POST /v1/videos/{job_id}/cancel right before tasks.py commits status="COMPLETED".
2. Concurrent refund/deduction updates reserved_balance using stale ORM value check.
Expected vs actual:
Expected: Conditional SQL UPDATE ... WHERE status != 'CANCELLED' prevents a cancelled job from transitioning to COMPLETED and cleans up orphan file/asset; reserved_balance decrements use atomic SQL CASE >= 0 clamp.
Actual: Direct ORM attribute assignment after an earlier _is_job_cancelled check allowed a late cancel window and ORM-checked reserved_balance decrement.
Evidence: services/worker/app/tasks.py, services/worker/app/db.py (finalize_credit_deduction, refund_credit_atomically). Verified by full 27-test pytest pass.
Environment: branch main, baseline 33a9948
Status: verified
```

```text
BUG-004 [S2 high]
Title: /v1/videos/generate lacks upfront SSRF check before DB insert, fails 500 on concurrent idempotency race, and honors simulate_failure in production
Steps to reproduce:
1. Send POST /v1/videos/generate with product_url="http://127.0.0.1/internal" (reserves credit before worker catches UnsafeUrlError) or send parallel identical Idempotency-Key requests or simulate_failure=true under APP_ENV=production.
Expected vs actual:
Expected: Reject SSRF URLs with 400 upfront without reserving credit, catch IntegrityError on (workspace_id, idempotency_key) collision to return existing job cleanly, and reject/ignore simulate_failure when APP_ENV=production.
Actual: Credit was reserved and failed async; concurrent idempotent insert raised unhandled IntegrityError; simulate_failure remained honored in production.
Evidence: services/worker/app/main.py generate_video(), tasks.py; verified by test_production_guards_video_limit_ssrf_and_stale_recovery & test_idempotency_key_prevents_duplicate_charge.
Environment: branch main, baseline 33a9948
Status: verified
```

```text
BUG-005 [S2 high]
Title: AuthModal stays on prior tab when reopened via VERIFY button, dev verify token lost on close, and Billing modal table overflows mobile width
Steps to reproduce:
1. Register an account via Create Account tab -> AuthModal closes on success (hiding dev verification token).
2. Click header "VERIFY" button expecting Verify Email form.
3. Open "Buy Credits" modal at 375x812 mobile width.
Expected vs actual:
Expected: AuthModal syncs mode to initialMode on open (opening Verify Email), passes devVerifyToken into StudioWorkspace banner, supports Escape key close, and CreditCheckoutModal ledger wraps with overflow-x-auto cleanly inside 375px viewport.
Actual: AuthModal retained internal React mode state ('register'), discarded verify_email_token, had no Escape handler, and ledger table wrapper lacked overflow-x-auto.
Evidence: apps/studio/src/components/AuthModal.tsx, StudioWorkspace.tsx, CreditCheckoutModal.tsx; fixed & verified via live browser walkthrough on http://127.0.0.1:3000 at 1280x800 and 375x812 (table 540.85px scrolled inside 263.2px container, dialog 360px).
Environment: branch main (historical v2.0.0 baseline at `33a9948` upgraded to Next.js 16.4.6 / React 19.3.1 in subsequent release)
Status: verified
```

```text
BUG-006 [S2 high]
Title: services/worker/pyproject.toml omitted production PostgreSQL, Redis, and Google ADC driver extras
Steps to reproduce:
1. Install services/worker cleanly from pyproject.toml in a production container targeting postgresql://, redis://, and GCS ADC.
Expected vs actual:
Expected: A [prod] optional-dependencies group (psycopg[binary], redis, google-auth) is declared and documented in INSTALLATION.md and DEPLOYMENT.md.
Actual: Only SQLite/core HTTP packages were listed, causing ModuleNotFoundError unless installed ad-hoc.
Evidence: services/worker/pyproject.toml, DEPLOYMENT.md, INSTALLATION.md.
Environment: branch main, baseline 33a9948
Status: verified
```

```text
BUG-007 [S2 high]
Title: Stripe billing webhook ignored checkout.session.async_payment_succeeded and over-revoked credits on cumulative partial refunds
Steps to reproduce:
1. Deliver Stripe checkout.session.async_payment_succeeded event.
2. Deliver two cumulative partial charge.refunded events for a single 10-credit ($9.00) purchase: amount_refunded=450 followed by amount_refunded=900.
Expected vs actual:
Expected: async_payment_succeeded grants credits idempotently; partial refund #1 revokes 5 credits and cumulative partial refund #2 revokes the remaining 5 credits (10 total).
Actual: async_payment_succeeded was ignored as ignored_event_type; cumulative second partial refund calculated 900/900 = 10 credits again, revoking up to 15 credits total.
Evidence: services/worker/app/billing.py; fixed & verified by test_async_payment_succeeded_and_multiple_partial_refunds.
Environment: branch main, baseline 33a9948
Status: verified
```

```text
BUG-008 [S3 medium]
Title: Frontend lacked serialized silent refresh on 401 expiry and omitted confirmedMetadata in generate requests
Steps to reproduce:
1. Let short-lived 15-minute access cookie expire while StudioWorkspace polls /api/v1/videos and /credits simultaneously.
2. Confirm product facts manually after failed scrape and click Generate.
Expected vs actual:
Expected: Concurrent 401 responses share a single serialized POST /api/v1/auth/refresh call (avoiding refresh replay revocation) before retrying; generate sends confirmedMetadata so worker skips redundant fallback scrape.
Actual: Any 401 logged user out immediately; worker re-scraped product_url unnecessarily.
Evidence: apps/studio/src/components/StudioWorkspace.tsx, types/studio.ts, apps/studio/src/app/api/v1/videos/generate/route.ts; verified by apps/studio/src/__tests__/studio.test.ts.
Environment: branch main (historical v2.0.0 baseline upgraded to Next.js 16.4.6 / React 19.3.1 in subsequent release)
Status: verified
```

```text
BUG-009 [S3 medium]
Title: Dev UI State Inspector rendered in production builds, icon buttons lacked aria-label, compositor skipped font sanitization, and /health skipped live DB/FFmpeg probes
Steps to reproduce:
1. Run `next build && next start` and open Creator Studio header.
2. Inspect RefreshCw/LogOut/Copy-URL icon buttons, compositor ASS font header, and GET /health output.
Expected vs actual:
Expected: Dev inspector hidden when NODE_ENV === 'production', explicit aria-labels on icon buttons, ASS font sanitized cleanly, and /health checks live DB (`SELECT 1` returning 503 if unreachable) + FFmpeg availability.
Actual: UI State Inspector appeared in prod header, icon buttons had only `title`, /health did not probe DB or FFmpeg.
Evidence: StudioHeader.tsx, RenderQueueGallery.tsx, compositor.py, main.py; verified via live browser walkthrough + pytest test_production_guards_video_limit_ssrf_and_stale_recovery.
Environment: branch main, baseline 33a9948
Status: verified
```

```text
BUG-010 [S3 medium]
Title: Outbound SMTP / transactional email delivery not connected for production email verification & password reset tokens
Steps to reproduce:
1. Deploy with APP_ENV=production and call /v1/auth/register or /v1/auth/password-reset/request.
Expected vs actual:
Expected: Verification and password reset tokens are emailed to user via configured SMTP / transactional email service (tokens remain omitted from production HTTP responses).
Actual: Tokens are safely hashed and hidden from production API responses, but no SMTP/Resend transport is wired to send the email out-of-band yet.
Evidence: services/worker/app/main.py lines 388-390, 518-520 (token hidden when settings.is_production is True).
Environment: Production deployment configuration
Status: deferred (requires buyer transactional email / SMTP provider credentials; does not weaken auth security)
```
