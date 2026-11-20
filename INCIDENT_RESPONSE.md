# Incident Response Runbook

## Severity Classification

- **SEV-1 (Critical):** Payment/credit ledger imbalance, authentication bypass, active SSRF exploit, database outage, or Redis broker total outage.
- **SEV-2 (High):** Elevated job failure rates (`> 10%`), expired worker leases piling up, Vertex AI / Stripe degraded responses, or sustained `429` surge.
- **SEV-3 (Moderate):** Scraper upstream HTML layout changes or localized single-storefront failures.

---

## Diagnostic Checklist by Symptom

### 1. Customer Reports Failed Render / Missing Credit Refund
1. Obtain request or job correlation ID (`X-Request-ID` response header or `VideoJob.id`).
2. Inspect structured logs (`event=video_job_failed` or `event=video_job_retry_scheduled`) filtering by `request_id` or `job_id`.
3. Query workspace ledger reconciliation:
   ```bash
   curl -H "Authorization: Bearer <token>" \
     https://<worker>/v1/workspaces/<ws_id>/credits/reconcile
   ```
4. If `is_balanced: false` (never expected under normal operation), halt manual adjustments, capture `credit_ledger` rows for `<ws_id>`, and check pending `reservation` rows.

### 2. Jobs Stuck in `QUEUED` or `PROCESSING`
1. Check `/health` and `/v1/ops/metrics` (with `X-Admin-Secret`):
   - If `redis_broker: false`, restore Redis connectivity immediately; API safely returns `HTTP 503` without silently corrupting state.
   - If `queue.queue_depth` climbs while `jobs.active_leases == 0`, verify Celery worker containers are running (`celery -A app.tasks.celery_app inspect ping`).
   - If `jobs.expired_leases > 0`, run recovery manually:
     ```bash
     python -c "from app.tasks import recover_interrupted_jobs; print(recover_interrupted_jobs(min_age_seconds=120))"
     ```

### 3. Suspected Refresh Token Theft or Account Compromise
1. Call `POST /v1/auth/logout-all` (or revoke directly via user ID `revoke_all_user_sessions`).
2. Rotate `AUTH_JWT_SECRET` if platform-wide key exposure is suspected (invalidates all active access JWTs immediately).
3. Review `worker_api_key_rejected`, `workspace_access_denied`, and `user_logged_out_all` structured audit logs.

### 4. Stripe Webhook Discrepancies or Out-of-Order Events
1. Inspect `stripe_events` rows by `payment_intent_id` and `stripe_event_id`.
2. Out-of-order refunds recorded as `refund_without_matching_purchase` are automatically reconciled when `checkout.session.completed` arrives (`status = refund_processed_out_of_order`).
3. Replaying any missed signed webhook from Stripe Dashboard is safe and idempotent (`stripe_events.stripe_event_id` unique constraint + `credit_ledger.idempotency_key`).

### 5. Emergency Rollback Procedure
1. Stop incoming traffic / place load balancer in maintenance mode if a bad schema or app deploy causes `5xx` spikes.
2. Redeploy the previous known-good container tag (code rollback).
3. Because schema migrations (`002`, `003`, `004`, `005`) strictly add nullable/defaulted columns, additive outbox tables, and non-breaking indexes/triggers, the prior minor code version remains backward-compatible with added columns; restore DB snapshot only if data corruption occurred.
