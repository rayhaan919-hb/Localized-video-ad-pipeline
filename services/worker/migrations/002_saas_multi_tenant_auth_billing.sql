-- Migration 002: Multi-tenant authentication, workspace RBAC, private assets,
-- transactional credit ledger, and idempotent Stripe webhook accounting.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL DEFAULT '',
  is_email_verified BOOLEAN NOT NULL DEFAULT FALSE,
  email_verify_token_hash TEXT,
  email_verify_expires_at TIMESTAMPTZ,
  password_reset_token_hash TEXT,
  password_reset_expires_at TIMESTAMPTZ,
  failed_login_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  is_admin BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  refresh_token_hash TEXT NOT NULL UNIQUE,
  user_agent TEXT NOT NULL DEFAULT '',
  ip_address TEXT NOT NULL DEFAULT '',
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT 'Workspace';
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS reserved_balance INTEGER NOT NULL DEFAULT 0;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS promo_granted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS workspace_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS workspace_assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  asset_kind TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
  sha256 TEXT NOT NULL,
  storage_rel_path TEXT NOT NULL UNIQUE,
  source_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS aspect_ratio TEXT NOT NULL DEFAULT '9:16';
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS duration_seconds INTEGER NOT NULL DEFAULT 4;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS storage_rel_path TEXT;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS progress_pct INTEGER NOT NULL DEFAULT 0;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS stage_detail TEXT NOT NULL DEFAULT 'Queued';
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS error_code TEXT;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS reserved_credits INTEGER NOT NULL DEFAULT 1;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE video_jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS job_id UUID REFERENCES video_jobs(id) ON DELETE SET NULL;
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS payment_id TEXT;
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS transaction_type TEXT NOT NULL DEFAULT 'admin_adjustment';
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS amount INTEGER NOT NULL DEFAULT 0;
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS previous_balance INTEGER NOT NULL DEFAULT 0;
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS new_balance INTEGER NOT NULL DEFAULT 0;
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS balance_after INTEGER NOT NULL DEFAULT 0;
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE credit_ledger ADD COLUMN IF NOT EXISTS metadata_json JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_ledger_idempotency_key
  ON credit_ledger (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_video_jobs_workspace_idempotency_key
  ON video_jobs (workspace_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS stripe_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  stripe_event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  payment_intent_id TEXT,
  checkout_session_id TEXT,
  workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  pack_id TEXT,
  amount_cents INTEGER,
  currency TEXT,
  credits_delta INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'processed',
  payload_summary JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user_id ON workspace_members (user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_assets_workspace_id ON workspace_assets (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_jobs_workspace_created_at ON video_jobs (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_workspace_created_at ON credit_ledger (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stripe_events_payment_intent ON stripe_events (payment_intent_id);

-- Idempotent Row-Level Security (RLS) hardening across all public tables
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE stripe_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE video_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_ledger ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'auth' AND p.proname = 'uid'
  ) THEN
    CREATE OR REPLACE FUNCTION public.is_workspace_member(target_workspace_id UUID)
    RETURNS BOOLEAN
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $fn$
      SELECT EXISTS (
        SELECT 1
        FROM public.workspace_members wm
        WHERE wm.workspace_id = target_workspace_id
          AND wm.user_id = (SELECT auth.uid())
      );
    $fn$;

    CREATE OR REPLACE FUNCTION public.is_workspace_admin(target_workspace_id UUID)
    RETURNS BOOLEAN
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $fn$
      SELECT EXISTS (
        SELECT 1
        FROM public.workspace_members wm
        WHERE wm.workspace_id = target_workspace_id
          AND wm.user_id = (SELECT auth.uid())
          AND wm.role IN ('owner', 'admin')
      );
    $fn$;

    REVOKE ALL ON FUNCTION public.is_workspace_member(UUID) FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.is_workspace_admin(UUID) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.is_workspace_member(UUID) TO authenticated, service_role;
    GRANT EXECUTE ON FUNCTION public.is_workspace_admin(UUID) TO authenticated, service_role;

    DROP POLICY IF EXISTS workspaces_member_select ON workspaces;
    CREATE POLICY workspaces_member_select
      ON workspaces FOR SELECT
      USING (public.is_workspace_member(id));

    DROP POLICY IF EXISTS workspaces_owner_insert ON workspaces;
    CREATE POLICY workspaces_owner_insert
      ON workspaces FOR INSERT
      WITH CHECK ((SELECT auth.uid()) = owner_id);

    DROP POLICY IF EXISTS workspaces_admin_update ON workspaces;
    CREATE POLICY workspaces_admin_update
      ON workspaces FOR UPDATE
      USING (public.is_workspace_admin(id))
      WITH CHECK (public.is_workspace_admin(id));

    DROP POLICY IF EXISTS workspace_members_select ON workspace_members;
    CREATE POLICY workspace_members_select
      ON workspace_members FOR SELECT
      USING (public.is_workspace_member(workspace_id));

    DROP POLICY IF EXISTS workspace_members_admin_insert ON workspace_members;
    CREATE POLICY workspace_members_admin_insert
      ON workspace_members FOR INSERT
      WITH CHECK (public.is_workspace_admin(workspace_id));

    DROP POLICY IF EXISTS workspace_members_admin_update ON workspace_members;
    CREATE POLICY workspace_members_admin_update
      ON workspace_members FOR UPDATE
      USING (public.is_workspace_admin(workspace_id))
      WITH CHECK (public.is_workspace_admin(workspace_id));

    DROP POLICY IF EXISTS workspace_members_admin_delete ON workspace_members;
    CREATE POLICY workspace_members_admin_delete
      ON workspace_members FOR DELETE
      USING (public.is_workspace_admin(workspace_id));

    DROP POLICY IF EXISTS workspace_assets_member_all ON workspace_assets;
    CREATE POLICY workspace_assets_member_all
      ON workspace_assets FOR ALL
      USING (public.is_workspace_member(workspace_id))
      WITH CHECK (public.is_workspace_member(workspace_id));

    DROP POLICY IF EXISTS video_jobs_member_all ON video_jobs;
    CREATE POLICY video_jobs_member_all
      ON video_jobs FOR ALL
      USING (public.is_workspace_member(workspace_id))
      WITH CHECK (public.is_workspace_member(workspace_id));

    DROP POLICY IF EXISTS credit_ledger_member_select ON credit_ledger;
    CREATE POLICY credit_ledger_member_select
      ON credit_ledger FOR SELECT
      USING (public.is_workspace_member(workspace_id));
  END IF;
END
$$;
