"""FastAPI application for the Localized AI Video Ad Multi-Tenant SaaS API."""

from __future__ import annotations

import base64
import hmac
import json
import re
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from email.parser import BytesParser
from email.policy import default as email_default_policy
from typing import Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.db as db_module
from app.auth import (
    ACCESS_COOKIE_NAME,
    OAUTH_STATE_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    AccountLockedError,
    EmailAlreadyRegisteredError,
    EmailNotVerifiedError,
    GoogleOAuthConfigError,
    GoogleOAuthError,
    InvalidCredentialsError,
    authenticate_user,
    build_google_oauth_start,
    confirm_password_reset,
    exchange_google_oauth_code,
    get_current_user,
    issue_session_tokens,
    normalize_email,
    register_user,
    request_password_reset,
    require_workspace_role,
    revoke_all_user_sessions,
    revoke_refresh_session,
    rotate_refresh_session,
    send_verification_email,
    upsert_google_user,
    verify_google_oauth_state_cookie,
    verify_user_email,
)
from app.billing import (
    BillingConfigurationError,
    BillingError,
    WebhookSignatureError,
    WebhookValidationError,
    create_stripe_checkout_session,
    get_public_credit_packages,
    process_stripe_webhook,
)
from app.config import settings, validate_production_config
from app.db import (
    CreditLedger,
    InsufficientCreditsError,
    JobDispatchOutbox,
    User,
    VideoJob,
    Workspace,
    WorkspaceAsset,
    WorkspaceMember,
    add_credits_atomically,
    adjust_credits_atomically,
    create_dispatch_outbox_event,
    create_workspace_for_user,
    db_now_expr,
    get_session,
    init_db,
    reconcile_workspace_credits,
    refund_credit_atomically,
    reserve_credit_atomically,
    utcnow,
)
from app.scraper import (
    UnsafeUrlError,
    scrape_product_url,
    validate_image_bytes,
    validate_public_http_url,
)
from app.security import (
    RequestContextMiddleware,
    get_client_ip,
    log_audit_event,
    metrics_registry,
    rate_limiter,
)
from app.storage import (
    StorageError,
    create_signed_download_token,
    register_workspace_file,
    resolve_workspace_rel_path,
    verify_signed_download_token,
)
from app.tasks import (
    BrokerUnavailableError,
    celery_app,
    check_queue_health,
    publish_outbox_event,
    recover_interrupted_jobs,
)
from app.veo import get_ffmpeg_binary

LanguageCode = Literal["ur", "ar", "hi", "en"]
AspectRatioCode = Literal["9:16", "16:9"]
WorkspaceRole = Literal["owner", "admin", "member"]


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None)


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=256)


class PasswordResetRequestBody(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)


class PasswordResetConfirmBody(BaseModel):
    token: str = Field(..., min_length=10, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=128)


class GoogleCallbackRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=2048)
    state: str = Field(..., min_length=1, max_length=512)


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)


class AddMemberRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    role: Literal["admin", "member"] = Field(default="member")


class UpdateMemberRoleRequest(BaseModel):
    role: Literal["admin", "member"]


class GenerateVideoRequest(BaseModel):
    workspace_id: uuid.UUID
    product_url: AnyHttpUrl
    target_language: LanguageCode
    ad_angle: str = Field(default="problem_solution", min_length=1, max_length=64)
    aspect_ratio: AspectRatioCode = Field(default="9:16")
    duration_seconds: float = Field(default=4.0, ge=1.0, le=15.0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    simulate_failure: bool = Field(default=False)
    custom_props: dict[str, Any] | None = Field(default=None)


class VideoJobResponse(BaseModel):
    id: str
    job_id: str
    workspace_id: str
    user_id: str | None = None
    product_url: str
    target_language: LanguageCode
    aspect_ratio: str = "9:16"
    duration_seconds: int = 4
    script_json: dict[str, Any] | None = None
    veo_gcs_uri: str | None = None
    final_mp4_url: str | None = None
    status: str
    progress_pct: int = 0
    stage_detail: str = ""
    error_code: str | None = None
    error_message: str | None = None
    credit_balance: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ScrapeProductRequest(BaseModel):
    product_url: AnyHttpUrl
    target_language: LanguageCode = "ur"


class CreditCheckoutRequest(BaseModel):
    pack_id: Literal["starter_10", "growth_50", "scale_200"]
    success_url: str | None = Field(default=None)
    cancel_url: str | None = Field(default=None)


class AdminCreditAdjustRequest(BaseModel):
    delta: int = Field(..., ge=-10000, le=10000)
    reason: str = Field(..., min_length=3, max_length=300)


class DevTopupRequest(BaseModel):
    pack_id: Literal["starter_10", "growth_50", "scale_200"] = "starter_10"


def _set_auth_cookies(response: Response, tokens: dict[str, Any]) -> None:
    secure = settings.is_production
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=tokens["access_token"],
        max_age=int(settings.ACCESS_TOKEN_TTL_SECONDS),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=tokens["refresh_token"],
        max_age=int(settings.REFRESH_TOKEN_TTL_SECONDS),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")


def _serialize_user_summary(session: Session, user: User) -> dict[str, Any]:
    rows = session.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at.asc())
    ).all()
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "auth_provider": getattr(user, "auth_provider", "password"),
        "is_email_verified": bool(user.is_email_verified),
        "is_admin": bool(user.is_admin),
        "workspaces": [
            {
                "id": ws.id,
                "name": ws.name,
                "owner_id": ws.owner_id,
                "role": role,
                "credit_balance": ws.credit_balance,
                "reserved_balance": ws.reserved_balance,
                "created_at": ws.created_at.isoformat(),
            }
            for ws, role in rows
        ],
    }


def _serialize_job(job: VideoJob, credit_balance: int | None = None) -> VideoJobResponse:
    return VideoJobResponse(
        id=job.id,
        job_id=job.id,
        workspace_id=job.workspace_id,
        user_id=job.user_id,
        product_url=job.product_url,
        target_language=job.target_language,  # type: ignore[arg-type]
        aspect_ratio=job.aspect_ratio or "9:16",
        duration_seconds=int(job.duration_seconds or 4),
        script_json=job.script_json,
        veo_gcs_uri=job.veo_gcs_uri,
        final_mp4_url=job.final_mp4_url,
        status=job.status,
        progress_pct=int(job.progress_pct or 0),
        stage_detail=job.stage_detail or "",
        error_code=job.error_code,
        error_message=job.error_message,
        credit_balance=credit_balance,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def _enforce_rate_limit(
    request: Request,
    bucket: str,
    subject: str,
    limit: int,
    *,
    burst_limit: int | None = None,
) -> None:
    burst_win = settings.effective_rate_limit_burst_window_seconds if burst_limit else None
    decision = rate_limiter.check_with_metadata(
        bucket,
        subject,
        limit=limit,
        window_seconds=60,
        burst_limit=burst_limit,
        burst_window_seconds=burst_win,
    )
    if not decision.allowed:
        metrics_registry.incr(f"rate_limit.rejected.{bucket}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please retry shortly.",
            headers={
                "Retry-After": str(decision.retry_after),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )


def _enforce_auth_rate_limit(
    request: Request,
    extra_key: str = "",
    *,
    category: str = "auth_login",
) -> None:
    ip = get_client_ip(request)
    limit = settings.get_rate_limit(category)
    _enforce_rate_limit(request, f"{category}_ip", ip, limit)
    if extra_key:
        _enforce_rate_limit(request, f"{category}_subject", extra_key.lower(), limit)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Validate production security settings, migrate schema, and recover interrupted jobs."""
    validate_production_config()
    init_db()
    grace = (
        0
        if celery_app.conf.task_always_eager
        else settings.effective_job_unclaimed_grace_seconds
    )
    recover_interrupted_jobs(min_age_seconds=grace)
    yield


app = FastAPI(
    title="Localized AI Video Ad SaaS API",
    version="2.0.0",
    description=(
        "Multi-tenant FastAPI + Celery + Vertex AI Veo 3.1 + FFmpeg Commercial Video Ad API"
    ),
    lifespan=lifespan,
)

_cors_origins = settings.effective_cors_origins
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Request-ID",
    ],
)


@app.get("/health")
def health_check() -> Any:
    """Readiness probe checking DB, queue, and FFmpeg without exposing sensitive creds."""
    db_ok = False
    in_flight_jobs = 0
    try:
        with db_module.SessionLocal() as session:
            session.execute(text("SELECT 1"))
            db_ok = True
            in_flight_jobs = int(
                session.scalar(
                    select(func.count(VideoJob.id)).where(
                        VideoJob.status.in_(
                            ("CREATED", "QUEUED", "PROCESSING", "RENDERING")
                        )
                    )
                )
                or 0
            )
    except Exception:
        db_ok = False

    ffmpeg_available = False
    try:
        ffmpeg_available = bool(get_ffmpeg_binary())
    except Exception:
        ffmpeg_available = False

    queue_info = check_queue_health(inspect_workers=False)
    payload = {
        "status": "ok" if db_ok else "degraded",
        "service": "localized-video-ad-worker",
        "environment": settings.effective_app_env,
        "database": "ok" if db_ok else "error",
        "ffmpeg_available": ffmpeg_available,
        "veo_model": settings.VEO_MODEL,
        "mock_vertex_veo": settings.is_mock_veo,
        "mock_tts": settings.is_mock_tts,
        "stripe_configured": bool(
            settings.effective_stripe_secret_key and settings.effective_stripe_webhook_secret
        ),
        "in_flight_jobs": in_flight_jobs,
        **queue_info,
    }
    if not db_ok:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    if settings.is_production and (
        not queue_info["redis_broker"] or queue_info["celery_eager_mode"]
    ):
        payload["status"] = "degraded"
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload


@app.get("/v1/ops/metrics")
def ops_metrics(
    request: Request,
    x_admin_secret: str = Header(default="", alias="X-Admin-Secret"),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Operational telemetry endpoint reporting DB, Redis/queue, leases, and latencies."""
    configured_admin = settings.effective_admin_adjust_secret
    has_admin_secret = bool(
        configured_admin
        and x_admin_secret
        and hmac.compare_digest(x_admin_secret.strip(), configured_admin)
    )
    if not has_admin_secret:
        user = get_current_user(request, db)
        if not user.is_admin and settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator authorization is required for ops metrics.",
            )

    t0 = time.perf_counter()
    db.execute(text("SELECT 1"))
    db_latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    now_sql = db_now_expr(db)
    in_flight = int(
        db.scalar(
            select(func.count(VideoJob.id)).where(
                VideoJob.status.in_(("CREATED", "QUEUED", "PROCESSING", "RENDERING"))
            )
        )
        or 0
    )
    active_leases = int(
        db.scalar(
            select(func.count(VideoJob.id)).where(
                VideoJob.status.in_(("PROCESSING", "RENDERING")),
                VideoJob.lease_expires_at > now_sql,
            )
        )
        or 0
    )
    expired_leases = int(
        db.scalar(
            select(func.count(VideoJob.id)).where(
                VideoJob.status.in_(("PROCESSING", "RENDERING")),
                VideoJob.lease_expires_at.is_not(None),
                VideoJob.lease_expires_at <= now_sql,
            )
        )
        or 0
    )
    failed_jobs = int(
        db.scalar(select(func.count(VideoJob.id)).where(VideoJob.status == "FAILED")) or 0
    )
    outbox_pending = int(
        db.scalar(
            select(func.count(JobDispatchOutbox.id)).where(
                JobDispatchOutbox.status.in_(("PENDING", "PUBLISHING"))
            )
        )
        or 0
    )
    outbox_failed = int(
        db.scalar(
            select(func.count(JobDispatchOutbox.id)).where(JobDispatchOutbox.status == "FAILED")
        )
        or 0
    )
    outbox_published = int(
        db.scalar(
            select(func.count(JobDispatchOutbox.id)).where(JobDispatchOutbox.status == "PUBLISHED")
        )
        or 0
    )
    queue_health = check_queue_health(inspect_workers=False)

    return {
        "service": "localized-video-ad-worker",
        "environment": settings.effective_app_env,
        "db_latency_ms": db_latency_ms,
        "rate_limiter_backend": rate_limiter.backend_mode,
        "queue": queue_health,
        "outbox": {
            "pending": outbox_pending,
            "failed": outbox_failed,
            "published": outbox_published,
        },
        "jobs": {
            "in_flight": in_flight,
            "active_leases": active_leases,
            "expired_leases": expired_leases,
            "total_failed": failed_jobs,
        },
        "telemetry": metrics_registry.snapshot(),
    }


# ---------------------------------------------------------------------------
# Authentication & Session Management
# ---------------------------------------------------------------------------


@app.get("/v1/auth/providers")
def auth_providers() -> dict[str, Any]:
    """Advertise enabled authentication methods without leaking credentials."""
    return {
        "google_enabled": settings.is_google_oauth_configured,
        "email_verification_required": settings.effective_require_email_verification,
        "smtp_configured": settings.is_smtp_configured,
    }


@app.post("/v1/auth/register", status_code=status.HTTP_201_CREATED)
def auth_register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_auth_rate_limit(request, payload.email, category="auth_register")
    try:
        user, workspace, verify_token = register_user(
            db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
        )
    except EmailAlreadyRegisteredError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if settings.effective_require_email_verification:
        email_sent = False
        try:
            email_sent = send_verification_email(user.email, verify_token)
        except Exception as exc:
            log_audit_event(
                "verification_email_failed",
                level="WARNING",
                user_id=user.id,
                details={"error": type(exc).__name__},
            )
        db.commit()
        log_audit_event(
            "user_registered_pending_verification",
            user_id=user.id,
            workspace_id=workspace.id,
            ip_address=get_client_ip(request),
            details={"email_sent": email_sent},
        )
        msg = (
            "Verification link sent to your inbox. Check your email or paste "
            "the code below before signing in."
            if email_sent
            else "Account created. Email verification is required before "
            "sign-in (configure SMTP or use Continue with Google)."
        )
        result: dict[str, Any] = {
            "verification_required": True,
            "email_sent": email_sent,
            "email": user.email,
            "primary_workspace_id": workspace.id,
            "message": msg,
        }
        if settings.effective_expose_dev_auth_tokens:
            result["verify_email_token"] = verify_token
        return result

    tokens = issue_session_tokens(
        db,
        user,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=get_client_ip(request),
    )
    db.commit()
    _set_auth_cookies(response, tokens)
    log_audit_event(
        "user_registered",
        user_id=user.id,
        workspace_id=workspace.id,
        ip_address=get_client_ip(request),
    )
    result = {
        **tokens,
        "user": _serialize_user_summary(db, user),
        "primary_workspace_id": workspace.id,
    }
    if settings.effective_expose_dev_auth_tokens:
        result["verify_email_token"] = verify_token
    return result


@app.post("/v1/auth/login")
def auth_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_auth_rate_limit(request, payload.email, category="auth_login")
    try:
        user = authenticate_user(db, email=payload.email, password=payload.password)
        tokens = issue_session_tokens(
            db,
            user,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=get_client_ip(request),
        )
        db.commit()
    except AccountLockedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except EmailNotVerifiedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (InvalidCredentialsError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        ) from exc

    _set_auth_cookies(response, tokens)
    log_audit_event("user_logged_in", user_id=user.id, ip_address=get_client_ip(request))
    return {
        **tokens,
        "user": _serialize_user_summary(db, user),
    }


@app.post("/v1/auth/refresh")
def auth_refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_auth_rate_limit(request)
    raw_refresh = (payload.refresh_token if payload else None) or request.cookies.get(
        REFRESH_COOKIE_NAME
    )
    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is required."
        )

    try:
        user, tokens = rotate_refresh_session(
            db,
            raw_refresh,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=get_client_ip(request),
        )
        db.commit()
    except InvalidCredentialsError as exc:
        _clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    _set_auth_cookies(response, tokens)
    return {
        **tokens,
        "user": _serialize_user_summary(db, user),
    }


@app.post("/v1/auth/logout")
def auth_logout(
    request: Request,
    response: Response,
    payload: LogoutRequest | None = None,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    raw_refresh = (payload.refresh_token if payload else None) or request.cookies.get(
        REFRESH_COOKIE_NAME
    )
    revoke_refresh_session(db, raw_refresh)
    db.commit()
    _clear_auth_cookies(response)
    return {"logged_out": True}


@app.post("/v1/auth/logout-all")
def auth_logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Revoke every active refresh session across all devices for current_user."""
    revoked = revoke_all_user_sessions(db, current_user.id)
    db.commit()
    _clear_auth_cookies(response)
    log_audit_event(
        "user_logged_out_all",
        user_id=current_user.id,
        ip_address=get_client_ip(request),
        details={"revoked_sessions": revoked},
    )
    return {"logged_out_all": True, "revoked_sessions": revoked}


@app.get("/v1/auth/me")
def auth_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    return {"user": _serialize_user_summary(db, current_user)}


@app.post("/v1/auth/verify-email")
def auth_verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_auth_rate_limit(request)
    try:
        user = verify_user_email(db, payload.token)
        tokens = issue_session_tokens(
            db,
            user,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=get_client_ip(request),
        )
        db.commit()
    except InvalidCredentialsError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _set_auth_cookies(response, tokens)
    log_audit_event("email_verified", user_id=user.id, ip_address=get_client_ip(request))
    summary = _serialize_user_summary(db, user)
    primary_ws_id = summary["workspaces"][0]["id"] if summary["workspaces"] else None
    return {
        "verified": True,
        "email": user.email,
        **tokens,
        "user": summary,
        "primary_workspace_id": primary_ws_id,
    }


@app.post("/v1/auth/password-reset/request")
def auth_password_reset_request(
    payload: PasswordResetRequestBody,
    request: Request,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_auth_rate_limit(request, payload.email, category="auth_password_reset")
    try:
        user, raw_token = request_password_reset(db, payload.email)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    resp: dict[str, Any] = {
        "accepted": True,
        "message": "If an account exists for that email, reset instructions have been issued.",
    }
    if user is not None and raw_token is not None and settings.effective_expose_dev_auth_tokens:
        resp["reset_token"] = raw_token
    return resp


@app.post("/v1/auth/password-reset/confirm")
def auth_password_reset_confirm(
    payload: PasswordResetConfirmBody,
    request: Request,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_auth_rate_limit(request, category="auth_password_reset")
    try:
        user = confirm_password_reset(db, payload.token, payload.new_password)
        db.commit()
    except (InvalidCredentialsError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event("password_reset_completed", user_id=user.id, ip_address=get_client_ip(request))
    return {"password_reset": True}


@app.get("/v1/auth/google/start")
def auth_google_start(
    request: Request,
    response: Response,
    mode: Literal["login", "register"] = Query(default="login"),
) -> dict[str, Any]:
    _enforce_auth_rate_limit(request)
    try:
        auth_url, signed_cookie = build_google_oauth_start(mode)
    except GoogleOAuthConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=signed_cookie,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
    return {"authorization_url": auth_url}


@app.post("/v1/auth/google/callback")
def auth_google_callback(
    payload: GoogleCallbackRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_auth_rate_limit(request)
    raw_cookie = request.cookies.get(OAUTH_STATE_COOKIE_NAME, "")
    try:
        state_payload = verify_google_oauth_state_cookie(raw_cookie, payload.state)
        identity = exchange_google_oauth_code(
            code=payload.code,
            code_verifier=str(state_payload.get("code_verifier") or ""),
        )
        user, workspace, is_new = upsert_google_user(
            db,
            google_sub=identity["sub"],
            email=identity["email"],
            full_name=identity["name"],
        )
        tokens = issue_session_tokens(
            db,
            user,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=get_client_ip(request),
        )
        db.commit()
    except GoogleOAuthConfigError as exc:
        db.rollback()
        response.delete_cookie(OAUTH_STATE_COOKIE_NAME, path="/")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except GoogleOAuthError as exc:
        db.rollback()
        response.delete_cookie(OAUTH_STATE_COOKIE_NAME, path="/")
        code = (
            status.HTTP_403_FORBIDDEN
            if "not verified" in str(exc).lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    _set_auth_cookies(response, tokens)
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME, path="/")
    log_audit_event(
        "user_google_authenticated",
        user_id=user.id,
        workspace_id=workspace.id,
        ip_address=get_client_ip(request),
        details={"is_new_user": is_new},
    )
    return {
        **tokens,
        "user": _serialize_user_summary(db, user),
        "primary_workspace_id": workspace.id,
        "is_new_user": is_new,
    }


# ---------------------------------------------------------------------------
# Multi-Tenant Workspaces & RBAC
# ---------------------------------------------------------------------------


@app.get("/v1/workspaces")
def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    return {"workspaces": _serialize_user_summary(db, current_user)["workspaces"]}


@app.post("/v1/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_rate_limit(request, "workspace_create", current_user.id, 20)
    ws = create_workspace_for_user(
        db,
        owner_id=current_user.id,
        name=payload.name,
        grant_initial_promo=False,
        promo_credits=0,
    )
    db.commit()
    log_audit_event("workspace_created", user_id=current_user.id, workspace_id=ws.id)
    return {
        "id": ws.id,
        "name": ws.name,
        "owner_id": ws.owner_id,
        "role": "owner",
        "credit_balance": ws.credit_balance,
        "reserved_balance": ws.reserved_balance,
        "created_at": ws.created_at.isoformat(),
    }


@app.get("/v1/workspaces/{workspace_id}")
def get_workspace(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    ws, member = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role="member",
    )
    ledger_rows = list(
        db.scalars(
            select(CreditLedger)
            .where(CreditLedger.workspace_id == ws.id)
            .order_by(CreditLedger.created_at.desc())
            .limit(50)
        ).all()
    )
    members_rows = db.execute(
        select(WorkspaceMember, User.email, User.full_name)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == ws.id)
    ).all()

    return {
        "id": ws.id,
        "name": ws.name,
        "owner_id": ws.owner_id,
        "role": member.role,
        "credit_balance": ws.credit_balance,
        "reserved_balance": ws.reserved_balance,
        "created_at": ws.created_at.isoformat(),
        "members": [
            {
                "user_id": m.user_id,
                "email": email,
                "full_name": full_name,
                "role": m.role,
                "created_at": m.created_at.isoformat(),
            }
            for m, email, full_name in members_rows
        ],
        "ledger": [
            {
                "id": entry.id,
                "user_id": entry.user_id,
                "job_id": entry.job_id,
                "payment_id": entry.payment_id,
                "transaction_type": entry.transaction_type,
                "amount": entry.amount,
                "delta": entry.delta,
                "previous_balance": entry.previous_balance,
                "new_balance": entry.new_balance,
                "balance_after": entry.balance_after,
                "reason": entry.reason,
                "status": entry.status,
                "metadata": entry.metadata_json,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in ledger_rows
        ],
    }


@app.post("/v1/workspaces/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
def add_workspace_member(
    workspace_id: uuid.UUID,
    payload: AddMemberRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_rate_limit(request, "member_invite", current_user.id, 20)
    required_role = "owner" if payload.role == "admin" else "admin"
    ws, _ = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role=required_role,
    )
    try:
        email = normalize_email(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target_user = db.scalar(select(User).where(User.email == email))
    if target_user is None:
        raise HTTPException(status_code=404, detail="Target user account not found.")

    existing = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == target_user.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="User is already a member of this workspace.")

    member = WorkspaceMember(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        user_id=target_user.id,
        role=payload.role,
        created_at=utcnow(),
    )
    db.add(member)
    db.commit()
    return {
        "workspace_id": ws.id,
        "user_id": target_user.id,
        "email": target_user.email,
        "role": member.role,
    }


@app.patch("/v1/workspaces/{workspace_id}/members/{member_user_id}")
def update_workspace_member_role(
    workspace_id: uuid.UUID,
    member_user_id: uuid.UUID,
    payload: UpdateMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    ws, _ = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role="owner",
    )
    target_id = str(member_user_id)
    if target_id == ws.owner_id:
        raise HTTPException(status_code=400, detail="Cannot downgrade workspace owner role.")
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == target_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found in workspace.")
    member.role = payload.role
    db.commit()
    return {"workspace_id": ws.id, "user_id": target_id, "role": member.role}


@app.delete("/v1/workspaces/{workspace_id}/members/{member_user_id}")
def remove_workspace_member(
    workspace_id: uuid.UUID,
    member_user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Remove a non-owner workspace member enforcing RBAC hierarchy."""
    ws, actor_member = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role="admin",
    )
    target_id = str(member_user_id)
    if target_id == ws.owner_id:
        raise HTTPException(status_code=400, detail="Cannot remove the workspace owner.")

    target_member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == target_id,
        )
    )
    if target_member is None:
        raise HTTPException(status_code=404, detail="Member not found in workspace.")
    if target_member.role == "admin" and actor_member.role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Only the workspace owner can remove an admin.",
        )

    db.delete(target_member)
    db.commit()
    log_audit_event(
        "workspace_member_removed",
        user_id=current_user.id,
        workspace_id=ws.id,
        ip_address=get_client_ip(request),
        details={"removed_user_id": target_id},
    )
    return {"removed": True, "workspace_id": ws.id, "user_id": target_id}


# ---------------------------------------------------------------------------
# Credit Packages, Stripe Checkout, Webhooks & Controlled Admin Adjustments
# ---------------------------------------------------------------------------


@app.get("/v1/workspaces/{workspace_id}/credits/reconcile")
def reconcile_workspace_credit_ledger(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Verify Workspace credit balance invariants against immutable CreditLedger rows."""
    ws, _ = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role="member",
    )
    return reconcile_workspace_credits(db, ws.id)


@app.get("/v1/billing/packages")
def list_credit_packages() -> dict[str, Any]:
    return {"packages": get_public_credit_packages()}


@app.post("/v1/workspaces/{workspace_id}/credits/checkout")
def checkout_credits(
    workspace_id: uuid.UUID,
    payload: CreditCheckoutRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_rate_limit(
        request,
        "billing_checkout",
        current_user.id,
        settings.get_rate_limit("billing_checkout"),
        burst_limit=max(5, settings.get_rate_limit("billing_checkout") // 2),
    )
    ws, _ = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role="member",
    )
    try:
        session_info = create_stripe_checkout_session(
            workspace=ws,
            user=current_user,
            pack_id=payload.pack_id,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
        )
    except BillingConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    metrics_registry.incr("billing.checkout_created")
    return {
        "id": ws.id,
        "checkout_mode": "stripe_checkout_session",
        **session_info,
    }


@app.post("/v1/billing/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        return process_stripe_webhook(
            db,
            raw_body=raw_body,
            signature_header=stripe_signature,
        )
    except BillingConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except WebhookSignatureError as exc:
        log_audit_event(
            "stripe_webhook_signature_rejected",
            level="WARNING",
            ip_address=get_client_ip(request),
            details={"reason": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WebhookValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/v1/workspaces/{workspace_id}/credits/admin-adjust")
def admin_adjust_credits(
    workspace_id: uuid.UUID,
    payload: AdminCreditAdjustRequest,
    request: Request,
    x_admin_secret: str = Header(default="", alias="X-Admin-Secret"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    configured_secret = settings.effective_admin_adjust_secret
    has_secret = bool(
        configured_secret
        and x_admin_secret
        and hmac.compare_digest(x_admin_secret.strip(), configured_secret)
    )
    if not current_user.is_admin and not has_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Explicit platform administrator authorization is required "
                "for manual credit adjustments."
            ),
        )

    ws = db.get(Workspace, str(workspace_id))
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    if payload.delta == 0:
        raise HTTPException(status_code=400, detail="delta cannot be zero.")

    try:
        new_balance = adjust_credits_atomically(
            db,
            workspace_id=ws.id,
            delta=payload.delta,
            transaction_type="admin_adjustment",
            reason=payload.reason.strip(),
            user_id=current_user.id,
            metadata={"admin_actor_email": current_user.email},
        )
        db.commit()
    except InsufficientCreditsError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    log_audit_event(
        "admin_credit_adjustment",
        user_id=current_user.id,
        workspace_id=ws.id,
        ip_address=get_client_ip(request),
        details={"delta": payload.delta, "new_balance": new_balance, "reason": payload.reason},
    )
    return {"workspace_id": ws.id, "credit_balance": new_balance, "delta": payload.delta}


@app.post("/v1/workspaces/{workspace_id}/credits/dev-topup")
def dev_only_topup(
    workspace_id: uuid.UUID,
    payload: DevTopupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Explicitly disabled in production and disabled unless ENABLE_DEV_TOPUP=true locally."""
    if settings.is_production or not settings.effective_enable_dev_topup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development top-up is disabled.",
        )
    ws, _ = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role="admin",
    )
    pack_credits = {"starter_10": 10, "growth_50": 50, "scale_200": 200}[payload.pack_id]
    new_balance = add_credits_atomically(
        db,
        workspace_id=ws.id,
        credits=pack_credits,
        transaction_type="promo_bonus",
        reason=f"Local development top-up ({payload.pack_id})",
        user_id=current_user.id,
        metadata={"dev_only": True},
    )
    db.commit()
    return {
        "id": ws.id,
        "credit_balance": new_balance,
        "added_credits": pack_credits,
        "pack_id": payload.pack_id,
        "checkout_mode": "local_dev_topup",
    }


# ---------------------------------------------------------------------------
# Workspace Private Asset Uploads & Retrieval
# ---------------------------------------------------------------------------


def _extract_uploaded_asset_payload(
    content_type: str,
    body: bytes,
    header_filename: str | None = None,
) -> tuple[str, bytes]:
    ct = (content_type or "").lower()
    if "multipart/form-data" in ct:
        safe_ct = (content_type or "").replace("\r", " ").replace("\n", " ").strip()
        mime_msg = BytesParser(policy=email_default_policy).parsebytes(
            f"Content-Type: {safe_ct}\r\nMIME-Version: 1.0\r\n\r\n".encode(
                "latin-1", errors="ignore"
            )
            + body
        )
        if mime_msg.is_multipart():
            for part in mime_msg.iter_parts():
                part_bytes = part.get_payload(decode=True)
                if isinstance(part_bytes, bytes) and len(part_bytes) > 0:
                    return part.get_filename() or header_filename or "product.png", part_bytes
        raise ValueError("Multipart payload did not contain an uploaded file part.")

    if "application/json" in ct:
        parsed = json.loads(body.decode("utf-8"))
        b64 = str(parsed.get("content_base64") or "").strip()
        if not b64:
            raise ValueError("Missing content_base64 field.")
        fname = str(parsed.get("filename") or header_filename or "product.png")
        return fname, base64.b64decode(b64)

    return header_filename or "product.png", body


@app.post("/v1/workspaces/{workspace_id}/assets", status_code=status.HTTP_201_CREATED)
async def upload_workspace_asset(
    workspace_id: uuid.UUID,
    request: Request,
    x_filename: str | None = Header(default=None, alias="X-Filename"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_rate_limit(request, "asset_upload", current_user.id, 30)
    ws, _ = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role="member",
    )
    raw_body = await request.body()
    try:
        filename, raw = _extract_uploaded_asset_payload(
            request.headers.get("content-type", ""),
            raw_body,
            header_filename=x_filename,
        )
        mime, _ = validate_image_bytes(raw)
        asset = register_workspace_file(
            db,
            workspace_id=ws.id,
            user_id=current_user.id,
            asset_kind="product_image",
            filename=filename,
            content_type=mime,
            data=raw,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {
        "id": asset.id,
        "workspace_id": asset.workspace_id,
        "asset_kind": asset.asset_kind,
        "filename": asset.filename,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "sha256": asset.sha256,
        "created_at": asset.created_at.isoformat(),
    }


@app.get("/v1/workspaces/{workspace_id}/assets")
def list_workspace_assets(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    ws, _ = require_workspace_role(
        db,
        workspace_id=str(workspace_id),
        user=current_user,
        minimum_role="member",
    )
    assets = list(
        db.scalars(
            select(WorkspaceAsset)
            .where(WorkspaceAsset.workspace_id == ws.id)
            .order_by(WorkspaceAsset.created_at.desc())
            .limit(100)
        ).all()
    )
    return {
        "assets": [
            {
                "id": a.id,
                "asset_kind": a.asset_kind,
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at.isoformat(),
            }
            for a in assets
        ]
    }


@app.get("/v1/assets/{asset_id}")
def download_workspace_asset(
    asset_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> FileResponse:
    _enforce_rate_limit(
        request,
        "file_download",
        current_user.id,
        settings.get_rate_limit("file_download"),
    )
    asset = db.get(WorkspaceAsset, str(asset_id))
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")

    require_workspace_role(
        db,
        workspace_id=asset.workspace_id,
        user=current_user,
        minimum_role="member",
    )
    try:
        path = resolve_workspace_rel_path(asset.workspace_id, asset.storage_rel_path)
    except StorageError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored asset file is missing.")
    return FileResponse(path=path, media_type=asset.content_type, filename=asset.filename)


# ---------------------------------------------------------------------------
# Product Scraper & Workspace-Isolated Video Jobs
# ---------------------------------------------------------------------------


@app.post("/v1/products/scrape")
def scrape_product(
    payload: ScrapeProductRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _enforce_rate_limit(
        request,
        "product_scrape",
        current_user.id,
        settings.get_rate_limit("product_scrape"),
        burst_limit=max(10, settings.get_rate_limit("product_scrape") // 2),
    )
    try:
        return scrape_product_url(
            product_url=str(payload.product_url),
            target_language=payload.target_language,
        )
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post(
    "/v1/videos/generate",
    response_model=VideoJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_video(
    payload: GenerateVideoRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> VideoJobResponse:
    _enforce_rate_limit(
        request,
        "video_generate",
        current_user.id,
        settings.get_rate_limit("video_generate"),
        burst_limit=max(20, settings.get_rate_limit("video_generate")),
    )
    ws, _ = require_workspace_role(
        db,
        workspace_id=str(payload.workspace_id),
        user=current_user,
        minimum_role="member",
    )

    resolved_idem = (idempotency_key or payload.idempotency_key or "").strip() or None
    if resolved_idem is not None and not re.match(r"^[A-Za-z0-9._:-]{1,128}$", resolved_idem):
        raise HTTPException(status_code=400, detail="Invalid Idempotency-Key format.")

    if resolved_idem is not None:
        existing_job = db.scalar(
            select(VideoJob).where(
                VideoJob.workspace_id == ws.id,
                VideoJob.idempotency_key == resolved_idem,
            )
        )
        if existing_job is not None:
            return _serialize_job(existing_job, credit_balance=ws.credit_balance)

    if payload.simulate_failure and settings.is_production:
        raise HTTPException(
            status_code=400,
            detail="Failure simulation is disabled in production.",
        )

    try:
        validate_public_http_url(str(payload.product_url))
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not settings.is_mock_veo and int(round(payload.duration_seconds)) not in (4, 6, 8):
        raise HTTPException(
            status_code=400,
            detail="Live Vertex AI Veo supports duration_seconds values of 4, 6, or 8.",
        )

    correlation_id = getattr(request.state, "request_id", None)
    job_id = str(uuid.uuid4())
    now = utcnow()
    job = VideoJob(
        id=job_id,
        workspace_id=ws.id,
        user_id=current_user.id,
        product_url=str(payload.product_url),
        target_language=payload.target_language,
        aspect_ratio=payload.aspect_ratio,
        duration_seconds=int(round(payload.duration_seconds)),
        idempotency_key=resolved_idem,
        correlation_id=str(correlation_id)[:64] if correlation_id else None,
        status="CREATED",
        progress_pct=5,
        stage_detail="Created — reserving workspace credit",
        reserved_credits=1,
        script_json={"status_history": ["CREATED"]},
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(job)
        db.flush()
    except IntegrityError:
        db.rollback()
        if resolved_idem is not None:
            existing_job = db.scalar(
                select(VideoJob).where(
                    VideoJob.workspace_id == ws.id,
                    VideoJob.idempotency_key == resolved_idem,
                )
            )
            if existing_job is not None:
                ws_cur = db.get(Workspace, ws.id)
                return _serialize_job(
                    existing_job, credit_balance=ws_cur.credit_balance if ws_cur else None
                )
        raise

    try:
        reserve_credit_atomically(
            db,
            workspace_id=ws.id,
            job_id=job_id,
            user_id=current_user.id,
            cost=1,
            reason=f"Reserved 1 credit for video job {job_id}",
        )
    except InsufficientCreditsError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Insufficient credits in workspace. Please purchase credits "
                "to generate a video."
            ),
        ) from exc

    outbox_event = create_dispatch_outbox_event(
        db,
        job_id=job_id,
        workspace_id=ws.id,
        payload={
            "job_id": job_id,
            "ad_angle": payload.ad_angle,
            "simulate_failure": payload.simulate_failure,
            "custom_props": payload.custom_props,
            "duration_seconds": payload.duration_seconds,
            "aspect_ratio": payload.aspect_ratio,
            "correlation_id": str(correlation_id)[:64] if correlation_id else None,
        },
    )
    db.commit()

    try:
        publish_outbox_event(outbox_event.id, fail_job_on_broker_error=True)
    except (BrokerUnavailableError, Exception) as exc:
        metrics_registry.incr("jobs.dispatch_failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background render queue unavailable; reserved credit has been refunded.",
        ) from exc

    db.expire_all()
    updated_job = db.get(VideoJob, job_id)
    updated_ws = db.get(Workspace, ws.id)
    assert updated_job is not None
    return _serialize_job(
        updated_job, credit_balance=updated_ws.credit_balance if updated_ws else None
    )


@app.get("/v1/videos", response_model=list[VideoJobResponse])
def list_videos(
    workspace_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[VideoJobResponse]:
    """List video jobs strictly scoped to workspaces owned or joined by current_user."""
    if workspace_id is not None:
        ws, _ = require_workspace_role(
            db,
            workspace_id=str(workspace_id),
            user=current_user,
            minimum_role="member",
        )
        stmt = (
            select(VideoJob)
            .where(VideoJob.workspace_id == ws.id)
            .order_by(VideoJob.created_at.desc())
            .limit(100)
        )
        jobs = list(db.scalars(stmt).all())
        return [_serialize_job(j, credit_balance=ws.credit_balance) for j in jobs]

    member_ws_ids = list(
        db.scalars(
            select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == current_user.id)
        ).all()
    )
    if not member_ws_ids:
        return []
    stmt = (
        select(VideoJob)
        .where(VideoJob.workspace_id.in_(member_ws_ids))
        .order_by(VideoJob.created_at.desc())
        .limit(100)
    )
    jobs = list(db.scalars(stmt).all())
    return [_serialize_job(j) for j in jobs]


@app.get("/v1/videos/{job_id}", response_model=VideoJobResponse)
def get_video_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> VideoJobResponse:
    job = db.get(VideoJob, str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Video job not found.")

    ws, _ = require_workspace_role(
        db,
        workspace_id=job.workspace_id,
        user=current_user,
        minimum_role="member",
    )
    return _serialize_job(job, credit_balance=ws.credit_balance)


@app.post("/v1/videos/{job_id}/cancel", response_model=VideoJobResponse)
def cancel_video_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> VideoJobResponse:
    job = db.get(VideoJob, str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Video job not found.")
    ws, _ = require_workspace_role(
        db,
        workspace_id=job.workspace_id,
        user=current_user,
        minimum_role="member",
    )
    now_sql = db_now_expr(db)
    upd = db.execute(
        update(VideoJob)
        .where(
            VideoJob.id == job.id,
            VideoJob.status.notin_(("COMPLETED", "FAILED", "CANCELLED")),
        )
        .values(
            status="CANCELLED",
            stage_detail="Cancelled by customer — reserved credit refunded",
            worker_id=None,
            lease_expires_at=None,
            fencing_token=VideoJob.fencing_token + 1,
            updated_at=now_sql,
        )
    )
    if int(getattr(upd, "rowcount", 0) or 0) != 1:
        db.rollback()
        latest = db.get(VideoJob, job.id)
        cur_status = latest.status if latest else "UNKNOWN"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel job in terminal status '{cur_status}'.",
        )
    db.execute(
        update(JobDispatchOutbox)
        .where(
            JobDispatchOutbox.job_id == job.id,
            JobDispatchOutbox.status.in_(("PENDING", "PUBLISHING")),
        )
        .values(status="CANCELLED", updated_at=now_sql)
    )
    refund_credit_atomically(
        db,
        workspace_id=ws.id,
        job_id=job.id,
        user_id=current_user.id,
        cost=int(job.reserved_credits or 1),
        reason="Customer cancelled queued/in-progress job",
    )
    db.commit()
    db.expire_all()
    cancelled_job = db.get(VideoJob, job.id)
    updated_ws = db.get(Workspace, ws.id)
    assert cancelled_job is not None
    return _serialize_job(
        cancelled_job, credit_balance=updated_ws.credit_balance if updated_ws else None
    )


@app.post(
    "/v1/videos/{job_id}/retry",
    response_model=VideoJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_video_job(
    job_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> VideoJobResponse:
    _enforce_rate_limit(
        request,
        "video_render_retry",
        current_user.id,
        settings.get_rate_limit("video_render_retry"),
    )
    prev_job = db.get(VideoJob, str(job_id))
    if prev_job is None:
        raise HTTPException(status_code=404, detail="Video job not found.")
    require_workspace_role(
        db,
        workspace_id=prev_job.workspace_id,
        user=current_user,
        minimum_role="member",
    )
    if prev_job.status not in ("FAILED", "CANCELLED"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only FAILED or CANCELLED jobs can be retried.",
        )

    prev_script = prev_job.script_json or {}
    retry_custom = (
        {"veoPrompt": str(prev_script["veo_prompt"])}
        if prev_script.get("veo_prompt")
        else None
    )
    retry_payload = GenerateVideoRequest(
        workspace_id=uuid.UUID(prev_job.workspace_id),
        product_url=prev_job.product_url,  # type: ignore[arg-type]
        target_language=prev_job.target_language,  # type: ignore[arg-type]
        ad_angle=str(prev_script.get("ad_angle") or "problem_solution"),
        aspect_ratio=prev_job.aspect_ratio or "9:16",  # type: ignore[arg-type]
        duration_seconds=float(prev_job.duration_seconds or 4),
        custom_props=retry_custom,
    )
    return generate_video(
        payload=retry_payload,
        request=request,
        idempotency_key=None,
        current_user=current_user,
        db=db,
    )


@app.get("/v1/videos/{job_id}/signed-url")
def get_signed_video_url(
    job_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    _enforce_rate_limit(
        request,
        "file_download",
        current_user.id,
        settings.get_rate_limit("file_download"),
    )
    job = db.get(VideoJob, str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Video job not found.")
    ws, _ = require_workspace_role(
        db,
        workspace_id=job.workspace_id,
        user=current_user,
        minimum_role="member",
    )
    if job.status != "COMPLETED" or not job.storage_rel_path:
        raise HTTPException(status_code=409, detail="Rendered video is not completed yet.")

    token, exp = create_signed_download_token(job_id=job.id, workspace_id=ws.id)
    return {
        "job_id": job.id,
        "download_path": f"/v1/videos/{job.id}/download?token={token}",
        "expires_at": exp,
    }


@app.get("/v1/videos/{job_id}/download")
def download_video_render(
    job_id: uuid.UUID,
    request: Request,
    token: str | None = Query(default=None),
    db: Session = Depends(get_session),
) -> FileResponse:
    """Stream completed video strictly from workspace private storage after authorization."""
    _enforce_rate_limit(
        request,
        "file_download",
        get_client_ip(request),
        settings.get_rate_limit("file_download"),
    )
    job = db.get(VideoJob, str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Video job not found.")

    if token:
        if not verify_signed_download_token(
            token=token, job_id=job.id, workspace_id=job.workspace_id
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired signed download token.")
    else:
        user = get_current_user(request, db)
        require_workspace_role(
            db,
            workspace_id=job.workspace_id,
            user=user,
            minimum_role="member",
        )

    if job.status != "COMPLETED" or not job.storage_rel_path:
        raise HTTPException(status_code=404, detail="Rendered video is not available for this job.")

    try:
        file_path = resolve_workspace_rel_path(job.workspace_id, job.storage_rel_path)
    except StorageError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Rendered MP4 artifact not found on storage.")

    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=f"ad-{job.id}.mp4",
    )


__all__ = ["app", "db_module"]
