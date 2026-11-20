-- Migration 005: Transactional dispatch outbox for durable job queuing
-- and explicit `TO authenticated` RLS policy scoping across tenant tables.

CREATE TABLE IF NOT EXISTS job_dispatch_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL UNIQUE REFERENCES video_jobs(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  payload_json JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
    status IN ('PENDING', 'PUBLISHING', 'PUBLISHED', 'FAILED', 'CANCELLED')
  ),
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_error TEXT,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_dispatch_outbox_status_next
  ON job_dispatch_outbox (status, next_attempt_at);

ALTER TABLE job_dispatch_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_dispatch_outbox FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    DROP POLICY IF EXISTS workspaces_member_select ON workspaces;
    CREATE POLICY workspaces_member_select
      ON workspaces FOR SELECT
      TO authenticated
      USING (public.is_workspace_member(id));

    DROP POLICY IF EXISTS workspaces_owner_insert ON workspaces;
    CREATE POLICY workspaces_owner_insert
      ON workspaces FOR INSERT
      TO authenticated
      WITH CHECK ((SELECT auth.uid()) = owner_id);

    DROP POLICY IF EXISTS workspaces_admin_update ON workspaces;
    CREATE POLICY workspaces_admin_update
      ON workspaces FOR UPDATE
      TO authenticated
      USING (public.is_workspace_admin(id))
      WITH CHECK (public.is_workspace_admin(id));

    DROP POLICY IF EXISTS workspace_members_select ON workspace_members;
    CREATE POLICY workspace_members_select
      ON workspace_members FOR SELECT
      TO authenticated
      USING (public.is_workspace_member(workspace_id));

    DROP POLICY IF EXISTS workspace_members_admin_insert ON workspace_members;
    CREATE POLICY workspace_members_admin_insert
      ON workspace_members FOR INSERT
      TO authenticated
      WITH CHECK (public.is_workspace_admin(workspace_id));

    DROP POLICY IF EXISTS workspace_members_admin_update ON workspace_members;
    CREATE POLICY workspace_members_admin_update
      ON workspace_members FOR UPDATE
      TO authenticated
      USING (public.is_workspace_admin(workspace_id))
      WITH CHECK (public.is_workspace_admin(workspace_id));

    DROP POLICY IF EXISTS workspace_members_admin_delete ON workspace_members;
    CREATE POLICY workspace_members_admin_delete
      ON workspace_members FOR DELETE
      TO authenticated
      USING (public.is_workspace_admin(workspace_id));

    DROP POLICY IF EXISTS workspace_assets_member_all ON workspace_assets;
    CREATE POLICY workspace_assets_member_all
      ON workspace_assets FOR ALL
      TO authenticated
      USING (public.is_workspace_member(workspace_id))
      WITH CHECK (public.is_workspace_member(workspace_id));

    DROP POLICY IF EXISTS video_jobs_member_all ON video_jobs;
    CREATE POLICY video_jobs_member_all
      ON video_jobs FOR ALL
      TO authenticated
      USING (public.is_workspace_member(workspace_id))
      WITH CHECK (public.is_workspace_member(workspace_id));

    DROP POLICY IF EXISTS credit_ledger_member_select ON credit_ledger;
    CREATE POLICY credit_ledger_member_select
      ON credit_ledger FOR SELECT
      TO authenticated
      USING (public.is_workspace_member(workspace_id));
  END IF;
END
$$;

INSERT INTO schema_migrations (version)
VALUES ('005_transactional_outbox_and_rls_hardening')
ON CONFLICT (version) DO NOTHING;
