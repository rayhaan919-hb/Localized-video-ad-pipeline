# Backup and Recovery Policy

## 1. PostgreSQL Database Backups
- **Primary Financial & Tenant State:** `users`, `auth_sessions`, `workspaces`, `workspace_members`, `credit_ledger`, `stripe_events`, `video_jobs`, `workspace_assets`, and `schema_migrations`.
- **Automated Schedule (Production Requirement):**
  - Continuous Point-in-Time Recovery (PITR) WAL archiving enabled (Supabase Pro / Managed PostgreSQL).
  - Encrypted daily logical snapshot (`pg_dump --format=custom --no-owner --no-acl`) retained for at least `30` days in a separate region/bucket.

```bash
# Example encrypted logical backup command
pg_dump "$DATABASE_URL" --format=custom --no-owner --no-acl \
  -f "backup-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

## 2. Private Workspace Storage (`STORAGE_ROOT` & `GCS_BUCKET`)
- Workspace uploads and completed MP4 artifacts stored under `STORAGE_ROOT/workspaces/<workspace_id>/...` must reside on persistent block/object storage (e.g., GCS bucket / attached persistent volume with bucket versioning enabled).
- Raw Veo clips under `GCS_BUCKET/workspaces/<workspace_id>/jobs/<job_id>/` should have lifecycle retention policies aligned with customer retention terms (e.g. `90` days for raw intermediates, persistent storage for final rendered MP4s).

## 3. Restore Verification Drill
1. Restore the latest `pg_dump` into an isolated staging database (never overwrite production directly).
2. Run migration verification (`services/worker/migrations/004_job_leases_and_immutability.sql`).
3. Run workspace ledger integrity check across all workspaces:
   - Verify `credit_balance == SUM(credit_ledger.delta)` via `reconcile_workspace_credits()`.
4. Run `recover_interrupted_jobs()` before opening worker traffic so any in-flight jobs captured during a crash backup cleanly refund pending reservations once.

## 4. Recovery Objectives
- **RPO (Data Loss Tolerance):** `<= 5 minutes` with managed PostgreSQL PITR (up to last daily snapshot if WAL archiving is not used).
- **RTO (Restoration Time):** `< 30 minutes` for database restore + stateless API/worker container redeploy.
- **Note:** Because Redis stores ephemeral queue messages and sliding-window rate-limit counters (all credit holds and job states live authoritatively in PostgreSQL), a total Redis loss recovers cleanly via DB lease expiration + `recover_interrupted_jobs()` without financial discrepancy.
