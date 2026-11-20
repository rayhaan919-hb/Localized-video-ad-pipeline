-- Authoritative PostgreSQL / Supabase SaaS schema for Localized AI Video Ad Pipeline.
-- Note: Runtime upgrades and SQLite test support are handled idempotently by
-- services/worker/app/migrations.py and versioned SQL files under services/worker/migrations/.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

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
  auth_provider TEXT NOT NULL DEFAULT 'password',
  google_sub TEXT UNIQUE,
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

CREATE TABLE IF NOT EXISTS workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL DEFAULT 'My Workspace',
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  credit_balance INTEGER NOT NULL DEFAULT 0 CHECK (credit_balance >= 0),
  reserved_balance INTEGER NOT NULL DEFAULT 0 CHECK (reserved_balance >= 0),
  promo_granted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS video_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  product_url TEXT NOT NULL,
  target_language TEXT NOT NULL CHECK (target_language IN ('ur', 'ar', 'hi', 'en')),
  aspect_ratio TEXT NOT NULL DEFAULT '9:16',
  duration_seconds INTEGER NOT NULL DEFAULT 4,
  idempotency_key TEXT,
  script_json JSONB,
  veo_gcs_uri TEXT,
  final_mp4_url TEXT,
  storage_rel_path TEXT,
  status TEXT NOT NULL DEFAULT 'CREATED' CHECK (
    status IN (
      'CREATED', 'QUEUED', 'PROCESSING', 'RENDERING', 'COMPLETED', 'FAILED', 'CANCELLED',
      'PENDING', 'GENERATING_CLIPS', 'COMPOSITING'
    )
  ),
  progress_pct INTEGER NOT NULL DEFAULT 0,
  stage_detail TEXT NOT NULL DEFAULT 'Queued',
  error_code TEXT,
  error_message TEXT,
  reserved_credits INTEGER NOT NULL DEFAULT 1,
  retry_count INTEGER NOT NULL DEFAULT 0,
  worker_id TEXT,
  lease_expires_at TIMESTAMPTZ,
  heartbeat_at TIMESTAMPTZ,
  fencing_token INTEGER NOT NULL DEFAULT 0,
  correlation_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  UNIQUE (workspace_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS credit_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  job_id UUID REFERENCES video_jobs(id) ON DELETE SET NULL,
  payment_id TEXT,
  transaction_type TEXT NOT NULL CHECK (
    transaction_type IN (
      'initial_promo', 'purchased', 'reservation', 'deduction',
      'refund', 'admin_adjustment', 'payment_refund', 'promo_bonus'
    )
  ),
  amount INTEGER NOT NULL DEFAULT 0,
  delta INTEGER NOT NULL DEFAULT 0,
  previous_balance INTEGER NOT NULL DEFAULT 0,
  new_balance INTEGER NOT NULL DEFAULT 0,
  balance_after INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL,
  reference_id TEXT,
  status TEXT NOT NULL DEFAULT 'completed',
  idempotency_key TEXT UNIQUE,
  metadata_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user_id ON workspace_members (user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_assets_workspace_id ON workspace_assets (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_jobs_workspace_created_at ON video_jobs (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_jobs_status_lease ON video_jobs (status, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_video_jobs_correlation_id ON video_jobs (correlation_id);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_workspace_created_at ON credit_ledger (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stripe_events_payment_intent ON stripe_events (payment_intent_id);
CREATE INDEX IF NOT EXISTS idx_job_dispatch_outbox_status_next ON job_dispatch_outbox (status, next_attempt_at);

-- Financial audit ledger immutability guard
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

-- Supabase Row-Level Security (RLS) multi-tenant policies
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE schema_migrations FORCE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE stripe_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE stripe_events FORCE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members FORCE ROW LEVEL SECURITY;
ALTER TABLE workspace_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_assets FORCE ROW LEVEL SECURITY;
ALTER TABLE video_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE video_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE credit_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_ledger FORCE ROW LEVEL SECURITY;
ALTER TABLE job_dispatch_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_dispatch_outbox FORCE ROW LEVEL SECURITY;

-- Security-definer helpers prevent infinite RLS recursion on workspace_members
CREATE OR REPLACE FUNCTION public.is_workspace_member(target_workspace_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.workspace_members wm
    WHERE wm.workspace_id = target_workspace_id
      AND wm.user_id = (SELECT auth.uid())
  );
$$;

CREATE OR REPLACE FUNCTION public.is_workspace_admin(target_workspace_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.workspace_members wm
    WHERE wm.workspace_id = target_workspace_id
      AND wm.user_id = (SELECT auth.uid())
      AND wm.role IN ('owner', 'admin')
  );
$$;

REVOKE ALL ON FUNCTION public.is_workspace_member(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.is_workspace_admin(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_workspace_member(UUID) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.is_workspace_admin(UUID) TO authenticated, service_role;

-- Sensitive internal tables (users, auth_sessions, stripe_events, job_dispatch_outbox, schema_migrations)
-- keep RLS enabled with no permissive anon/authenticated policies (default deny for PostgREST).

CREATE POLICY workspaces_member_select
  ON workspaces FOR SELECT
  TO authenticated
  USING (public.is_workspace_member(id));

CREATE POLICY workspaces_owner_insert
  ON workspaces FOR INSERT
  TO authenticated
  WITH CHECK ((SELECT auth.uid()) = owner_id);

CREATE POLICY workspaces_admin_update
  ON workspaces FOR UPDATE
  TO authenticated
  USING (public.is_workspace_admin(id))
  WITH CHECK (public.is_workspace_admin(id));

CREATE POLICY workspace_members_select
  ON workspace_members FOR SELECT
  TO authenticated
  USING (public.is_workspace_member(workspace_id));

CREATE POLICY workspace_members_admin_insert
  ON workspace_members FOR INSERT
  TO authenticated
  WITH CHECK (public.is_workspace_admin(workspace_id));

CREATE POLICY workspace_members_admin_update
  ON workspace_members FOR UPDATE
  TO authenticated
  USING (public.is_workspace_admin(workspace_id))
  WITH CHECK (public.is_workspace_admin(workspace_id));

CREATE POLICY workspace_members_admin_delete
  ON workspace_members FOR DELETE
  TO authenticated
  USING (public.is_workspace_admin(workspace_id));

CREATE POLICY workspace_assets_member_all
  ON workspace_assets FOR ALL
  TO authenticated
  USING (public.is_workspace_member(workspace_id))
  WITH CHECK (public.is_workspace_member(workspace_id));

CREATE POLICY video_jobs_member_all
  ON video_jobs FOR ALL
  TO authenticated
  USING (public.is_workspace_member(workspace_id))
  WITH CHECK (public.is_workspace_member(workspace_id));

CREATE POLICY credit_ledger_member_select
  ON credit_ledger FOR SELECT
  TO authenticated
  USING (public.is_workspace_member(workspace_id));
