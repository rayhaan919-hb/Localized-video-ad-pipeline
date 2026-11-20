"""Database engine, SaaS multi-tenant ORM models, and atomic credit operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    case,
    create_engine,
    event,
    func,
    inspect,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import CHAR, TypeDecorator

from app.config import settings
from app.migrations import run_migrations

VALID_LANGUAGES = ("ur", "ar", "hi", "en")
CANONICAL_JOB_STATUSES = (
    "CREATED",
    "QUEUED",
    "PROCESSING",
    "RENDERING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
VALID_STATUSES = CANONICAL_JOB_STATUSES + ("PENDING", "GENERATING_CLIPS", "COMPOSITING")
ACTIVE_EXECUTION_STATUSES = ("PROCESSING", "RENDERING", "GENERATING_CLIPS", "COMPOSITING")
QUEUED_JOB_STATUSES = ("CREATED", "QUEUED", "PENDING")
TERMINAL_JOB_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")
VALID_WORKSPACE_ROLES = ("owner", "admin", "member")
VALID_TRANSACTION_TYPES = (
    "initial_promo",
    "purchased",
    "reservation",
    "deduction",
    "refund",
    "admin_adjustment",
    "payment_refund",
    "promo_bonus",
)


def utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class InsufficientCreditsError(Exception):
    """Raised when a workspace lacks spendable credits for an atomic reservation."""


class UUIDString(TypeDecorator):
    """Store UUID values transparently as native UUID on Postgres and CHAR(36) on SQLite."""

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: str | uuid.UUID | None, dialect) -> str | None:
        if value is None:
            return None
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value: Any, dialect) -> str | None:
        if value is None:
            return None
        return str(value)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class User(Base):
    """Registered SaaS customer account."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auth_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="password")
    google_sub: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    email_verify_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email_verify_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_reset_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class AuthSession(Base):
    """Server-persisted refresh session supporting rotation and revocation."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Workspace(Base):
    """Tenant workspace owning credit balance, jobs, and assets."""

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("credit_balance >= 0", name="ck_workspaces_credit_balance_nonneg"),
        CheckConstraint("reserved_balance >= 0", name="ck_workspaces_reserved_balance_nonneg"),
    )

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="My Workspace")
    owner_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credit_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    promo_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class WorkspaceMember(Base):
    """Membership linking users to workspaces with RBAC roles."""

    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_ws_user"),
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_workspace_members_role"),
    )

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class WorkspaceAsset(Base):
    """Private workspace-scoped uploaded/fetched product assets and rendered outputs."""

    __tablename__ = "workspace_assets"

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        UUIDString(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    asset_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_rel_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class VideoJob(Base):
    """Video render job with canonical workflow states and private storage path."""

    __tablename__ = "video_jobs"
    __table_args__ = (
        CheckConstraint(
            "target_language IN ('ur', 'ar', 'hi', 'en')", name="ck_video_jobs_target_language"
        ),
        CheckConstraint(
            "status IN ('CREATED', 'QUEUED', 'PROCESSING', 'RENDERING', 'COMPLETED', "
            "'FAILED', 'CANCELLED', 'PENDING', 'GENERATING_CLIPS', 'COMPOSITING')",
            name="ck_video_jobs_status",
        ),
        Index("idx_video_jobs_workspace_created", "workspace_id", "created_at"),
        Index("idx_video_jobs_status_lease", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        UUIDString(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_language: Mapped[str] = mapped_column(String(8), nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False, default="9:16")
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    script_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    veo_gcs_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_mp4_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_rel_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage_detail: Mapped[str] = mapped_column(String(200), nullable=False, default="Queued")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserved_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditLedger(Base):
    """Immutable audit trail of all workspace credit transactions."""

    __tablename__ = "credit_ledger"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('initial_promo', 'purchased', 'reservation', 'deduction', "
            "'refund', 'admin_adjustment', 'payment_refund', 'promo_bonus')",
            name="ck_credit_ledger_tx_type",
        ),
        Index("idx_credit_ledger_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        UUIDString(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        UUIDString(), ForeignKey("video_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    previous_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class StripeEvent(Base):
    """Processed Stripe webhook events ensuring strictly idempotent billing handling."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    stripe_event_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payment_intent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    checkout_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        UUIDString(), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        UUIDString(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    pack_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    credits_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processed")
    payload_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class JobDispatchOutbox(Base):
    """Transactional outbox ensuring durable job publication across API/broker failures."""

    __tablename__ = "job_dispatch_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PUBLISHING', 'PUBLISHED', 'FAILED', 'CANCELLED')",
            name="ck_job_dispatch_outbox_status",
        ),
        Index("idx_job_dispatch_outbox_status_next", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(
        UUIDString(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


def _configure_sqlite_pragmas(db_engine: Engine) -> None:
    if db_engine.dialect.name != "sqlite":
        return

    @event.listens_for(db_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def _build_engine(database_url: str | None = None) -> Engine:
    url = database_url or settings.effective_database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not configured.")
    is_sqlite = url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 15} if is_sqlite else {}
    engine_kwargs: dict[str, Any] = {
        "connect_args": connect_args,
        "pool_pre_ping": True,
        "future": True,
    }
    if not is_sqlite:
        engine_kwargs.update(
            {
                "pool_size": settings.effective_db_pool_size,
                "max_overflow": settings.effective_db_max_overflow,
                "pool_timeout": settings.effective_db_pool_timeout,
                "pool_recycle": settings.effective_db_pool_recycle,
            }
        )
    target_engine = create_engine(url, **engine_kwargs)
    _configure_sqlite_pragmas(target_engine)
    return target_engine


_IMMUTABLE_LEDGER_FIELDS = (
    "workspace_id",
    "user_id",
    "job_id",
    "payment_id",
    "transaction_type",
    "amount",
    "delta",
    "previous_balance",
    "new_balance",
    "balance_after",
    "idempotency_key",
    "created_at",
)


@event.listens_for(CreditLedger, "before_delete")
def _prevent_credit_ledger_delete(_mapper, _connection, _target) -> None:
    raise RuntimeError("CreditLedger records are immutable and cannot be deleted.")


@event.listens_for(CreditLedger, "before_update")
def _prevent_credit_ledger_financial_mutation(_mapper, _connection, target) -> None:
    state = inspect(target)
    for field_name in _IMMUTABLE_LEDGER_FIELDS:
        hist = state.get_history(field_name, True)
        if hist.has_changes():
            raise RuntimeError(
                f"CreditLedger field '{field_name}' is immutable and cannot be modified."
            )


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def configure_database(database_url: str) -> None:
    """Reconfigure module-level SQLAlchemy engine and session factory (used by tests/CLI)."""
    global engine, SessionLocal
    engine.dispose()
    engine = _build_engine(database_url)
    SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )


def init_db() -> None:
    """Apply safe schema migrations without provisioning unauthenticated shared workspaces."""
    run_migrations(engine, Base.metadata)


def get_session():
    """Yield a SQLAlchemy session wrapped cleanly for FastAPI dependencies."""
    with SessionLocal() as session:
        yield session


def create_workspace_for_user(
    session: Session,
    *,
    owner_id: str | uuid.UUID,
    name: str = "My Workspace",
    grant_initial_promo: bool = False,
    promo_credits: int = 0,
) -> Workspace:
    """Create a workspace for owner_id, add owner membership, and grant promo if requested."""
    owner_str = str(uuid.UUID(str(owner_id)))
    ws = Workspace(
        id=str(uuid.uuid4()),
        name=(name.strip() or "My Workspace")[:160],
        owner_id=owner_str,
        credit_balance=0,
        reserved_balance=0,
        promo_granted=False,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(ws)
    session.flush()

    member = WorkspaceMember(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        user_id=owner_str,
        role="owner",
        created_at=utcnow(),
    )
    session.add(member)
    session.flush()

    if grant_initial_promo and promo_credits > 0:
        add_credits_atomically(
            session,
            workspace_id=ws.id,
            credits=promo_credits,
            transaction_type="initial_promo",
            reason="Initial signup promotional credits",
            user_id=owner_str,
            idempotency_key=f"initial_promo:{ws.id}",
            metadata={"source": "signup_promo_policy"},
        )
        ws.promo_granted = True
        session.flush()

    session.refresh(ws)
    return ws


def _expire_workspace_cache(session: Session, ws_id: str) -> None:
    """Ensure cached Workspace ORM instances in the same session see Core UPDATE changes."""
    for obj in list(session.identity_map.values()):
        if isinstance(obj, Workspace) and obj.id == ws_id:
            session.expire(obj, ["credit_balance", "reserved_balance", "updated_at"])


def reserve_credit_atomically(
    session: Session,
    *,
    workspace_id: str | uuid.UUID,
    job_id: str | uuid.UUID,
    user_id: str | uuid.UUID | None = None,
    cost: int = 1,
    reason: str = "Video generation reservation",
) -> int:
    """Atomically reserve spendable credits for a job and append a ledger transaction."""
    if cost <= 0:
        raise ValueError("cost must be greater than zero.")
    ws_id = str(uuid.UUID(str(workspace_id)))
    job_str = str(uuid.UUID(str(job_id)))
    uid_str = str(uuid.UUID(str(user_id))) if user_id else None
    idem_key = f"reserve:{job_str}"

    existing = session.scalar(select(CreditLedger).where(CreditLedger.idempotency_key == idem_key))
    if existing is not None:
        ws = session.get(Workspace, ws_id)
        return int(ws.credit_balance if ws is not None else existing.new_balance)

    stmt = (
        update(Workspace)
        .where(Workspace.id == ws_id, Workspace.credit_balance >= cost)
        .values(
            credit_balance=Workspace.credit_balance - cost,
            reserved_balance=Workspace.reserved_balance + cost,
            updated_at=utcnow(),
        )
        .returning(Workspace.credit_balance)
    )
    row = session.execute(stmt).fetchone()
    if row is None:
        raise InsufficientCreditsError(
            "Insufficient workspace credits for this video generation job."
        )

    new_balance = int(row[0])
    prev_balance = new_balance + cost
    _expire_workspace_cache(session, ws_id)
    session.add(
        CreditLedger(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            user_id=uid_str,
            job_id=job_str,
            transaction_type="reservation",
            amount=cost,
            delta=-cost,
            previous_balance=prev_balance,
            new_balance=new_balance,
            balance_after=new_balance,
            reason=reason,
            reference_id=job_str,
            status="pending",
            idempotency_key=idem_key,
            metadata_json={"held_credits": cost},
            created_at=utcnow(),
        )
    )
    session.flush()
    return new_balance


def finalize_credit_deduction(
    session: Session,
    *,
    workspace_id: str | uuid.UUID,
    job_id: str | uuid.UUID,
    user_id: str | uuid.UUID | None = None,
    cost: int = 1,
) -> int:
    """Finalize a previously reserved credit hold after a verified successful render."""
    ws_id = str(uuid.UUID(str(workspace_id)))
    job_str = str(uuid.UUID(str(job_id)))
    uid_str = str(uuid.UUID(str(user_id))) if user_id else None
    deduct_key = f"deduct:{job_str}"

    existing = session.scalar(
        select(CreditLedger).where(CreditLedger.idempotency_key == deduct_key)
    )
    if existing is not None:
        ws = session.get(Workspace, ws_id)
        return int(ws.credit_balance if ws is not None else existing.new_balance)

    res_row = session.scalar(
        select(CreditLedger).where(CreditLedger.idempotency_key == f"reserve:{job_str}")
    )
    if res_row is not None and res_row.status == "refunded":
        ws = session.get(Workspace, ws_id)
        return int(ws.credit_balance if ws is not None else 0)

    release = cost if res_row is not None else 0
    ws = session.get(Workspace, ws_id)
    if ws is None:
        return 0
    if release > 0:
        row = session.execute(
            update(Workspace)
            .where(Workspace.id == ws_id)
            .values(
                reserved_balance=case(
                    (Workspace.reserved_balance >= release, Workspace.reserved_balance - release),
                    else_=0,
                ),
                updated_at=utcnow(),
            )
            .returning(Workspace.credit_balance, Workspace.reserved_balance)
        ).fetchone()
        _expire_workspace_cache(session, ws_id)
        cur_balance = int(row[0]) if row else int(ws.credit_balance)
    else:
        cur_balance = int(ws.credit_balance)

    if res_row is not None:
        res_row.status = "completed"

    session.add(
        CreditLedger(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            user_id=uid_str,
            job_id=job_str,
            transaction_type="deduction",
            amount=cost,
            delta=0,
            previous_balance=cur_balance,
            new_balance=cur_balance,
            balance_after=cur_balance,
            reason="Video generation completed — reserved credit finalized",
            reference_id=job_str,
            status="completed",
            idempotency_key=deduct_key,
            metadata_json={"settled_reserved_credits": release},
            created_at=utcnow(),
        )
    )
    session.flush()
    return cur_balance


def refund_credit_atomically(
    session: Session,
    *,
    workspace_id: str | uuid.UUID,
    job_id: str | uuid.UUID,
    user_id: str | uuid.UUID | None = None,
    cost: int = 1,
    reason: str = "Video generation failed or cancelled — credit refund",
) -> int | None:
    """Idempotently refund a job's reserved credits without allowing duplicate refunds."""
    ws_id = str(uuid.UUID(str(workspace_id)))
    job_str = str(uuid.UUID(str(job_id)))
    uid_str = str(uuid.UUID(str(user_id))) if user_id else None
    refund_key = f"refund:{job_str}"

    existing_refund = session.scalar(
        select(CreditLedger).where(CreditLedger.idempotency_key == refund_key)
    )
    if existing_refund is not None:
        ws = session.get(Workspace, ws_id)
        return int(ws.credit_balance if ws is not None else existing_refund.new_balance)

    # Never refund a job that never had a reservation or already finalized deduction.
    res_row = session.scalar(
        select(CreditLedger).where(CreditLedger.idempotency_key == f"reserve:{job_str}")
    )
    if res_row is None:
        return None
    if res_row.status == "completed":
        ws = session.get(Workspace, ws_id)
        return int(ws.credit_balance if ws is not None else 0)

    ws = session.get(Workspace, ws_id)
    if ws is None:
        return None
    release = cost if ws.reserved_balance >= cost else ws.reserved_balance

    row = session.execute(
        update(Workspace)
        .where(Workspace.id == ws_id)
        .values(
            credit_balance=Workspace.credit_balance + cost,
            reserved_balance=case(
                (Workspace.reserved_balance >= cost, Workspace.reserved_balance - cost),
                else_=0,
            ),
            updated_at=utcnow(),
        )
        .returning(Workspace.credit_balance, Workspace.reserved_balance)
    ).fetchone()
    if row is None:
        return None

    new_balance = int(row[0])
    prev_balance = new_balance - cost
    res_row.status = "refunded"
    _expire_workspace_cache(session, ws_id)

    session.add(
        CreditLedger(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            user_id=uid_str,
            job_id=job_str,
            transaction_type="refund",
            amount=cost,
            delta=cost,
            previous_balance=prev_balance,
            new_balance=new_balance,
            balance_after=new_balance,
            reason=reason,
            reference_id=job_str,
            status="completed",
            idempotency_key=refund_key,
            metadata_json={"released_reserved_credits": release},
            created_at=utcnow(),
        )
    )
    session.flush()
    return new_balance


def add_credits_atomically(
    session: Session,
    *,
    workspace_id: str | uuid.UUID,
    credits: int,
    transaction_type: str,
    reason: str,
    user_id: str | uuid.UUID | None = None,
    payment_id: str | None = None,
    reference_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Atomically grant credits and record an immutable CreditLedger entry."""
    if credits <= 0:
        raise ValueError("credits must be a positive integer.")
    if transaction_type not in VALID_TRANSACTION_TYPES:
        raise ValueError(f"Unsupported transaction_type: {transaction_type}")

    ws_id = str(uuid.UUID(str(workspace_id)))
    uid_str = str(uuid.UUID(str(user_id))) if user_id else None

    if idempotency_key:
        existing = session.scalar(
            select(CreditLedger).where(CreditLedger.idempotency_key == idempotency_key)
        )
        if existing is not None:
            ws = session.get(Workspace, ws_id)
            return int(ws.credit_balance if ws is not None else existing.new_balance)

    row = session.execute(
        update(Workspace)
        .where(Workspace.id == ws_id)
        .values(
            credit_balance=Workspace.credit_balance + credits,
            updated_at=utcnow(),
        )
        .returning(Workspace.credit_balance)
    ).fetchone()
    if row is None:
        raise ValueError(f"Workspace {ws_id} not found.")

    new_balance = int(row[0])
    prev_balance = new_balance - credits
    _expire_workspace_cache(session, ws_id)
    session.add(
        CreditLedger(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            user_id=uid_str,
            payment_id=payment_id,
            transaction_type=transaction_type,
            amount=credits,
            delta=credits,
            previous_balance=prev_balance,
            new_balance=new_balance,
            balance_after=new_balance,
            reason=reason,
            reference_id=reference_id or payment_id,
            status="completed",
            idempotency_key=idempotency_key,
            metadata_json=metadata,
            created_at=utcnow(),
        )
    )
    session.flush()
    return new_balance


def adjust_credits_atomically(
    session: Session,
    *,
    workspace_id: str | uuid.UUID,
    delta: int,
    transaction_type: str,
    reason: str,
    user_id: str | uuid.UUID | None = None,
    payment_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Atomically apply a positive or negative admin/adjustment credit delta cleanly."""
    if delta == 0:
        raise ValueError("delta cannot be zero.")
    if delta > 0:
        return add_credits_atomically(
            session,
            workspace_id=workspace_id,
            credits=delta,
            transaction_type=transaction_type,
            reason=reason,
            user_id=user_id,
            payment_id=payment_id,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    ws_id = str(uuid.UUID(str(workspace_id)))
    uid_str = str(uuid.UUID(str(user_id))) if user_id else None
    cost = abs(delta)

    if idempotency_key:
        existing = session.scalar(
            select(CreditLedger).where(CreditLedger.idempotency_key == idempotency_key)
        )
        if existing is not None:
            ws = session.get(Workspace, ws_id)
            return int(ws.credit_balance if ws is not None else existing.new_balance)

    row = session.execute(
        update(Workspace)
        .where(Workspace.id == ws_id, Workspace.credit_balance >= cost)
        .values(
            credit_balance=Workspace.credit_balance - cost,
            updated_at=utcnow(),
        )
        .returning(Workspace.credit_balance)
    ).fetchone()
    if row is None:
        raise InsufficientCreditsError("Cannot adjust workspace balance below zero.")

    new_balance = int(row[0])
    prev_balance = new_balance + cost
    _expire_workspace_cache(session, ws_id)
    session.add(
        CreditLedger(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            user_id=uid_str,
            payment_id=payment_id,
            transaction_type=transaction_type,
            amount=cost,
            delta=-cost,
            previous_balance=prev_balance,
            new_balance=new_balance,
            balance_after=new_balance,
            reason=reason,
            reference_id=payment_id,
            status="completed",
            idempotency_key=idempotency_key,
            metadata_json=metadata,
            created_at=utcnow(),
        )
    )
    session.flush()
    return new_balance


def reverse_credits_for_payment_refund(
    session: Session,
    *,
    workspace_id: str | uuid.UUID,
    credits_to_revoke: int,
    payment_id: str,
    idempotency_key: str,
    user_id: str | uuid.UUID | None = None,
    reason: str = "Stripe payment refunded/disputed — credit reversal",
    metadata: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """Revoke up to credits_to_revoke spendable credits on refund without negative balance."""
    ws_id = str(uuid.UUID(str(workspace_id)))
    uid_str = str(uuid.UUID(str(user_id))) if user_id else None

    existing = session.scalar(
        select(CreditLedger).where(CreditLedger.idempotency_key == idempotency_key)
    )
    if existing is not None:
        ws = session.get(Workspace, ws_id)
        return int(ws.credit_balance if ws is not None else existing.new_balance), abs(
            int(existing.delta)
        )

    ws = session.get(Workspace, ws_id)
    if ws is None:
        return 0, 0

    prev_balance = int(ws.credit_balance)
    revoked = min(max(0, credits_to_revoke), prev_balance)
    deficit = max(0, credits_to_revoke - revoked)

    if revoked > 0:
        row = session.execute(
            update(Workspace)
            .where(Workspace.id == ws_id, Workspace.credit_balance >= revoked)
            .values(
                credit_balance=Workspace.credit_balance - revoked,
                updated_at=utcnow(),
            )
            .returning(Workspace.credit_balance)
        ).fetchone()
        new_balance = int(row[0]) if row else max(0, prev_balance - revoked)
        _expire_workspace_cache(session, ws_id)
    else:
        new_balance = prev_balance

    combined_meta = dict(metadata or {})
    combined_meta.update(
        {
            "requested_revoke": credits_to_revoke,
            "actual_revoked": revoked,
            "unrecovered_deficit": deficit,
        }
    )
    session.add(
        CreditLedger(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            user_id=uid_str,
            payment_id=payment_id,
            transaction_type="payment_refund",
            amount=credits_to_revoke,
            delta=-revoked,
            previous_balance=prev_balance,
            new_balance=new_balance,
            balance_after=new_balance,
            reason=reason,
            reference_id=payment_id,
            status="completed" if deficit == 0 else "partial_recovery",
            idempotency_key=idempotency_key,
            metadata_json=combined_meta,
            created_at=utcnow(),
        )
    )
    session.flush()
    return new_balance, revoked


def db_dialect_name(session: Session) -> str:
    """Return the active SQLAlchemy dialect name for session."""
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else "sqlite"


def db_now_expr(session: Session):
    """Return a database-server clock expression (avoids app-host clock skew)."""
    if db_dialect_name(session) == "postgresql":
        return func.clock_timestamp()
    return func.strftime("%Y-%m-%d %H:%M:%f", "now").op("||")("000")


def db_offset_expr(session: Session, offset_seconds: float):
    """Return a database-server timestamp offset by offset_seconds."""
    offset = float(offset_seconds)
    if db_dialect_name(session) == "postgresql":
        return func.clock_timestamp() + func.make_interval(0, 0, 0, 0, 0, 0, offset)
    return func.strftime("%Y-%m-%d %H:%M:%f", "now", f"{offset:+.3f} seconds").op("||")("000")


def get_db_now(session: Session) -> datetime:
    """Fetch the current database clock timestamp as a timezone-aware UTC datetime."""
    val = session.execute(select(db_now_expr(session))).scalar_one()
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(val))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def create_dispatch_outbox_event(
    session: Session,
    *,
    job_id: str | uuid.UUID,
    workspace_id: str | uuid.UUID,
    payload: dict[str, Any],
    max_attempts: int = 5,
) -> JobDispatchOutbox:
    """Persist a durable outbox dispatch entry idempotently inside the caller transaction."""
    job_str = str(uuid.UUID(str(job_id)))
    ws_str = str(uuid.UUID(str(workspace_id)))
    existing = session.scalar(
        select(JobDispatchOutbox).where(JobDispatchOutbox.job_id == job_str)
    )
    if existing is not None:
        return existing
    now_sql = db_now_expr(session)
    outbox = JobDispatchOutbox(
        id=str(uuid.uuid4()),
        job_id=job_str,
        workspace_id=ws_str,
        payload_json=dict(payload),
        status="PENDING",
        attempts=0,
        max_attempts=max(1, int(max_attempts)),
        next_attempt_at=now_sql,
        created_at=now_sql,
        updated_at=now_sql,
    )
    session.add(outbox)
    session.flush()
    return outbox


def acquire_job_lease(
    session: Session,
    *,
    job_id: str | uuid.UUID,
    worker_id: str,
    lease_seconds: float | int = 120,
) -> int | None:
    """Atomically claim an unassigned or expired VideoJob lease with fencing token increment."""
    job_str = str(uuid.UUID(str(job_id)))
    now_sql = db_now_expr(session)
    exp_sql = db_offset_expr(session, max(0.05, float(lease_seconds)))
    stmt = (
        update(VideoJob)
        .where(
            VideoJob.id == job_str,
            VideoJob.status.notin_(TERMINAL_JOB_STATUSES),
            or_(
                and_(VideoJob.worker_id.is_(None), VideoJob.lease_expires_at.is_(None)),
                and_(
                    VideoJob.lease_expires_at.is_not(None),
                    VideoJob.lease_expires_at <= now_sql,
                ),
            ),
        )
        .values(
            status=case(
                (VideoJob.status.in_(QUEUED_JOB_STATUSES), "PROCESSING"),
                else_=VideoJob.status,
            ),
            worker_id=worker_id,
            heartbeat_at=now_sql,
            lease_expires_at=exp_sql,
            fencing_token=VideoJob.fencing_token + 1,
            updated_at=now_sql,
        )
        .returning(VideoJob.fencing_token)
    )
    row = session.execute(stmt).fetchone()
    if row is None:
        return None
    for obj in list(session.identity_map.values()):
        if isinstance(obj, VideoJob) and obj.id == job_str:
            session.expire(
                obj,
                [
                    "status",
                    "worker_id",
                    "heartbeat_at",
                    "lease_expires_at",
                    "fencing_token",
                    "updated_at",
                ],
            )
    return int(row[0])


def renew_job_lease(
    session: Session,
    *,
    job_id: str | uuid.UUID,
    worker_id: str,
    fencing_token: int,
    lease_seconds: float | int = 120,
) -> bool:
    """Extend an unexpired lease via DB clock without reviving expired/recovered jobs."""
    job_str = str(uuid.UUID(str(job_id)))
    now_sql = db_now_expr(session)
    exp_sql = db_offset_expr(session, max(0.05, float(lease_seconds)))
    res = session.execute(
        update(VideoJob)
        .where(
            VideoJob.id == job_str,
            VideoJob.worker_id == worker_id,
            VideoJob.fencing_token == int(fencing_token),
            VideoJob.status.in_(ACTIVE_EXECUTION_STATUSES),
            VideoJob.lease_expires_at.is_not(None),
            VideoJob.lease_expires_at > now_sql,
        )
        .values(
            heartbeat_at=now_sql,
            lease_expires_at=exp_sql,
            updated_at=now_sql,
        )
    )
    return int(res.rowcount or 0) > 0


def release_job_lease(
    session: Session,
    *,
    job_id: str | uuid.UUID,
    worker_id: str,
    fencing_token: int,
) -> bool:
    """Release worker ownership cleanly only if worker_id and fencing_token match."""
    job_str = str(uuid.UUID(str(job_id)))
    now_sql = db_now_expr(session)
    res = session.execute(
        update(VideoJob)
        .where(
            VideoJob.id == job_str,
            VideoJob.worker_id == worker_id,
            VideoJob.fencing_token == int(fencing_token),
        )
        .values(
            worker_id=None,
            lease_expires_at=None,
            updated_at=now_sql,
        )
    )
    return int(res.rowcount or 0) > 0


def reconcile_workspace_credits(session: Session, workspace_id: str | uuid.UUID) -> dict[str, Any]:
    """Compare Workspace spendable/reserved balances against immutable CreditLedger entries."""
    ws_id = str(uuid.UUID(str(workspace_id)))
    ws = session.get(Workspace, ws_id)
    if ws is None:
        raise ValueError(f"Workspace {ws_id} not found.")

    ledger_net = int(
        session.scalar(
            select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
                CreditLedger.workspace_id == ws_id
            )
        )
        or 0
    )
    pending_reservations = int(
        session.scalar(
            select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
                CreditLedger.workspace_id == ws_id,
                CreditLedger.transaction_type == "reservation",
                CreditLedger.status == "pending",
            )
        )
        or 0
    )
    entry_count = int(
        session.scalar(
            select(func.count(CreditLedger.id)).where(CreditLedger.workspace_id == ws_id)
        )
        or 0
    )
    return {
        "workspace_id": ws_id,
        "credit_balance": int(ws.credit_balance),
        "reserved_balance": int(ws.reserved_balance),
        "ledger_net_credits": ledger_net,
        "pending_reservations": pending_reservations,
        "ledger_entries": entry_count,
        "balance_discrepancy": int(ws.credit_balance) - ledger_net,
        "reserved_discrepancy": int(ws.reserved_balance) - pending_reservations,
        "is_balanced": (
            int(ws.credit_balance) == ledger_net
            and int(ws.reserved_balance) == pending_reservations
        ),
    }
