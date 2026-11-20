"""Celery application, reliable broker enforcement, lease recovery, and render pipeline."""

from __future__ import annotations

import importlib.util
import os
import random
import threading
import time
import uuid
from typing import Any

import httpx
from celery import Celery
from celery.exceptions import Retry as CeleryRetry
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import and_, or_, select, update

import app.db as db_module
from app.compositor import composite_final_video
from app.config import is_redis_reachable, settings
from app.db import (
    ACTIVE_EXECUTION_STATUSES,
    JobDispatchOutbox,
    VideoJob,
    WorkspaceAsset,
    acquire_job_lease,
    db_dialect_name,
    db_now_expr,
    db_offset_expr,
    finalize_credit_deduction,
    refund_credit_atomically,
    release_job_lease,
    renew_job_lease,
)
from app.scraper import (
    UnsafeUrlError,
    download_and_validate_product_image,
    scrape_product_url,
    validate_image_bytes,
)
from app.security import log_audit_event, metrics_registry
from app.storage import (
    get_workspace_subdir,
    register_workspace_file,
    resolve_workspace_rel_path,
    validate_mp4_file,
)
from app.tts import TTSProviderError, generate_localized_script, synthesize_voiceover_wav
from app.veo import VeoClient, VeoConfigurationError, VeoProviderError, VeoValidationError


class BrokerUnavailableError(RuntimeError):
    """Raised when Redis broker or required Celery workers are unavailable."""


class TransientJobError(RuntimeError):
    """Raised for transient external/infrastructure errors eligible for jittered retry."""


class PermanentJobError(RuntimeError):
    """Raised for non-retryable validation or policy errors."""


class StaleWorkerLeaseError(RuntimeError):
    """Raised when a worker attempts to mutate a job after losing its fencing lease."""


def configure_celery_app(target_app: Celery | None = None) -> dict[str, Any]:
    """Configure Celery strictly according to environment rules (never silent fallback in prod)."""
    app_obj = target_app if target_app is not None else celery_app
    require_redis = settings.effective_require_redis_broker
    redis_url = settings.effective_redis_url
    force_eager = os.environ.get("CELERY_ALWAYS_EAGER", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if settings.is_production and force_eager:
        raise RuntimeError(
            "CELERY_ALWAYS_EAGER cannot be enabled in production; dedicated workers are required."
        )

    if require_redis:
        if not redis_url or not redis_url.startswith(("redis://", "rediss://")):
            raise BrokerUnavailableError(
                "REDIS_URL must be configured with redis:// or rediss:// when Redis is required."
            )
        broker_url = redis_url
        backend_url = redis_url
        always_eager = False
    else:
        redis_up = (not force_eager) and is_redis_reachable(redis_url)
        broker_url = redis_url if redis_up else "memory://"
        backend_url = redis_url if redis_up else "cache+memory://"
        always_eager = not redis_up

    app_obj.conf.update(
        broker_url=broker_url,
        result_backend=backend_url,
        task_always_eager=always_eager,
        task_eager_propagates=False,
        task_ignore_result=always_eager,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        task_soft_time_limit=settings.effective_job_soft_time_limit_seconds,
        task_time_limit=settings.effective_job_hard_time_limit_seconds,
        broker_connection_retry_on_startup=False,
        broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 5},
    )
    return {
        "broker_url": broker_url,
        "task_always_eager": always_eager,
        "require_redis": require_redis,
    }


celery_app = Celery("localized_video_ad_worker")
if not settings.is_production:
    configure_celery_app(celery_app)
else:
    # Configure broker URL cleanly even if validated at FastAPI lifespan or worker startup.
    _prod_redis = settings.effective_redis_url or "redis://localhost:6379/0"
    celery_app.conf.update(
        broker_url=_prod_redis,
        result_backend=_prod_redis,
        task_always_eager=False,
        task_eager_propagates=False,
        task_ignore_result=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        task_soft_time_limit=settings.effective_job_soft_time_limit_seconds,
        task_time_limit=settings.effective_job_hard_time_limit_seconds,
        broker_connection_retry_on_startup=False,
        broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 5},
    )


def compute_retry_countdown(
    retry_attempt: int,
    *,
    base_delay: float | None = None,
    max_delay: float | None = None,
) -> float:
    """Compute bounded exponential backoff with randomized jitter."""
    b = (
        float(base_delay)
        if base_delay is not None
        else settings.effective_job_retry_base_delay_seconds
    )
    m = (
        float(max_delay)
        if max_delay is not None
        else settings.effective_job_retry_max_delay_seconds
    )
    cap = min(max(0.05, m), max(0.05, b) * (2 ** max(0, int(retry_attempt))))
    return round(cap * random.uniform(0.5, 1.0), 3)


def is_retryable_exception(exc: Exception) -> bool:
    """Classify transient infrastructure/provider failures separately from permanent errors."""
    if isinstance(
        exc,
        (
            PermanentJobError,
            ValueError,
            StaleWorkerLeaseError,
            UnsafeUrlError,
            VeoValidationError,
            VeoConfigurationError,
        ),
    ):
        return False
    msg = str(exc).lower()
    if "pipeline_simulated_failure" in msg:
        return False
    if isinstance(
        exc,
        (
            TransientJobError,
            httpx.TimeoutException,
            httpx.TransportError,
            TimeoutError,
            ConnectionError,
            SoftTimeLimitExceeded,
        ),
    ):
        return True
    if isinstance(exc, (VeoProviderError, TTSProviderError)):
        transient_markers = (
            "timeout",
            "timed out",
            "429",
            "500",
            "502",
            "503",
            "504",
            "temporarily unavailable",
            "connection",
            "transient",
        )
        return any(marker in msg for marker in transient_markers)
    return False


def check_queue_health(*, inspect_workers: bool = False) -> dict[str, Any]:
    """Inspect Redis broker reachability, queue depth, and optional Celery worker presence."""
    redis_url = settings.effective_redis_url
    redis_reachable = is_redis_reachable(redis_url)
    eager_mode = bool(celery_app.conf.task_always_eager)
    require_redis = settings.effective_require_redis_broker
    queue_depth: int | None = None
    active_workers: int | None = None

    if redis_reachable and redis_url.startswith(("redis://", "rediss://")):
        if importlib.util.find_spec("redis") is not None:
            try:
                import redis  # type: ignore[import-not-found]

                client = redis.Redis.from_url(
                    redis_url, socket_connect_timeout=0.4, socket_timeout=0.5
                )
                queue_depth = int(client.llen("celery"))
            except Exception:
                queue_depth = None

    if inspect_workers and not eager_mode and redis_reachable:
        try:
            pings = celery_app.control.inspect(timeout=0.75).ping() or {}
            active_workers = len(pings)
        except Exception:
            active_workers = 0

    return {
        "redis_broker": redis_reachable,
        "celery_eager_mode": eager_mode,
        "require_redis_broker": require_redis,
        "queue_depth": queue_depth,
        "active_workers": active_workers,
    }


def dispatch_video_job(
    *,
    job_id: str,
    ad_angle: str = "problem_solution",
    simulate_failure: bool = False,
    custom_props: dict[str, Any] | None = None,
    duration_seconds: float = 4.0,
    aspect_ratio: str = "9:16",
    correlation_id: str | None = None,
) -> str:
    """Enqueue a video job safely; fail closed when Redis/workers are required but down."""
    eager = bool(celery_app.conf.task_always_eager)
    if settings.is_production and eager:
        raise BrokerUnavailableError(
            "In-process eager task execution is forbidden in production."
        )

    must_use_redis = settings.effective_require_redis_broker or not eager
    if must_use_redis and not is_redis_reachable(settings.effective_redis_url):
        raise BrokerUnavailableError(
            "Background Redis broker is unavailable; job cannot be queued safely."
        )

    if settings.effective_require_active_celery_worker:
        if eager:
            raise BrokerUnavailableError("Dedicated Celery worker is required.")
        try:
            pings = celery_app.control.inspect(timeout=1.0).ping()
        except Exception as exc:
            raise BrokerUnavailableError(
                f"Failed to verify active Celery workers: {type(exc).__name__}"
            ) from exc
        if not pings:
            raise BrokerUnavailableError("No active Celery workers are connected to the queue.")

    process_video_job.delay(
        job_id=job_id,
        ad_angle=ad_angle,
        simulate_failure=simulate_failure,
        custom_props=custom_props,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        correlation_id=correlation_id,
    )
    return "eager" if eager else "queued"


def _apply_outbox_dispatch_failure(
    *,
    outbox_id: str,
    job_id: str,
    exc: Exception,
    attempts: int,
    max_attempts: int,
    fail_job_on_broker_error: bool,
) -> dict[str, Any]:
    """Handle broker/dispatch errors with bounded backoff retries or terminal refund."""
    err_text = str(exc)[:400] or type(exc).__name__
    err_code = (
        "BROKER_UNAVAILABLE" if isinstance(exc, BrokerUnavailableError) else "QUEUE_DISPATCH_FAILED"
    )
    should_fail_terminal = fail_job_on_broker_error or attempts >= max_attempts

    with db_module.SessionLocal() as session:
        now_sql = db_now_expr(session)
        job = session.get(VideoJob, job_id)
        if not should_fail_terminal:
            backoff_s = min(60.0, float(2.0 * (2 ** max(0, attempts - 1))))
            next_at_sql = db_offset_expr(session, backoff_s)
            if job is not None and job.status == "QUEUED" and job.worker_id is None:
                session.execute(
                    update(VideoJob)
                    .where(
                        VideoJob.id == job_id,
                        VideoJob.status == "QUEUED",
                        VideoJob.worker_id.is_(None),
                    )
                    .values(
                        status="CREATED",
                        stage_detail="Waiting to publish dispatch event to queue",
                        updated_at=now_sql,
                    )
                )
            session.execute(
                update(JobDispatchOutbox)
                .where(JobDispatchOutbox.id == outbox_id)
                .values(
                    status="PENDING",
                    next_attempt_at=next_at_sql,
                    last_error=err_text,
                    updated_at=now_sql,
                )
            )
            session.commit()
            metrics_registry.incr("outbox.retried")
            return {
                "status": "retry_scheduled",
                "outbox_id": outbox_id,
                "job_id": job_id,
                "attempts": attempts,
                "error": err_text,
            }

        session.execute(
            update(JobDispatchOutbox)
            .where(JobDispatchOutbox.id == outbox_id)
            .values(status="FAILED", last_error=err_text, updated_at=now_sql)
        )
        if job is not None:
            hist = list((job.script_json or {}).get("status_history") or ["CREATED", "QUEUED"])
            if "FAILED" not in hist:
                hist.append("FAILED")
            next_script = dict(job.script_json or {})
            next_script["status_history"] = hist
            upd_fail = session.execute(
                update(VideoJob)
                .where(
                    VideoJob.id == job_id,
                    VideoJob.status.in_(("CREATED", "QUEUED", "PENDING")),
                    VideoJob.worker_id.is_(None),
                )
                .values(
                    status="FAILED",
                    progress_pct=0,
                    error_code=(
                        err_code if fail_job_on_broker_error else "OUTBOX_DISPATCH_EXHAUSTED"
                    ),
                    error_message="Could not enqueue background render job; credit refunded.",
                    stage_detail="Dispatch failed — credit refunded",
                    fencing_token=VideoJob.fencing_token + 1,
                    script_json=next_script,
                    updated_at=now_sql,
                )
            )
            if int(upd_fail.rowcount or 0) == 1:
                refund_credit_atomically(
                    session,
                    workspace_id=job.workspace_id,
                    job_id=job_id,
                    user_id=job.user_id,
                    cost=int(job.reserved_credits or 1),
                    reason=f"Queue dispatch failed: {type(exc).__name__}",
                )
        session.commit()

    metrics_registry.incr("outbox.failed")
    if fail_job_on_broker_error:
        raise exc
    return {
        "status": "failed",
        "outbox_id": outbox_id,
        "job_id": job_id,
        "attempts": attempts,
        "error": err_text,
    }


def publish_outbox_event(
    outbox_id: str | uuid.UUID,
    *,
    fail_job_on_broker_error: bool = False,
) -> dict[str, Any]:
    """Claim and dispatch a single durable outbox event idempotently."""
    outbox_str = str(uuid.UUID(str(outbox_id)))
    with db_module.SessionLocal() as session:
        now_sql = db_now_expr(session)
        stale_pub_cutoff = db_offset_expr(session, -60.0)
        claim_stmt = (
            update(JobDispatchOutbox)
            .where(
                JobDispatchOutbox.id == outbox_str,
                or_(
                    and_(
                        JobDispatchOutbox.status == "PENDING",
                        JobDispatchOutbox.next_attempt_at <= now_sql,
                    ),
                    and_(
                        JobDispatchOutbox.status == "PUBLISHING",
                        JobDispatchOutbox.updated_at <= stale_pub_cutoff,
                    ),
                ),
            )
            .values(
                status="PUBLISHING",
                attempts=JobDispatchOutbox.attempts + 1,
                updated_at=now_sql,
            )
            .returning(
                JobDispatchOutbox.job_id,
                JobDispatchOutbox.workspace_id,
                JobDispatchOutbox.payload_json,
                JobDispatchOutbox.attempts,
                JobDispatchOutbox.max_attempts,
            )
        )
        claimed = session.execute(claim_stmt).fetchone()
        if claimed is None:
            session.commit()
            return {"status": "skipped", "outbox_id": outbox_str}

        job_id = str(claimed[0])
        payload = dict(claimed[2] or {})
        attempts = int(claimed[3] or 1)
        max_attempts = int(claimed[4] or 5)

        job = session.get(VideoJob, job_id)
        if job is None or job.status in ("COMPLETED", "FAILED", "CANCELLED"):
            session.execute(
                update(JobDispatchOutbox)
                .where(JobDispatchOutbox.id == outbox_str)
                .values(status="CANCELLED", updated_at=now_sql)
            )
            session.commit()
            metrics_registry.incr("outbox.cancelled")
            return {"status": "cancelled", "outbox_id": outbox_str, "job_id": job_id}

        next_script = dict(job.script_json or {})
        hist = list(next_script.get("status_history") or ["CREATED"])
        if "QUEUED" not in hist:
            hist.append("QUEUED")
        next_script["status_history"] = hist

        session.execute(
            update(VideoJob)
            .where(VideoJob.id == job_id, VideoJob.status == "CREATED")
            .values(
                status="QUEUED",
                progress_pct=10,
                stage_detail="Queued for AI generation & rendering",
                script_json=next_script,
                updated_at=now_sql,
            )
        )
        session.commit()

    try:
        dispatch_mode = dispatch_video_job(
            job_id=job_id,
            ad_angle=str(payload.get("ad_angle") or "problem_solution"),
            simulate_failure=bool(payload.get("simulate_failure", False)),
            custom_props=payload.get("custom_props"),
            duration_seconds=float(payload.get("duration_seconds") or 4.0),
            aspect_ratio=str(payload.get("aspect_ratio") or "9:16"),
            correlation_id=payload.get("correlation_id"),
        )
    except Exception as exc:
        return _apply_outbox_dispatch_failure(
            outbox_id=outbox_str,
            job_id=job_id,
            exc=exc,
            attempts=attempts,
            max_attempts=max_attempts,
            fail_job_on_broker_error=fail_job_on_broker_error,
        )

    with db_module.SessionLocal() as session:
        now_sql = db_now_expr(session)
        session.execute(
            update(JobDispatchOutbox)
            .where(JobDispatchOutbox.id == outbox_str, JobDispatchOutbox.status == "PUBLISHING")
            .values(
                status="PUBLISHED",
                published_at=now_sql,
                last_error=None,
                updated_at=now_sql,
            )
        )
        session.commit()
    metrics_registry.incr("outbox.published")
    return {
        "status": "published",
        "outbox_id": outbox_str,
        "job_id": job_id,
        "dispatch_mode": dispatch_mode,
    }


def reconcile_dispatch_outbox(*, limit: int = 50) -> dict[str, int]:
    """Publish pending or stalled transactional outbox rows reliably without double-dispatching."""
    counts = {"published": 0, "retried": 0, "failed": 0, "cancelled": 0, "skipped": 0}
    with db_module.SessionLocal() as session:
        now_sql = db_now_expr(session)
        stale_pub_cutoff = db_offset_expr(session, -60.0)
        stmt = (
            select(JobDispatchOutbox.id)
            .where(
                or_(
                    and_(
                        JobDispatchOutbox.status == "PENDING",
                        JobDispatchOutbox.next_attempt_at <= now_sql,
                    ),
                    and_(
                        JobDispatchOutbox.status == "PUBLISHING",
                        JobDispatchOutbox.updated_at <= stale_pub_cutoff,
                    ),
                )
            )
            .order_by(JobDispatchOutbox.created_at.asc())
            .limit(max(1, int(limit)))
        )
        outbox_ids = [str(oid) for oid in session.scalars(stmt).all()]

    for outbox_id in outbox_ids:
        res = publish_outbox_event(outbox_id, fail_job_on_broker_error=False)
        status_key = res.get("status", "skipped")
        if status_key == "retry_scheduled":
            counts["retried"] += 1
        elif status_key in counts:
            counts[status_key] += 1
    return counts


class _LeaseHeartbeatThread:
    """Periodic daemon heartbeat keeping a worker's lease fresh during long-running renders."""

    def __init__(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        lease_seconds: int,
        interval_seconds: float,
    ) -> None:
        self._job_id = job_id
        self._worker_id = worker_id
        self._fencing_token = fencing_token
        self._lease_seconds = lease_seconds
        self._interval = max(0.05, float(interval_seconds))
        self._stop_event = threading.Event()
        self.lease_lost = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"hb-{job_id[:8]}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                with db_module.SessionLocal() as hb_session:
                    ok = renew_job_lease(
                        hb_session,
                        job_id=self._job_id,
                        worker_id=self._worker_id,
                        fencing_token=self._fencing_token,
                        lease_seconds=self._lease_seconds,
                    )
                    hb_session.commit()
                    if not ok:
                        self.lease_lost = True
                        return
            except Exception:
                # Transient DB blip on one tick should not kill the thread; next tick retries.
                continue


def _is_job_cancelled(session, job_id: str) -> bool:
    session.expire_all()
    row = session.get(VideoJob, job_id)
    return row is not None and row.status == "CANCELLED"


def _resolve_reference_product_image(
    session,
    *,
    workspace_id: str,
    custom_props: dict[str, Any] | None,
    scraped_image_url: str,
) -> tuple[bytes | None, str | None]:
    props = custom_props or {}
    asset_id = str(props.get("productImageAssetId") or "").strip()
    if asset_id:
        asset = session.get(WorkspaceAsset, asset_id)
        if asset is None or asset.workspace_id != workspace_id:
            raise ValueError("Selected product asset does not belong to this workspace.")
        file_path = resolve_workspace_rel_path(workspace_id, asset.storage_rel_path)
        data = file_path.read_bytes()
        mime, _ = validate_image_bytes(data)
        return data, mime

    explicit_url = str(props.get("productImageUrl") or scraped_image_url or "").strip()
    if (
        explicit_url
        and explicit_url.startswith(("http://", "https://"))
        and not settings.is_mock_veo
    ):
        try:
            data, mime, _ = download_and_validate_product_image(explicit_url)
            return data, mime
        except Exception:
            return None, None
    return None, None


def _execute_leased_job_attempt(
    *,
    normalized_job_id: str,
    owner_id: str,
    ad_angle: str,
    simulate_failure: bool,
    custom_props: dict[str, Any] | None,
    duration_seconds: float,
    aspect_ratio: str,
    correlation_id: str | None,
    celery_task=None,
) -> dict[str, Any]:
    job_started = time.perf_counter()
    stage_timings_ms: dict[str, float] = {}

    with db_module.SessionLocal() as session:
        lease_seconds = settings.effective_job_lease_duration_seconds
        fencing_token = acquire_job_lease(
            session,
            job_id=normalized_job_id,
            worker_id=owner_id,
            lease_seconds=lease_seconds,
        )
        if fencing_token is None:
            existing = session.get(VideoJob, normalized_job_id)
            if existing is None:
                raise ValueError(f"VideoJob {normalized_job_id} not found")
            session.rollback()
            log_audit_event(
                "video_job_duplicate_or_owned_skipped",
                request_id=correlation_id,
                user_id=existing.user_id,
                workspace_id=existing.workspace_id,
                details={
                    "job_id": normalized_job_id,
                    "status": existing.status,
                    "current_worker_id": existing.worker_id,
                },
            )
            return {
                "id": existing.id,
                "workspace_id": existing.workspace_id,
                "status": existing.status,
                "skipped_duplicate": True,
            }

        job = session.get(VideoJob, normalized_job_id)
        if job is None:
            session.rollback()
            raise ValueError(f"VideoJob {normalized_job_id} not found")

        if correlation_id and not job.correlation_id:
            session.execute(
                update(VideoJob)
                .where(VideoJob.id == normalized_job_id, VideoJob.fencing_token == fencing_token)
                .values(correlation_id=correlation_id[:64])
            )
        session.commit()

        workspace_id = job.workspace_id
        user_id = job.user_id
        product_url = job.product_url
        target_language = job.target_language
        cost = int(job.reserved_credits or 1)
        current_retry_count = int(job.retry_count or 0)
        eff_corr_id = correlation_id or job.correlation_id
        history = list((job.script_json or {}).get("status_history") or ["CREATED", "QUEUED"])

        hb_interval = min(
            float(settings.effective_job_heartbeat_interval_seconds),
            max(1.0, float(lease_seconds) / 3.0),
        )
        heartbeat = _LeaseHeartbeatThread(
            job_id=normalized_job_id,
            worker_id=owner_id,
            fencing_token=fencing_token,
            lease_seconds=lease_seconds,
            interval_seconds=hb_interval,
        )
        heartbeat.start()

        def _fenced_transition(
            new_status: str,
            progress: int,
            detail: str,
            script: dict[str, Any] | None = None,
        ) -> None:
            if heartbeat.lease_lost:
                raise StaleWorkerLeaseError(
                    f"Worker '{owner_id}' lost lease heartbeat on job {normalized_job_id}."
                )
            if new_status not in history:
                history.append(new_status)
            existing_row = session.get(VideoJob, normalized_job_id)
            next_script = (
                dict(script) if script is not None else dict((existing_row.script_json or {}))
            )
            next_script["status_history"] = list(history)
            if stage_timings_ms:
                next_script["stage_timings_ms"] = dict(stage_timings_ms)

            now_sql = db_now_expr(session)
            res = session.execute(
                update(VideoJob)
                .where(
                    VideoJob.id == normalized_job_id,
                    VideoJob.worker_id == owner_id,
                    VideoJob.fencing_token == fencing_token,
                    VideoJob.status.notin_(("CANCELLED", "COMPLETED", "FAILED")),
                )
                .values(
                    status=new_status,
                    progress_pct=progress,
                    stage_detail=detail,
                    script_json=next_script,
                    heartbeat_at=now_sql,
                    updated_at=now_sql,
                )
            )
            if int(res.rowcount or 0) == 0:
                session.rollback()
                raise StaleWorkerLeaseError(
                    f"Worker '{owner_id}' lost fencing lock (token={fencing_token}) "
                    f"on job {normalized_job_id}."
                )
            session.commit()
            session.expire_all()

        audio_path = None
        source_clip_path = None
        try:
            _fenced_transition(
                "PROCESSING", 15, "Extracting verified product metadata & localization script"
            )

            if _is_job_cancelled(session, normalized_job_id):
                release_job_lease(
                    session,
                    job_id=normalized_job_id,
                    worker_id=owner_id,
                    fencing_token=fencing_token,
                )
                refund_credit_atomically(
                    session,
                    workspace_id=workspace_id,
                    job_id=normalized_job_id,
                    user_id=user_id,
                    cost=cost,
                    reason="Job cancelled prior to AI generation",
                )
                session.commit()
                return {
                    "id": normalized_job_id,
                    "workspace_id": workspace_id,
                    "status": "CANCELLED",
                }

            props = custom_props or {}
            confirmed_meta = (
                props.get("confirmedMetadata")
                if isinstance(props.get("confirmedMetadata"), dict)
                else None
            )
            t0 = time.perf_counter()
            if confirmed_meta is not None:
                metadata = confirmed_meta
            else:
                metadata = scrape_product_url(
                    product_url,
                    target_language=target_language,
                    fetch_live=not (
                        not settings.is_production and "simulate-fail" in product_url.lower()
                    ),
                )
            stage_timings_ms["scrape_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            metrics_registry.observe_ms("stage.scrape", stage_timings_ms["scrape_ms"])

            script_data = generate_localized_script(
                metadata,
                target_language=target_language,
                ad_angle=ad_angle,
                custom_props=custom_props,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
            )
            effective_duration = float(script_data.get("duration_ms", 4000)) / 1000.0
            _fenced_transition(
                "PROCESSING",
                35,
                "Synthesizing localized voiceover and AI video frames",
                script_data,
            )

            if not settings.is_production and (
                simulate_failure or "simulate-fail" in product_url.lower()
            ):
                raise RuntimeError("PIPELINE_SIMULATED_FAILURE: Requested failure simulation.")

            audio_dir = get_workspace_subdir(workspace_id, "audio")
            clips_dir = get_workspace_subdir(workspace_id, "clips")
            renders_dir = get_workspace_subdir(workspace_id, "renders")

            t_tts = time.perf_counter()
            audio_path = synthesize_voiceover_wav(
                normalized_job_id,
                script_data,
                output_dir=audio_dir,
                duration_seconds=effective_duration,
            )
            stage_timings_ms["tts_ms"] = round((time.perf_counter() - t_tts) * 1000.0, 2)
            metrics_registry.observe_ms("stage.tts", stage_timings_ms["tts_ms"])

            img_bytes, img_mime = _resolve_reference_product_image(
                session,
                workspace_id=workspace_id,
                custom_props=custom_props,
                scraped_image_url=str(metadata.get("image_url") or ""),
            )

            t_veo = time.perf_counter()
            veo_client = VeoClient()
            veo_result = veo_client.generate_clip(
                job_id=normalized_job_id,
                prompt=script_data["veo_prompt"],
                target_language=target_language,
                work_dir=clips_dir,
                duration_seconds=effective_duration,
                aspect_ratio=aspect_ratio,
                workspace_id=workspace_id,
                product_image_bytes=img_bytes,
                product_image_mime=img_mime,
            )
            stage_timings_ms["veo_ms"] = round((time.perf_counter() - t_veo) * 1000.0, 2)
            metrics_registry.observe_ms("stage.veo", stage_timings_ms["veo_ms"])
            source_clip_path = veo_result.local_clip_path

            if _is_job_cancelled(session, normalized_job_id):
                if audio_path:
                    audio_path.unlink(missing_ok=True)
                if source_clip_path:
                    source_clip_path.unlink(missing_ok=True)
                release_job_lease(
                    session,
                    job_id=normalized_job_id,
                    worker_id=owner_id,
                    fencing_token=fencing_token,
                )
                refund_credit_atomically(
                    session,
                    workspace_id=workspace_id,
                    job_id=normalized_job_id,
                    user_id=user_id,
                    cost=cost,
                    reason="Job cancelled prior to rendering",
                )
                session.commit()
                return {
                    "id": normalized_job_id,
                    "workspace_id": workspace_id,
                    "status": "CANCELLED",
                }

            script_data["veo_mocked"] = veo_result.mocked
            _fenced_transition(
                "RENDERING",
                80,
                "Compositing final ad overlays and validating MP4 container",
                script_data,
            )

            t_ffmpeg = time.perf_counter()
            final_mp4_path = composite_final_video(
                job_id=normalized_job_id,
                source_video_path=source_clip_path,
                voiceover_wav_path=audio_path,
                script_json=script_data,
                output_dir=renders_dir,
            )
            validation = validate_mp4_file(
                final_mp4_path,
                require_audio=True,
                min_duration_seconds=0.5,
            )
            stage_timings_ms["ffmpeg_ms"] = round((time.perf_counter() - t_ffmpeg) * 1000.0, 2)
            metrics_registry.observe_ms("stage.ffmpeg", stage_timings_ms["ffmpeg_ms"])

            mp4_bytes = final_mp4_path.read_bytes()
            asset = register_workspace_file(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                asset_kind="rendered_video",
                filename=f"{normalized_job_id}.mp4",
                content_type="video/mp4",
                data=mp4_bytes,
                source_url=product_url,
            )
            final_mp4_path.unlink(missing_ok=True)
            if audio_path:
                audio_path.unlink(missing_ok=True)
            if source_clip_path:
                source_clip_path.unlink(missing_ok=True)

            total_ms = round((time.perf_counter() - job_started) * 1000.0, 2)
            stage_timings_ms["total_ms"] = total_ms
            metrics_registry.observe_ms("job.total", total_ms)

            if "COMPLETED" not in history:
                history.append("COMPLETED")
            script_data["final_mp4_size_bytes"] = validation["size_bytes"]
            script_data["video_validation"] = validation
            script_data["status_history"] = list(history)
            script_data["stage_timings_ms"] = dict(stage_timings_ms)

            now_sql = db_now_expr(session)
            upd_res = session.execute(
                update(VideoJob)
                .where(
                    VideoJob.id == normalized_job_id,
                    VideoJob.worker_id == owner_id,
                    VideoJob.fencing_token == fencing_token,
                    VideoJob.status.notin_(("CANCELLED", "COMPLETED", "FAILED")),
                )
                .values(
                    veo_gcs_uri=veo_result.gcs_uri,
                    storage_rel_path=asset.storage_rel_path,
                    final_mp4_url=f"/api/v1/renders/{normalized_job_id}",
                    completed_at=now_sql,
                    status="COMPLETED",
                    progress_pct=100,
                    stage_detail="Completed and verified in workspace private storage",
                    script_json=dict(script_data),
                    worker_id=None,
                    lease_expires_at=None,
                    heartbeat_at=now_sql,
                    updated_at=now_sql,
                )
            )
            if int(upd_res.rowcount or 0) == 0:
                resolve_workspace_rel_path(workspace_id, asset.storage_rel_path).unlink(
                    missing_ok=True
                )
                session.delete(asset)
                latest = session.get(VideoJob, normalized_job_id)
                latest_status = latest.status if latest else "UNKNOWN"
                if latest_status == "CANCELLED":
                    refund_credit_atomically(
                        session,
                        workspace_id=workspace_id,
                        job_id=normalized_job_id,
                        user_id=user_id,
                        cost=cost,
                        reason="Job cancelled before completion",
                    )
                    session.commit()
                    return {
                        "id": normalized_job_id,
                        "workspace_id": workspace_id,
                        "status": "CANCELLED",
                    }
                session.rollback()
                metrics_registry.incr("jobs.fenced_stale_worker")
                raise StaleWorkerLeaseError(
                    f"Completion rejected due to lost lease (token={fencing_token})."
                )

            finalize_credit_deduction(
                session,
                workspace_id=workspace_id,
                job_id=normalized_job_id,
                user_id=user_id,
                cost=cost,
            )
            session.commit()
            session.expire_all()
            completed_job = session.get(VideoJob, normalized_job_id)
            assert completed_job is not None

            metrics_registry.incr("jobs.completed")
            log_audit_event(
                "video_job_completed",
                request_id=eff_corr_id,
                user_id=user_id,
                workspace_id=workspace_id,
                details={
                    "job_id": completed_job.id,
                    "worker_id": owner_id,
                    "fencing_token": fencing_token,
                    "size_bytes": validation["size_bytes"],
                    "stage_timings_ms": stage_timings_ms,
                },
            )
            return {
                "id": completed_job.id,
                "workspace_id": completed_job.workspace_id,
                "status": completed_job.status,
                "veo_gcs_uri": completed_job.veo_gcs_uri,
                "final_mp4_url": completed_job.final_mp4_url,
                "script_json": completed_job.script_json,
            }

        except StaleWorkerLeaseError:
            session.rollback()
            if audio_path:
                audio_path.unlink(missing_ok=True)
            if source_clip_path:
                source_clip_path.unlink(missing_ok=True)
            metrics_registry.incr("jobs.fenced_stale_worker")
            log_audit_event(
                "video_job_stale_worker_fenced",
                level="WARNING",
                request_id=eff_corr_id,
                user_id=user_id,
                workspace_id=workspace_id,
                details={
                    "job_id": normalized_job_id,
                    "worker_id": owner_id,
                    "fencing_token": fencing_token,
                },
            )
            latest = session.get(VideoJob, normalized_job_id)
            return {
                "id": normalized_job_id,
                "workspace_id": workspace_id,
                "status": latest.status if latest else "STALE_LEASE_FENCED",
                "fenced": True,
            }

        except Exception as exc:
            session.rollback()
            if audio_path:
                audio_path.unlink(missing_ok=True)
            if source_clip_path:
                source_clip_path.unlink(missing_ok=True)

            max_retries = settings.effective_job_max_retries
            if is_retryable_exception(exc) and current_retry_count < max_retries:
                next_retry = current_retry_count + 1
                countdown = compute_retry_countdown(current_retry_count)
                latest = session.get(VideoJob, normalized_job_id)
                retry_script = dict((latest.script_json if latest else {}) or {})
                retry_hist = list(retry_script.get("status_history") or history)
                if "QUEUED" not in retry_hist:
                    retry_hist.append("QUEUED")
                retry_script["status_history"] = retry_hist
                retry_script["last_transient_error"] = str(exc)[:300]

                upd_retry = session.execute(
                    update(VideoJob)
                    .where(
                        VideoJob.id == normalized_job_id,
                        VideoJob.worker_id == owner_id,
                        VideoJob.fencing_token == fencing_token,
                        VideoJob.status.notin_(("CANCELLED", "COMPLETED", "FAILED")),
                    )
                    .values(
                        status="QUEUED",
                        progress_pct=10,
                        stage_detail=(
                            f"Transient failure ({type(exc).__name__}); "
                            f"scheduled retry {next_retry}/{max_retries}"
                        ),
                        error_code=type(exc).__name__[:64],
                        error_message=str(exc)[:500],
                        retry_count=next_retry,
                        script_json=retry_script,
                        worker_id=None,
                        lease_expires_at=None,
                        updated_at=db_now_expr(session),
                    )
                )
                session.commit()
                if int(upd_retry.rowcount or 0) > 0:
                    metrics_registry.incr("jobs.retried")
                    log_audit_event(
                        "video_job_retry_scheduled",
                        level="WARNING",
                        request_id=eff_corr_id,
                        user_id=user_id,
                        workspace_id=workspace_id,
                        details={
                            "job_id": normalized_job_id,
                            "retry_count": next_retry,
                            "max_retries": max_retries,
                            "countdown_seconds": countdown,
                            "error": str(exc)[:250],
                        },
                    )
                    use_celery_retry = (
                        celery_task is not None
                        and not celery_app.conf.task_always_eager
                        and not getattr(celery_task.request, "called_directly", False)
                    )
                    if use_celery_retry:
                        raise celery_task.retry(
                            exc=exc, countdown=countdown, max_retries=max_retries
                        )
                    # Eager/direct execution mode: signal caller loop to retry immediately.
                    raise _EagerRetrySignal(countdown=countdown) from exc

            # Permanent failure or retries exhausted: fenced failure transition + single refund.
            if "FAILED" not in history:
                history.append("FAILED")
            latest = session.get(VideoJob, normalized_job_id)
            err_payload = dict((latest.script_json if latest else {}) or {})
            err_payload["error"] = str(exc)[:500]
            err_payload["status_history"] = list(history)
            if stage_timings_ms:
                err_payload["stage_timings_ms"] = dict(stage_timings_ms)

            now_sql = db_now_expr(session)
            upd_fail = session.execute(
                update(VideoJob)
                .where(
                    VideoJob.id == normalized_job_id,
                    VideoJob.worker_id == owner_id,
                    VideoJob.fencing_token == fencing_token,
                    VideoJob.status.notin_(("CANCELLED", "COMPLETED", "FAILED")),
                )
                .values(
                    status="FAILED",
                    progress_pct=0,
                    stage_detail="Generation failed — reserved credit refunded",
                    error_code=type(exc).__name__[:64],
                    error_message=str(exc)[:500],
                    script_json=err_payload,
                    worker_id=None,
                    lease_expires_at=None,
                    fencing_token=VideoJob.fencing_token + 1,
                    updated_at=now_sql,
                )
            )
            refunded_balance = None
            if int(upd_fail.rowcount or 0) > 0:
                refunded_balance = refund_credit_atomically(
                    session,
                    workspace_id=workspace_id,
                    job_id=normalized_job_id,
                    user_id=user_id,
                    cost=cost,
                    reason=f"Refund for failed job ({type(exc).__name__})",
                )
            session.commit()
            metrics_registry.incr("jobs.failed")
            log_audit_event(
                "video_job_failed",
                level="ERROR",
                request_id=eff_corr_id,
                user_id=user_id,
                workspace_id=workspace_id,
                details={
                    "job_id": normalized_job_id,
                    "error_code": type(exc).__name__,
                    "credit_balance_after_refund": refunded_balance,
                },
            )
            return {
                "id": normalized_job_id,
                "workspace_id": workspace_id,
                "status": "FAILED",
                "error": str(exc)[:500],
                "credit_balance": refunded_balance,
            }
        finally:
            heartbeat.stop()


class _EagerRetrySignal(Exception):
    """Internal control-flow signal for in-process retry execution when Celery runs eagerly."""

    def __init__(self, countdown: float) -> None:
        self.countdown = countdown
        super().__init__(f"Eager retry after {countdown}s")


@celery_app.task(
    name="worker.process_video_job",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_video_job(
    self,
    job_id: str,
    ad_angle: str = "problem_solution",
    simulate_failure: bool = False,
    custom_props: dict[str, Any] | None = None,
    duration_seconds: float = 4.0,
    aspect_ratio: str = "9:16",
    correlation_id: str | None = None,
    worker_id: str | None = None,
) -> dict[str, Any]:
    """Execute the end-to-end localized video ad pipeline with lease ownership & retries."""
    normalized_job_id = str(uuid.UUID(str(job_id)))
    owner_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    while True:
        try:
            return _execute_leased_job_attempt(
                normalized_job_id=normalized_job_id,
                owner_id=owner_id,
                ad_angle=ad_angle,
                simulate_failure=simulate_failure,
                custom_props=custom_props,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                correlation_id=correlation_id,
                celery_task=self,
            )
        except _EagerRetrySignal as sig:
            delay = (
                min(sig.countdown, 0.05)
                if settings.effective_app_env == "test"
                else min(sig.countdown, 2.0)
            )
            if delay > 0:
                time.sleep(delay)
            owner_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
            continue
        except CeleryRetry:
            raise


def recover_expired_leases(min_age_seconds: int | None = None) -> int:
    """Atomically recover genuinely expired active-worker jobs using DB clock & CAS.

    Legitimate CREATED/QUEUED/PENDING jobs waiting in Redis are NEVER marked failed here.
    Every candidate recovery re-validates status, worker_id, fencing_token, and DB-clock
    expiration inside the UPDATE statement itself so concurrent heartbeat renewals never lose.
    """
    grace_seconds = 0 if min_age_seconds is None else max(0, int(min_age_seconds))
    recovered = 0

    with db_module.SessionLocal() as scan_session:
        now_sql = db_now_expr(scan_session)
        candidates = list(
            scan_session.execute(
                select(
                    VideoJob.id,
                    VideoJob.worker_id,
                    VideoJob.fencing_token,
                    VideoJob.lease_expires_at,
                ).where(
                    VideoJob.status.in_(ACTIVE_EXECUTION_STATUSES),
                    or_(
                        and_(
                            VideoJob.lease_expires_at.is_not(None),
                            VideoJob.lease_expires_at <= now_sql,
                        ),
                        and_(
                            VideoJob.worker_id.is_(None),
                            VideoJob.lease_expires_at.is_(None),
                        ),
                    ),
                )
            ).all()
        )

    for job_id, observed_worker_id, observed_token, observed_lease_exp in candidates:
        with db_module.SessionLocal() as job_session:
            row_q = select(VideoJob).where(VideoJob.id == job_id)
            if db_dialect_name(job_session) == "postgresql":
                row_q = row_q.with_for_update(skip_locked=True)
            job = job_session.scalar(row_q)
            if job is None or job.status not in ACTIVE_EXECUTION_STATUSES:
                job_session.rollback()
                continue

            now_sql = db_now_expr(job_session)
            where_clauses = [
                VideoJob.id == job_id,
                VideoJob.status.in_(ACTIVE_EXECUTION_STATUSES),
                VideoJob.fencing_token == int(observed_token or 0),
                VideoJob.worker_id == observed_worker_id
                if observed_worker_id is not None
                else VideoJob.worker_id.is_(None),
            ]

            if observed_lease_exp is not None:
                where_clauses.extend(
                    [
                        VideoJob.lease_expires_at.is_not(None),
                        VideoJob.lease_expires_at <= now_sql,
                    ]
                )
                err_code = "WORKER_LEASE_EXPIRED"
                err_msg = (
                    "Worker lease expired before completion; reserved credit safely refunded."
                )
                stage_detail = "Worker lease expired — credit refunded"
            else:
                where_clauses.append(VideoJob.lease_expires_at.is_(None))
                if grace_seconds > 0:
                    where_clauses.append(
                        VideoJob.updated_at <= db_offset_expr(job_session, -float(grace_seconds))
                    )
                err_code = "WORKER_INTERRUPTED"
                err_msg = (
                    "Worker restarted while job was in progress; reserved credit refunded."
                )
                stage_detail = "Interrupted by server restart — credit refunded"

            hist = list((job.script_json or {}).get("status_history") or [])
            if "FAILED" not in hist:
                hist.append("FAILED")
            next_script = dict(job.script_json or {})
            next_script["status_history"] = hist

            upd = job_session.execute(
                update(VideoJob)
                .where(*where_clauses)
                .values(
                    status="FAILED",
                    progress_pct=0,
                    error_code=err_code,
                    error_message=err_msg,
                    stage_detail=stage_detail,
                    worker_id=None,
                    lease_expires_at=None,
                    fencing_token=VideoJob.fencing_token + 1,
                    script_json=next_script,
                    updated_at=now_sql,
                )
            )
            if int(upd.rowcount or 0) != 1:
                job_session.rollback()
                continue

            job_session.execute(
                update(JobDispatchOutbox)
                .where(
                    JobDispatchOutbox.job_id == job_id,
                    JobDispatchOutbox.status.in_(("PENDING", "PUBLISHING")),
                )
                .values(status="CANCELLED", updated_at=now_sql)
            )
            refund_credit_atomically(
                job_session,
                workspace_id=job.workspace_id,
                job_id=job.id,
                user_id=job.user_id,
                cost=int(job.reserved_credits or 1),
                reason="Automatic refund for interrupted/expired-lease job on recovery",
            )
            job_session.commit()
            recovered += 1

    if recovered:
        metrics_registry.incr("jobs.recovered", recovered)
        log_audit_event("worker_recovered_interrupted_jobs", details={"recovered_count": recovered})
    return recovered


def recover_interrupted_jobs(
    min_age_seconds: int | None = None,
    *,
    reconcile_outbox: bool = True,
) -> int:
    """Recover genuinely abandoned active jobs without harming queued jobs, then relay outbox."""
    recovered = recover_expired_leases(min_age_seconds=min_age_seconds)
    if reconcile_outbox:
        try:
            reconcile_dispatch_outbox()
        except Exception as exc:
            log_audit_event(
                "outbox_reconciliation_skipped",
                level="WARNING",
                details={"reason": type(exc).__name__},
            )
    return recovered
