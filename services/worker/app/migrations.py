"""Cross-dialect schema migration runner for SQLite and PostgreSQL."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

MIGRATION_VERSION = "002_saas_multi_tenant_auth_billing"

_LEGACY_JOB_COLUMN_DEFAULTS = {
    "user_id": "CHAR(36)",
    "aspect_ratio": "VARCHAR(8) NOT NULL DEFAULT '9:16'",
    "duration_seconds": "INTEGER NOT NULL DEFAULT 4",
    "idempotency_key": "VARCHAR(128)",
    "storage_rel_path": "TEXT",
    "progress_pct": "INTEGER NOT NULL DEFAULT 0",
    "stage_detail": "VARCHAR(200) NOT NULL DEFAULT 'Queued'",
    "error_code": "VARCHAR(64)",
    "error_message": "TEXT",
    "reserved_credits": "INTEGER NOT NULL DEFAULT 1",
    "retry_count": "INTEGER NOT NULL DEFAULT 0",
    "updated_at": "TIMESTAMP",
    "completed_at": "TIMESTAMP",
}

_LEGACY_WORKSPACE_COLUMN_DEFAULTS = {
    "name": "VARCHAR(160) NOT NULL DEFAULT 'Workspace'",
    "reserved_balance": "INTEGER NOT NULL DEFAULT 0",
    "promo_granted": "BOOLEAN NOT NULL DEFAULT FALSE",
    "updated_at": "TIMESTAMP",
}

_LEGACY_LEDGER_COLUMN_DEFAULTS = {
    "user_id": "CHAR(36)",
    "job_id": "CHAR(36)",
    "payment_id": "VARCHAR(128)",
    "reference_id": "VARCHAR(128)",
    "transaction_type": "VARCHAR(32) NOT NULL DEFAULT 'admin_adjustment'",
    "amount": "INTEGER NOT NULL DEFAULT 0",
    "previous_balance": "INTEGER NOT NULL DEFAULT 0",
    "new_balance": "INTEGER NOT NULL DEFAULT 0",
    "balance_after": "INTEGER NOT NULL DEFAULT 0",
    "status": "VARCHAR(32) NOT NULL DEFAULT 'completed'",
    "idempotency_key": "VARCHAR(160)",
    "metadata_json": "TEXT",
}


def _add_missing_columns(
    conn,
    table_name: str,
    existing_cols: set[str],
    column_defs: dict[str, str],
    dialect: str,
) -> None:
    for col_name, col_ddl in column_defs.items():
        if col_name in existing_cols:
            continue
        ddl = col_ddl
        if dialect == "postgresql":
            if col_name == "metadata_json":
                ddl = "JSONB"
            elif col_name in ("user_id", "job_id"):
                ddl = "UUID"
            elif col_name in ("updated_at", "completed_at"):
                ddl = "TIMESTAMPTZ"
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {ddl}"))


def _sqlite_rebuild_video_jobs_if_old_check(conn) -> None:
    """Upgrade legacy SQLite video_jobs table CHECK constraint non-destructively."""
    row = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='video_jobs'")
    ).fetchone()
    if not row or not row[0]:
        return
    table_sql = str(row[0])
    if "'CREATED'" in table_sql and "'CANCELLED'" in table_sql:
        return

    # Rebuild preserving all existing rows with the expanded status check constraint.
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        cols_info = conn.execute(text("PRAGMA table_info(video_jobs)")).fetchall()
        existing_names = [str(r[1]) for r in cols_info]
        conn.execute(
            text(
                """
                CREATE TABLE video_jobs_v2 (
                  id CHAR(36) PRIMARY KEY,
                  workspace_id CHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                  user_id CHAR(36),
                  product_url TEXT NOT NULL,
                  target_language VARCHAR(8) NOT NULL
                    CHECK (target_language IN ('ur', 'ar', 'hi', 'en')),
                  aspect_ratio VARCHAR(8) NOT NULL DEFAULT '9:16',
                  duration_seconds INTEGER NOT NULL DEFAULT 4,
                  idempotency_key VARCHAR(128),
                  script_json TEXT,
                  veo_gcs_uri TEXT,
                  final_mp4_url TEXT,
                  storage_rel_path TEXT,
                  status VARCHAR(32) NOT NULL DEFAULT 'CREATED' CHECK (
                    status IN (
                      'CREATED', 'QUEUED', 'PROCESSING', 'RENDERING',
                      'COMPLETED', 'FAILED', 'CANCELLED',
                      'PENDING', 'GENERATING_CLIPS', 'COMPOSITING'
                    )
                  ),
                  progress_pct INTEGER NOT NULL DEFAULT 0,
                  stage_detail VARCHAR(200) NOT NULL DEFAULT 'Queued',
                  error_code VARCHAR(64),
                  error_message TEXT,
                  reserved_credits INTEGER NOT NULL DEFAULT 1,
                  retry_count INTEGER NOT NULL DEFAULT 0,
                  created_at TIMESTAMP NOT NULL,
                  updated_at TIMESTAMP,
                  completed_at TIMESTAMP
                )
                """
            )
        )
        v2_cols = [
            "id",
            "workspace_id",
            "user_id",
            "product_url",
            "target_language",
            "aspect_ratio",
            "duration_seconds",
            "idempotency_key",
            "script_json",
            "veo_gcs_uri",
            "final_mp4_url",
            "storage_rel_path",
            "status",
            "progress_pct",
            "stage_detail",
            "error_code",
            "error_message",
            "reserved_credits",
            "retry_count",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        copy_cols = [c for c in v2_cols if c in existing_names]
        col_csv = ", ".join(copy_cols)
        conn.execute(
            text(f"INSERT INTO video_jobs_v2 ({col_csv}) SELECT {col_csv} FROM video_jobs")
        )
        conn.execute(text("DROP TABLE video_jobs"))
        conn.execute(text("ALTER TABLE video_jobs_v2 RENAME TO video_jobs"))
    finally:
        conn.execute(text("PRAGMA foreign_keys=ON"))


def run_migrations(engine: Engine, metadata) -> None:
    """Create missing tables and safely upgrade existing v1 schemas in-place."""
    metadata.create_all(bind=engine)
    inspector = inspect(engine)
    dialect = engine.dialect.name

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version VARCHAR(128) PRIMARY KEY, "
                "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )

        tables = set(inspector.get_table_names())
        if "workspaces" in tables:
            ws_cols = {c["name"] for c in inspector.get_columns("workspaces")}
            _add_missing_columns(
                conn, "workspaces", ws_cols, _LEGACY_WORKSPACE_COLUMN_DEFAULTS, dialect
            )

        if "video_jobs" in tables:
            job_cols = {c["name"] for c in inspector.get_columns("video_jobs")}
            _add_missing_columns(conn, "video_jobs", job_cols, _LEGACY_JOB_COLUMN_DEFAULTS, dialect)
            if dialect == "sqlite":
                _sqlite_rebuild_video_jobs_if_old_check(conn)

        if "credit_ledger" in tables:
            ledger_cols = {c["name"] for c in inspector.get_columns("credit_ledger")}
            _add_missing_columns(
                conn, "credit_ledger", ledger_cols, _LEGACY_LEDGER_COLUMN_DEFAULTS, dialect
            )
            conn.execute(
                text(
                    "UPDATE credit_ledger SET new_balance = balance_after "
                    "WHERE new_balance = 0 AND balance_after <> 0"
                )
            )
            conn.execute(
                text("UPDATE credit_ledger SET amount = ABS(delta) WHERE amount = 0 AND delta <> 0")
            )

        # Ensure unique partial/nullable indexes exist on upgraded schemas.
        if dialect in ("sqlite", "postgresql"):
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_ledger_idempotency_key "
                    "ON credit_ledger (idempotency_key) WHERE idempotency_key IS NOT NULL"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_video_jobs_workspace_idempotency_key "
                    "ON video_jobs (workspace_id, idempotency_key) "
                    "WHERE idempotency_key IS NOT NULL"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_video_jobs_workspace_created_at "
                    "ON video_jobs (workspace_id, created_at DESC)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_credit_ledger_workspace_created_at "
                    "ON credit_ledger (workspace_id, created_at DESC)"
                )
            )

        already = conn.execute(
            text("SELECT version FROM schema_migrations WHERE version = :v"),
            {"v": MIGRATION_VERSION},
        ).fetchone()
        if not already:
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                {"v": MIGRATION_VERSION},
            )
