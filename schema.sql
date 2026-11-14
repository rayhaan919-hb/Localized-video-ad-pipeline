CREATE TABLE workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL,
  credit_balance INTEGER NOT NULL DEFAULT 10 CHECK (credit_balance >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE video_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  product_url TEXT NOT NULL,
  target_language TEXT NOT NULL CHECK (target_language IN ('ur', 'ar', 'hi', 'en')),
  script_json JSONB,
  veo_gcs_uri TEXT,
  final_mp4_url TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'GENERATING_CLIPS', 'COMPOSITING', 'COMPLETED', 'FAILED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE credit_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  delta INTEGER NOT NULL CHECK (delta <> 0),
  reason TEXT NOT NULL,
  reference_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_video_jobs_workspace_created_at
  ON video_jobs (workspace_id, created_at DESC);

CREATE INDEX idx_credit_ledger_workspace_created_at
  ON credit_ledger (workspace_id, created_at DESC);

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE video_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_ledger ENABLE ROW LEVEL SECURITY;

CREATE POLICY workspaces_owner_select
  ON workspaces FOR SELECT
  USING ((SELECT auth.uid()) = owner_id);

CREATE POLICY workspaces_owner_insert
  ON workspaces FOR INSERT
  WITH CHECK ((SELECT auth.uid()) = owner_id);

CREATE POLICY workspaces_owner_update
  ON workspaces FOR UPDATE
  USING ((SELECT auth.uid()) = owner_id)
  WITH CHECK ((SELECT auth.uid()) = owner_id);

CREATE POLICY video_jobs_owner_all
  ON video_jobs FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM workspaces w
      WHERE w.id = video_jobs.workspace_id
        AND w.owner_id = (SELECT auth.uid())
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM workspaces w
      WHERE w.id = video_jobs.workspace_id
        AND w.owner_id = (SELECT auth.uid())
    )
  );

CREATE POLICY credit_ledger_owner_select
  ON credit_ledger FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM workspaces w
      WHERE w.id = credit_ledger.workspace_id
        AND w.owner_id = (SELECT auth.uid())
    )
  );
