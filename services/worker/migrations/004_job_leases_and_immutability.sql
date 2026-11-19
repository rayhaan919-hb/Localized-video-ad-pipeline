-- Migration 004: Worker leases, heartbeats, fencing tokens, correlation IDs,
-- credit_ledger immutability enforcement, and PostgreSQL FORCE ROW LEVEL SECURITY.

ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS worker_id TEXT;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS fencing_token INTEGER NOT NULL DEFAULT 0;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS correlation_id TEXT;

CREATE INDEX IF NOT EXISTS idx_video_jobs_status_lease
  ON video_jobs (status, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_video_jobs_correlation_id
  ON video_jobs (correlation_id);

-- Enforce strict immutability on financial ledger rows at PostgreSQL trigger level.
CREATE OR REPLACE FUNCTION public.prevent_credit_ledger_delete()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'credit_ledger rows are immutable and cannot be deleted';
END;
$$;

DROP TRIGGER IF EXISTS trg_credit_ledger_no_delete ON credit_ledger;
CREATE TRIGGER trg_credit_ledger_no_delete
  BEFORE DELETE ON credit_ledger
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_credit_ledger_delete();

-- Enforce RLS even for privileged/table-owner sessions unless explicitly bypassed.
ALTER TABLE schema_migrations FORCE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE stripe_events FORCE ROW LEVEL SECURITY;
ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;
ALTER TABLE workspace_members FORCE ROW LEVEL SECURITY;
ALTER TABLE workspace_assets FORCE ROW LEVEL SECURITY;
ALTER TABLE video_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY;

INSERT INTO schema_migrations (version)
VALUES ('004_job_leases_and_immutability')
ON CONFLICT (version) DO NOTHING;
