"""Database models, session management, and atomic credit ledger operations."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from app.config import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID, settings

VALID_LANGUAGES = ("ur", "ar", "hi", "en")
VALID_STATUSES = ("PENDING", "GENERATING_CLIPS", "COMPOSITING", "COMPLETED", "FAILED")


def normalize_uuid(value: str | uuid.UUID) -> str:
    """Normalize a UUID string or UUID object into a canonical hyphenated UUID string."""
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(uuid.UUID(str(value).strip()))


class UUIDString(TypeDecorator[str]):
    """Platform-independent UUID type storing canonical 36-char hyphenated strings."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: str | uuid.UUID | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return normalize_uuid(value)

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return str(value)


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all database tables."""


class Workspace(Base):
    """Workspace table matching schema.sql."""

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("credit_balance >= 0", name="ck_workspaces_credit_balance_non_negative"),
    )

    id: Mapped[str] = mapped_column(
        UUIDString(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_id: Mapped[str] = mapped_column(
        UUIDString(),
        nullable=False,
        default=lambda: DEFAULT_OWNER_ID,
    )
    credit_balance: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
        server_default=text("10"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    jobs: Mapped[list[VideoJob]] = relationship(
        "VideoJob",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    ledger_entries: Mapped[list[CreditLedger]] = relationship(
        "CreditLedger",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class VideoJob(Base):
    """Video render job table matching schema.sql."""

    __tablename__ = "video_jobs"
    __table_args__ = (
        CheckConstraint(
            "target_language IN ('ur', 'ar', 'hi', 'en')",
            name="ck_video_jobs_target_language",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'GENERATING_CLIPS', 'COMPOSITING', 'COMPLETED', 'FAILED')",
            name="ck_video_jobs_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUIDString(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    workspace_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_language: Mapped[str] = mapped_column(Text, nullable=False)
    script_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    veo_gcs_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_mp4_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="PENDING",
        server_default=text("'PENDING'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="jobs")


class CreditLedger(Base):
    """Audit trail of atomic credit deductions, refunds, and top-up checkouts."""

    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(
        UUIDString(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    workspace_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[str | None] = mapped_column(UUIDString(), nullable=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="ledger_entries")


def _build_engine(db_url: str) -> Engine:
    """Create a SQLAlchemy engine supporting both SQLite and PostgreSQL."""
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if ":memory:" in db_url:
            eng = create_engine(
                db_url,
                connect_args=connect_args,
                poolclass=StaticPool,
            )
        else:
            eng = create_engine(db_url, connect_args=connect_args)

        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return eng
    return create_engine(db_url, pool_pre_ping=True)


engine: Engine = _build_engine(settings.effective_database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def configure_database(db_url: str | None = None) -> Engine:
    """Reconfigure engine & SessionLocal (useful for test isolation) and initialize schema."""
    global engine, SessionLocal
    resolved = db_url or settings.effective_database_url
    engine = _build_engine(resolved)
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    init_db()
    return engine


def init_db() -> None:
    """Create database tables and seed the default workspace if missing."""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        existing = session.get(Workspace, DEFAULT_WORKSPACE_ID)
        if existing is None:
            default_ws = Workspace(
                id=DEFAULT_WORKSPACE_ID,
                owner_id=DEFAULT_OWNER_ID,
                credit_balance=10,
            )
            session.add(default_ws)
            session.add(
                CreditLedger(
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    delta=10,
                    reason="initial_seed",
                    balance_after=10,
                )
            )
            session.commit()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_workspace(
    session: Session,
    workspace_id: str | uuid.UUID,
    owner_id: str | uuid.UUID = DEFAULT_OWNER_ID,
    initial_credits: int = 10,
) -> Workspace:
    """Retrieve a workspace by ID, auto-provisioning it if it does not exist yet."""
    ws_id = normalize_uuid(workspace_id)
    ws = session.get(Workspace, ws_id)
    if ws is None:
        ws = Workspace(
            id=ws_id,
            owner_id=normalize_uuid(owner_id),
            credit_balance=initial_credits,
        )
        session.add(ws)
        session.add(
            CreditLedger(
                workspace_id=ws_id,
                delta=initial_credits,
                reason="workspace_provisioned",
                balance_after=initial_credits,
            )
        )
        session.commit()
        session.refresh(ws)
    return ws


def deduct_credit_atomically(
    session: Session,
    workspace_id: str | uuid.UUID,
    job_id: str | uuid.UUID | None = None,
    auto_provision: bool = True,
) -> bool:
    """Atomically deduct 1 credit from a workspace if credit_balance >= 1.

    Executes:
        UPDATE workspaces
        SET credit_balance = credit_balance - 1
        WHERE id = :id AND credit_balance >= 1

    Returns True if 1 credit was deducted, False if insufficient credits.
    """
    ws_id = normalize_uuid(workspace_id)
    if auto_provision:
        ensure_workspace(session, ws_id)

    stmt = text(
        "UPDATE workspaces "
        "SET credit_balance = credit_balance - 1 "
        "WHERE id = :id AND credit_balance >= 1"
    )
    result = session.execute(stmt, {"id": ws_id})
    if result.rowcount != 1:
        session.rollback()
        return False

    ws = session.execute(select(Workspace).where(Workspace.id == ws_id)).scalar_one()
    session.refresh(ws)
    session.add(
        CreditLedger(
            workspace_id=ws_id,
            job_id=normalize_uuid(job_id) if job_id else None,
            delta=-1,
            reason="video_render_deduction",
            balance_after=ws.credit_balance,
        )
    )
    session.commit()
    return True


def refund_credit_atomically(
    session: Session,
    workspace_id: str | uuid.UUID,
    job_id: str | uuid.UUID | None = None,
    reason: str = "video_render_failed_refund",
) -> int:
    """Atomically refund 1 credit to a workspace when a render job fails."""
    ws_id = normalize_uuid(workspace_id)
    stmt = text(
        "UPDATE workspaces "
        "SET credit_balance = credit_balance + 1 "
        "WHERE id = :id"
    )
    session.execute(stmt, {"id": ws_id})
    ws = session.execute(select(Workspace).where(Workspace.id == ws_id)).scalar_one()
    session.refresh(ws)
    session.add(
        CreditLedger(
            workspace_id=ws_id,
            job_id=normalize_uuid(job_id) if job_id else None,
            delta=1,
            reason=reason,
            balance_after=ws.credit_balance,
        )
    )
    session.commit()
    return ws.credit_balance


def add_credits_atomically(
    session: Session,
    workspace_id: str | uuid.UUID,
    credits: int,
    reason: str = "credit_pack_checkout",
) -> Workspace:
    """Atomically add credits to a workspace and record a ledger entry."""
    if credits <= 0:
        raise ValueError("credits must be a positive integer")
    ws_id = normalize_uuid(workspace_id)
    ensure_workspace(session, ws_id)
    stmt = text(
        "UPDATE workspaces "
        "SET credit_balance = credit_balance + :credits "
        "WHERE id = :id"
    )
    session.execute(stmt, {"id": ws_id, "credits": credits})
    ws = session.execute(select(Workspace).where(Workspace.id == ws_id)).scalar_one()
    session.refresh(ws)
    session.add(
        CreditLedger(
            workspace_id=ws_id,
            delta=credits,
            reason=reason,
            balance_after=ws.credit_balance,
        )
    )
    session.commit()
    session.refresh(ws)
    return ws
