"""FastAPI application for the Localized AI Video Ad Worker."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.db as db_module
from app.config import AUDIO_DIR, RENDERS_DIR, STATIC_DIR, settings
from app.db import (
    CreditLedger,
    VideoJob,
    Workspace,
    add_credits_atomically,
    deduct_credit_atomically,
    ensure_workspace,
    get_db,
    init_db,
    normalize_uuid,
)
from app.scraper import scrape_product_url
from app.tasks import process_video_job
from app.veo import ensure_sample_fixture

LanguageCode = Literal["ur", "ar", "hi", "en"]


class GenerateVideoRequest(BaseModel):
    """Request payload for POST /v1/videos/generate matching api-contract.yaml."""

    workspace_id: uuid.UUID
    product_url: AnyHttpUrl
    target_language: LanguageCode
    ad_angle: str = Field(default="problem_solution", min_length=1, max_length=64)
    simulate_failure: bool = Field(default=False)


class VideoJobResponse(BaseModel):
    """Serialized representation of a VideoJob."""

    id: str
    job_id: str
    workspace_id: str
    product_url: str
    target_language: LanguageCode
    script_json: dict[str, Any] | None = None
    veo_gcs_uri: str | None = None
    final_mp4_url: str | None = None
    status: str
    credit_balance: int | None = None
    created_at: datetime


class ScrapeProductRequest(BaseModel):
    """Request payload for POST /v1/products/scrape."""

    product_url: AnyHttpUrl
    target_language: LanguageCode = "ur"


class CreditCheckoutRequest(BaseModel):
    """Request payload for POST /v1/workspaces/{workspace_id}/credits/checkout."""

    credits: int = Field(default=10, gt=0, le=10000)
    pack_id: str = Field(default="growth_10", min_length=1, max_length=64)


def _serialize_job(job: VideoJob, credit_balance: int | None = None) -> VideoJobResponse:
    return VideoJobResponse(
        id=job.id,
        job_id=job.id,
        workspace_id=job.workspace_id,
        product_url=job.product_url,
        target_language=job.target_language,  # type: ignore[arg-type]
        script_json=job.script_json,
        veo_gcs_uri=job.veo_gcs_uri,
        final_mp4_url=job.final_mp4_url,
        status=job.status,
        credit_balance=credit_balance,
        created_at=job.created_at,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database tables, default workspace, and 9:16 MP4 sample fixture on startup."""
    init_db()
    ensure_sample_fixture()
    yield


app = FastAPI(
    title="Localized AI Video Ad API",
    version="1.0.0",
    description="FastAPI + Celery + Vertex AI Veo 3.1 + FFmpeg worker for Non-English D2C Ads",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _dir in (STATIC_DIR, RENDERS_DIR, AUDIO_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

app.mount("/static/renders", StaticFiles(directory=str(RENDERS_DIR)), name="renders")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Service readiness and configuration check."""
    return {
        "status": "ok",
        "service": "localized-video-ad-worker",
        "veo_model": settings.VEO_MODEL,
        "gcp_project_id": settings.GCP_PROJECT_ID,
        "gcs_bucket": settings.GCS_BUCKET,
        "mock_vertex_veo": settings.is_mock_veo,
    }


@app.post(
    "/v1/videos/generate",
    response_model=VideoJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_video(
    payload: GenerateVideoRequest,
    db: Session = Depends(get_db),
) -> VideoJobResponse:
    """Deduct 1 credit atomically and start Veo 3.1 + Remotion render job."""
    ws_id = normalize_uuid(payload.workspace_id)
    ensure_workspace(db, ws_id)

    job_id = str(uuid.uuid4())
    deducted = deduct_credit_atomically(
        db,
        workspace_id=ws_id,
        job_id=job_id,
        auto_provision=False,
    )
    if not deducted:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient credits in workspace. Please top up credits to generate a video.",
        )

    job = VideoJob(
        id=job_id,
        workspace_id=ws_id,
        product_url=str(payload.product_url),
        target_language=payload.target_language,
        status="PENDING",
    )
    db.add(job)
    db.commit()

    process_video_job.delay(
        job_id=job_id,
        ad_angle=payload.ad_angle,
        simulate_failure=payload.simulate_failure,
    )

    db.expire_all()
    updated_job = db.get(VideoJob, job_id)
    ws = db.get(Workspace, ws_id)
    assert updated_job is not None
    return _serialize_job(updated_job, credit_balance=ws.credit_balance if ws else None)


@app.get("/v1/videos", response_model=list[VideoJobResponse])
def list_videos(
    workspace_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[VideoJobResponse]:
    """List video render jobs, optionally filtered by workspace_id."""
    stmt = select(VideoJob).order_by(VideoJob.created_at.desc())
    if workspace_id is not None:
        stmt = stmt.where(VideoJob.workspace_id == normalize_uuid(workspace_id))
    jobs = list(db.execute(stmt).scalars().all())
    return [_serialize_job(j) for j in jobs]


@app.get("/v1/videos/{job_id}", response_model=VideoJobResponse)
def get_video_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> VideoJobResponse:
    """Retrieve a single video render job by ID."""
    normalized_id = normalize_uuid(job_id)
    job = db.get(VideoJob, normalized_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video job {normalized_id} not found",
        )
    ws = db.get(Workspace, job.workspace_id)
    return _serialize_job(job, credit_balance=ws.credit_balance if ws else None)


@app.post("/v1/products/scrape")
def scrape_product(payload: ScrapeProductRequest) -> dict[str, Any]:
    """Scrape or extract localized product metadata from a D2C product URL."""
    return scrape_product_url(
        product_url=str(payload.product_url),
        target_language=payload.target_language,
    )


@app.get("/v1/workspaces/{workspace_id}")
def get_workspace(
    workspace_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get workspace credit balance and recent ledger entries."""
    ws_id = normalize_uuid(workspace_id)
    ws = ensure_workspace(db, ws_id)
    ledger_stmt = (
        select(CreditLedger)
        .where(CreditLedger.workspace_id == ws_id)
        .order_by(CreditLedger.created_at.desc())
        .limit(25)
    )
    ledger_rows = list(db.execute(ledger_stmt).scalars().all())
    return {
        "id": ws.id,
        "owner_id": ws.owner_id,
        "credit_balance": ws.credit_balance,
        "created_at": ws.created_at.isoformat(),
        "ledger": [
            {
                "id": entry.id,
                "delta": entry.delta,
                "reason": entry.reason,
                "job_id": entry.job_id,
                "balance_after": entry.balance_after,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in ledger_rows
        ],
    }


@app.post("/v1/workspaces/{workspace_id}/credits/checkout")
def checkout_credits(
    workspace_id: uuid.UUID,
    payload: CreditCheckoutRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Atomically top up credits for a workspace."""
    ws = add_credits_atomically(
        db,
        workspace_id=workspace_id,
        credits=payload.credits,
        reason=f"checkout:{payload.pack_id}",
    )
    return {
        "id": ws.id,
        "owner_id": ws.owner_id,
        "credit_balance": ws.credit_balance,
        "added_credits": payload.credits,
        "pack_id": payload.pack_id,
    }


__all__ = ["app", "db_module"]
