# Database Migrations & Schema Hardening

## Migration Architecture

The authoritative PostgreSQL schema lives in [`schema.sql`](./schema.sql), backed by idempotent SQL migration files in `services/worker/migrations/` and automatic startup enforcement in [`services/worker/app/migrations.py`](./services/worker/app/migrations.py).

| Version | File | Key Schema Changes |
| :--- | :--- | :--- |
| `001_initial_schema` | [`001_initial_schema.sql`](./services/worker/migrations/001_initial_schema.sql) | Initial legacy single-tenant `workspaces`, `video_jobs`, `credit_ledger`. |
| `002_saas_multi_tenant_auth_billing` | [`002_saas_multi_tenant_auth_billing.sql`](./services/worker/migrations/002_saas_multi_tenant_auth_billing.sql) | Adds `users`, `auth_sessions`, `workspace_members`, `workspace_assets`, `stripe_events`, idempotency unique partial indexes, RLS policies, and `SECURITY DEFINER` helpers. |
| `003_google_oauth_identity` | [`003_google_oauth_identity.sql`](./services/worker/migrations/003_google_oauth_identity.sql) | Adds `users.auth_provider`, `users.google_sub`, and partial unique index `idx_users_google_sub_unique`. |
| `004_job_leases_and_immutability` | [`004_job_leases_and_immutability.sql`](./services/worker/migrations/004_job_leases_and_immutability.sql) | Adds `worker_id`, `lease_expires_at`, `heartbeat_at`, `fencing_token`, and `correlation_id` to `video_jobs`; adds `trg_credit_ledger_no_delete` immutability trigger (`BEFORE DELETE ON credit_ledger`); applies `FORCE ROW LEVEL SECURITY` on all PostgreSQL tables. |
| `005_transactional_outbox_and_rls_hardening` | [`005_transactional_outbox_and_rls_hardening.sql`](./services/worker/migrations/005_transactional_outbox_and_rls_hardening.sql) | Adds `job_dispatch_outbox` (`ENABLE` + `FORCE ROW LEVEL SECURITY`) with `idx_job_dispatch_outbox_status_next`, and scopes tenant RLS policies explicitly `TO authenticated`. |

---

## Safe Production Migration Procedure

1. **Take a Snapshot First:** Capture a PostgreSQL snapshot / `pg_dump` before executing schema migrations (see [`BACKUP_AND_RECOVERY.md`](./BACKUP_AND_RECOVERY.md)).
2. **Apply Versioned SQL Scripts (PostgreSQL / Supabase):**
   Execute migrations strictly in numeric order (`001` -> `002` -> `003` -> `004` -> `005`), or apply [`schema.sql`](./schema.sql) via `psql` or Supabase SQL Editor:
   ```bash
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f services/worker/migrations/002_saas_multi_tenant_auth_billing.sql
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f services/worker/migrations/003_google_oauth_identity.sql
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f services/worker/migrations/004_job_leases_and_immutability.sql
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f services/worker/migrations/005_transactional_outbox_and_rls_hardening.sql
   ```
3. **Verify Applied Migrations, Forces & Indexes:**
   ```sql
   SELECT version, applied_at FROM schema_migrations ORDER BY applied_at;
   SELECT relname, relrowsecurity, relforcerowsecurity
   FROM pg_class JOIN pg_namespace n ON n.oid = pg_class.relnamespace
   WHERE n.nspname = 'public' AND relkind = 'r';
   ```
   Confirm `005_transactional_outbox_and_rls_hardening` is present and both `relrowsecurity` & `relforcerowsecurity` are `true` on `users`, `auth_sessions`, `stripe_events`, `workspaces`, `workspace_members`, `workspace_assets`, `video_jobs`, `credit_ledger`, `job_dispatch_outbox`, and `schema_migrations`.
4. **Runtime Safety Net (`init_db()`):**
   On application startup, `run_migrations()` inspects existing columns cleanly via SQLAlchemy Inspector and adds missing columns/indexes non-destructively without dropping existing rows.

---

## Financial & Multi-Tenant Invariants

- **Immutability:** Both the SQLAlchemy ORM layer (`@event.listens_for(CreditLedger, "before_delete" | "before_update")`), `ON DELETE RESTRICT` foreign key on `credit_ledger.workspace_id`, and database triggers (`trg_credit_ledger_no_delete`) prevent deletion or post-write tampering of `credit_ledger` amounts, deltas, or balances. Only `reservation` status transitions (`pending` -> `completed` or `refunded`) are permitted.
- **Row-Level Security:** PostgreSQL `schema.sql`, `004`, and `005` enforce `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` across all public tables with explicit `TO authenticated` policies, delegating membership checks to non-recursive `SECURITY DEFINER` functions (`public.is_workspace_member`, `public.is_workspace_admin`) with `PUBLIC` execution revoked. Always verify application/PostgREST database roles use `NOBYPASSRLS` (`pg_roles.rolbypassrls = false`).
- **Connection Pooling (`db.py`):** Non-SQLite engines configure `pool_pre_ping=True`, `pool_size=DB_POOL_SIZE` (default `10`), `max_overflow=DB_MAX_OVERFLOW` (`20`), `pool_timeout=DB_POOL_TIMEOUT` (`30s`), and `pool_recycle=DB_POOL_RECYCLE` (`1800s`).
