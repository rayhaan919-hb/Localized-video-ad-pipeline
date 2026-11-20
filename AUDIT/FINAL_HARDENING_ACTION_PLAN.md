# Final Production Hardening Action Plan & Revalidation

**Branch:** `production-final-hardening` (branched from `main` at `259c3f1`)  
**Date:** `2026-11-20`  
**Baseline Test Run:** `pytest -v` in `services/worker` -> **`36 passed, 1 warning`** (`0` failed, `0` skipped)

---

## 1. Revalidation Summary

All 5 items identified for final commercial hardening were independently revalidated against live code, CI workflows, manifests, documentation, and local toolchains. **All 5 issues are confirmed present** in the `259c3f1` baseline and targeted in this branch without rewriting sound architecture.

---

## 2. Detailed Revalidated Findings & Action Plan

### Finding 1 — Queued Jobs Can Be Incorrectly Failed as Abandoned (`P1`)
- **Status:** **CONFIRMED**
- **Severity:** **P1 (Customer Data & Credit Loss Under Queue Congestion)**
- **Affected Files:**
  - `services/worker/app/tasks.py` (`recover_interrupted_jobs()`, lines `1013–1090`)
  - `services/worker/app/main.py` (`generate_video()`, lines `1559–1660`)
  - `services/worker/app/db.py`, `schema.sql`, `services/worker/app/migrations.py`
- **Root Cause:**
  1. `recover_interrupted_jobs()` includes `"CREATED"`, `"QUEUED"`, and `"PENDING"` inside `in_flight_statuses`. Because queued jobs have `worker_id IS NULL` and `lease_expires_at IS NULL`, any queued job waiting longer than `min_age_seconds` falls into the unleased `else:` branch and is forcibly transitioned to `FAILED` (`WORKER_INTERRUPTED`) with its credit refunded — even while its Celery task message remains legitimately waiting in Redis under queue congestion.
  2. `generate_video()` commits `VideoJob(status="QUEUED")` and calls `dispatch_video_job()` in a separate post-commit call without a durable transactional outbox. An API crash or transient network blip right after `db.commit()` leaves an orphaned `CREATED`/`QUEUED` row with no dispatch record.
- **Proposed Fix:**
  1. Separate queued-job handling from active-worker lease recovery: exclude `"CREATED"`, `"QUEUED"`, and `"PENDING"` from `recover_expired_leases()` / `recover_interrupted_jobs()`. Only active execution states (`PROCESSING`, `RENDERING`, `GENERATING_CLIPS`, `COMPOSITING`) are eligible for abandoned-worker recovery.
  2. Add migration `005_transactional_outbox_and_rls_hardening.sql` introducing `job_dispatch_outbox` (`JobDispatchOutbox`) written atomically in the same DB transaction as `VideoJob(status="CREATED")` and `reserve_credit_atomically()`. Implement idempotent `publish_outbox_event()` and `reconcile_dispatch_outbox()` so queued messages never execute on already-`FAILED`/`CANCELLED` jobs and transient broker glitches retry safely without corrupting customer jobs.
  3. Require `acquire_job_lease()` to ignore already-terminal jobs (`COMPLETED`/`FAILED`/`CANCELLED`), ensuring stale queued messages in Redis skip cleanly without touching state or credits.
- **Required Regression Tests (`services/worker/tests/test_queued_and_lease_races.py`):**
  - Queued job waiting longer than recovery threshold (`min_age_seconds=0` and `min_age_seconds=60`) stays `QUEUED`.
  - Heavy queue congestion (`10` queued jobs + repeated recovery runs) preserves all queued jobs.
  - Transient Redis outage during outbox relay reschedules backoff without losing/failing job, then dispatches cleanly when Redis recovers; exhausted outbox retries fail cleanly and refund once.
  - Old Celery message arriving after `FAILED`/`CANCELLED`, duplicate delivery, and worker starting right after recovery scan.

---

### Finding 2 — Race Condition Between Worker Heartbeat Renewal, Cancellation & Job Recovery (`P1`)
- **Status:** **CONFIRMED**
- **Severity:** **P1 (Split-Brain Ownership & Corrupted State Transitions)**
- **Affected Files:**
  - `services/worker/app/tasks.py` (`recover_interrupted_jobs()`, lines `1037–1093`; `_fenced_transition()`, completion/failure `UPDATE`s)
  - `services/worker/app/db.py` (`acquire_job_lease()`, `renew_job_lease()`, `release_job_lease()`, lines `966–1063`)
  - `services/worker/app/main.py` (`cancel_video_job()`, lines `1744–1760`)
- **Root Cause:**
  1. `recover_interrupted_jobs()` evaluates `lease_expires_at <= now` in Python (`utcnow()`) after reading ORM rows, then runs an unconditional `UPDATE` gated only on `(id, status, fencing_token)`. If the live worker's `_LeaseHeartbeatThread` calls `renew_job_lease()` between the read and commit, `fencing_token` does not change on renewal (`db.py:1011–1038`), so recovery overwrites the freshly renewed lease and fails an actively running job.
  2. `renew_job_lease()` checks `worker_id == worker_id AND fencing_token == fencing_token` without verifying `lease_expires_at > db_now` or restricting `status` strictly to active execution states, permitting a paused worker to revive an expired lease after recovery has read it.
  3. Lease checks rely on Python `utcnow()` instead of database server time (`clock_timestamp()` on PostgreSQL / `strftime('%Y-%m-%d %H:%M:%f', 'now')` on SQLite), risking skew across multi-host API/worker nodes.
  4. `acquire_job_lease()` allows `or_(..., VideoJob.worker_id == worker_id)` even when a lease is unexpired, permitting same-worker duplicate delivery overlap before completion.
  5. `cancel_video_job()` uses non-atomic ORM attribute assignment without compare-and-swap or `fencing_token` increment, creating a cancel-vs-complete race.
- **Proposed Fix:**
  1. Introduce dialect-aware database-clock expressions `db_now_expr(session)` and `db_offset_expr(session, offset_seconds)` in `services/worker/app/db.py`.
  2. Rewrite `recover_expired_leases()` to execute an atomic per-job compare-and-swap `UPDATE` checking ALL of: `status IN ACTIVE_EXECUTION_STATUSES`, `worker_id == observed_worker_id`, `fencing_token == observed_token`, `lease_expires_at IS NOT NULL`, `lease_expires_at <= db_now_expr(session)` (plus `FOR UPDATE SKIP LOCKED` on PostgreSQL candidate reads). Refund only when `rowcount == 1`.
  3. Rewrite `renew_job_lease()` to enforce `status IN ACTIVE_EXECUTION_STATUSES AND lease_expires_at IS NOT NULL AND lease_expires_at > db_now_expr(session)` in the SQL `WHERE` clause so expired or recovered leases can never be revived.
  4. Tighten `acquire_job_lease()` to prevent claiming already-leased active jobs while incrementing `fencing_token` atomically (`CASE WHEN status IN QUEUED_STATUSES THEN 'PROCESSING' ELSE status END`), and convert `cancel_video_job()` + pending outbox cancellation to atomic CAS + `fencing_token + 1`.
- **Required Regression Tests:**
  - Sequential & barrier-synchronized concurrent tests in `test_queued_and_lease_races.py` and real PostgreSQL concurrency tests in `test_postgres_integration.py` covering heartbeat before/during/after recovery, expired lease renewal rejection, competing workers, dual recovery workers, stale worker completion fencing, and cancel vs complete races.

---

### Finding 3 — Deprecated Node.js 20 GitHub Actions & Missing Live Service CI (`P2`)
- **Status:** **CONFIRMED**
- **Severity:** **P2 (CI/CD Runner Deprecation & Integration Blind Spot)**
- **Affected Files:**
  - `.github/workflows/ci.yml`
  - `services/worker/pyproject.toml`
- **Root Cause:**
  1. `.github/workflows/ci.yml` pins `actions/checkout@v4`, `actions/setup-python@v5`, and `actions/setup-node@v4` (Node.js 20 runner execution), rather than current Node 24-compatible SHA-pinned releases (`v6.1.0`, `v6.3.0`, `v6.5.0`).
  2. CI has no job provisioning live `postgres:16-alpine` and `redis:7-alpine` service containers to run real PostgreSQL RLS/concurrency and Redis/Celery recovery tests on every push/PR.
- **Proposed Fix:**
  - Upgrade workflow actions in `.github/workflows/ci.yml` to verified commit SHAs:
    - `actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0`
    - `actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0`
    - `actions/setup-node@249970729cb0ef3589644e2896644e2896645e5dc # v6.5.0`
  - Add `postgres-redis-integration` job running `test_postgres_integration.py` and `test_redis_celery_recovery.py` against live `postgres:16-alpine` and `redis:7-alpine`, plus static type checking (`mypy` / `uvx mypy`) where appropriate.
- **Required Regression Checks:**
  - Inspect resolved git SHAs, verify workflow YAML structure, and confirm local + CI execution parity.

---

### Finding 4 — Documentation Drift & Broken Local Filesystem Links (`P2`)
- **Status:** **CONFIRMED**
- **Severity:** **P2 (Developer Onboarding & Operator Documentation Defect)**
- **Affected Files:**
  - `README.md`, `INSTALLATION.md`, `API_DOCUMENTATION.md`, `DEPLOYMENT.md`, `PRODUCTION_READINESS_REPORT.md`, `DESIGN.md`
  - `DATABASE_MIGRATIONS.md`, `DEPLOYMENT_GUIDE.md`, `PRODUCTION_READINESS.md`, `SECURITY.md`, `TESTING_GUIDE.md`, `docs/STATUS.md`, `AUDIT/FINAL_PRODUCTION_READINESS_REPORT.md`, `BACKGROUND_JOBS.md`, `ENVIRONMENT_VARIABLES.md`, `MONITORING.md`, `INCIDENT_RESPONSE.md`, `CHANGELOG.md`
- **Root Cause:**
  1. Legacy docs still reference `Next.js 14.2.35` (`README.md`), dark-mode `#09090B` styling (`README.md`, `DESIGN.md`), old test counts (`27/27`, `5/5` in `PRODUCTION_READINESS_REPORT.md`), Node `20.x` (`INSTALLATION.md`), and only migrations `001`–`002` (`INSTALLATION.md`, `DEPLOYMENT.md`).
  2. `API_DOCUMENTATION.md` lacks newer routes (`/v1/ops/metrics`, `/v1/auth/logout-all`, Google OAuth routes, `DELETE` workspace member, `/credits/reconcile`).
  3. Seven markdown files contain developer-local Windows filesystem links unusable by teammates on clean checkouts.
- **Proposed Fix:**
  - Synchronize all root, worker, and operational docs against verified package manifests (`next@^16.4.6`, `react@^19.3.1`, `remotion@4.0.545`, `tailwindcss@^4.3.5`, `node v22`), schema migrations (`001`–`005`), actual executed test results, and real UI/architecture.
  - Replace every local Windows filesystem link across all repo `.md` files with repository-relative markdown links (`./...`, `../...`), and verify zero broken relative links remain.

---

### Finding 5 — Unverified Real PostgreSQL, Redis/Celery, Stripe, GCP & Staging Load Tests (`P1`)
- **Status:** **CONFIRMED (Environment Gated Locally)**
- **Severity:** **P1 (Launch Gate Verification Requirement)**
- **Affected Environment & Files:**
  - Local workstation lacks `docker`, `psql`, `redis-server`, `stripe`, active GCP ADC (`gcloud auth list` empty), and valid staging DB credentials (`supabase_mcp` DB queries return `28P01`).
  - `services/worker/tests/test_postgres_integration.py` (missing)
  - `services/worker/tests/test_redis_celery_recovery.py` (missing)
  - `services/worker/tests/test_staging_integrations.py` (missing — needs real Stripe test-mode & GCP Veo/TTS/GCS staging harnesses)
  - `services/worker/scripts/run_staging_benchmarks.py` (missing — needs multi-tier Postgres/Redis/Celery benchmark suite)
- **Proposed Fix:**
  1. Author full executable PostgreSQL (including real `NOBYPASSRLS` role testing + `clock_timestamp()` concurrency tests), Redis+Celery multi-process crash/recovery, Stripe test-mode, GCP Veo/TTS/GCS staging tests, and multi-tier `run_staging_benchmarks.py`.
  2. Wire PostgreSQL 16 + Redis 7 suites into `.github/workflows/ci.yml` so they run automatically in GitHub Actions.
  3. Execute every local security (`uvx pip-audit`, `npm audit --omit=dev`), static (`ruff`, `uvx mypy`, `tsc`, `eslint`), build (`next build`), SQLite/unit/concurrency test, local dry-run benchmark, and full browser E2E customer journey locally; mark unexecuted external credentialed tests transparently as **`NOT VERIFIED`** in `AUDIT/PRODUCTION_TEST_RESULTS.md` and `AUDIT/FINAL_READINESS_SCORECARD.md`.

---

## 3. Planned Branch Commit Sequence (`production-final-hardening`)

1. `docs(audit): add final production hardening revalidation action plan`
2. `fix(jobs): separate queued-job recovery and add transactional dispatch outbox`
3. `fix(leases): make lease heartbeat, cancellation, and recovery atomic with DB clock`
4. `ci: upgrade GitHub Actions to Node 24 SHA pins and add Postgres/Redis integration job`
5. `test: add PostgreSQL RLS/concurrency, Redis/Celery recovery, and staging integration suites`
6. `docs: synchronize technical documentation and replace local filesystem links`
7. `docs(audit): add final hardening report, test results, deployment checklist, and scorecard`
