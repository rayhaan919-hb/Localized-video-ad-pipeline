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
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  UNIQUE (workspace_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS credit_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user_id ON workspace_members (user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_assets_workspace_id ON workspace_assets (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_jobs_workspace_created_at ON video_jobs (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_workspace_created_at ON credit_ledger (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stripe_events_payment_intent ON stripe_events (payment_intent_id);

-- Supabase Row-Level Security (RLS) multi-tenant policies
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE video_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_ledger ENABLE ROW LEVEL SECURITY;

CREATE POLICY workspaces_member_select
  ON workspaces FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = workspaces.id
        AND wm.user_id = (SELECT auth.uid())
    )
  );

CREATE POLICY workspaces_owner_insert
  ON workspaces FOR INSERT
  WITH CHECK ((SELECT auth.uid()) = owner_id);

CREATE POLICY workspaces_admin_update
  ON workspaces FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = workspaces.id
        AND wm.user_id = (SELECT auth.uid())
        AND wm.role IN ('owner', 'admin')
    )
  );

CREATE POLICY workspace_members_select
  ON workspace_members FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = workspace_members.workspace_id
        AND wm.user_id = (SELECT auth.uid())
    )
  );

CREATE POLICY workspace_assets_member_all
  ON workspace_assets FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = workspace_assets.workspace_id
        AND wm.user_id = (SELECT auth.uid())
    )
  );

CREATE POLICY video_jobs_member_all
  ON video_jobs FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = video_jobs.workspace_id
        AND wm.user_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = video_jobs.workspace_id
        AND wm.user_id = (SELECT auth.uid())
    )
  );

CREATE POLICY credit_ledger_member_select
  ON credit_ledger FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM workspace_members wm
      WHERE wm.workspace_id = credit_ledger.workspace_id
        AND wm.user_id = (SELECT auth.uid())
    )
  );
