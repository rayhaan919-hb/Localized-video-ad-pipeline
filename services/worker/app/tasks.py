"""Celery application, canonical job state machine, recovery, and private render execution."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Any

from celery import Celery
from sqlalchemy import select, update

import app.db as db_module
from app.compositor import composite_final_video
from app.config import is_redis_reachable, settings
from app.db import (
    VideoJob,
    WorkspaceAsset,
    finalize_credit_deduction,
    refund_credit_atomically,
    utcnow,
)
from app.scraper import (
    download_and_validate_product_image,
    scrape_product_url,
    validate_image_bytes,
)
from app.security import log_audit_event
from app.storage import (
    get_workspace_subdir,
    register_workspace_file,
    resolve_workspace_rel_path,
    validate_mp4_file,
)
from app.tts import generate_localized_script, synthesize_voiceover_wav
from app.veo import VeoClient

_redis_up = is_redis_reachable(settings.REDIS_URL)
_force_eager = os.environ.get("CELERY_ALWAYS_EAGER", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_use_redis_broker = _redis_up and not _force_eager

celery_app = Celery(
    "localized_video_ad_worker",
    broker=settings.REDIS_URL if _use_redis_broker else "memory://",
    backend=settings.REDIS_URL if _use_redis_broker else "cache+memory://",
)
celery_app.conf.update(
    task_always_eager=not _use_redis_broker,
    task_eager_propagates=False,
    task_ignore_result=not _use_redis_broker,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


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


@celery_app.task(name="worker.process_video_job")
def process_video_job(
    job_id: str,
    ad_angle: str = "problem_solution",
    simulate_failure: bool = False,
    custom_props: dict[str, Any] | None = None,
    duration_seconds: float = 4.0,
    aspect_ratio: str = "9:16",
) -> dict[str, Any]:
    """Execute the end-to-end localized video ad pipeline with strict workspace isolation.

    Canonical transitions:
        CREATED -> QUEUED -> PROCESSING -> RENDERING -> COMPLETED
    Cancellation or failure:
        Sets FAILED / CANCELLED and refunds reserved credits atomically & idempotently.
    """
    normalized_job_id = str(uuid.UUID(str(job_id)))

    with db_module.SessionLocal() as session:
        job = session.get(VideoJob, normalized_job_id)
        if job is None:
            raise ValueError(f"VideoJob {normalized_job_id} not found")

        if job.status in ("COMPLETED", "CANCELLED"):
            return {"id": job.id, "workspace_id": job.workspace_id, "status": job.status}

        workspace_id = job.workspace_id
        user_id = job.user_id
        product_url = job.product_url
        target_language = job.target_language
        cost = int(job.reserved_credits or 1)
        history = list((job.script_json or {}).get("status_history") or ["CREATED", "QUEUED"])

        def _transition(
            new_status: str, progress: int, detail: str, script: dict[str, Any] | None = None
        ) -> None:
            job.status = new_status
            job.progress_pct = progress
            job.stage_detail = detail
            job.updated_at = utcnow()
            if new_status not in history:
                history.append(new_status)
            if script is not None:
                script["status_history"] = list(history)
                job.script_json = dict(script)
            elif isinstance(job.script_json, dict):
                updated = dict(job.script_json)
                updated["status_history"] = list(history)
                job.script_json = updated
            session.commit()

        audio_path = None
        source_clip_path = None
        try:
            _transition(
                "PROCESSING", 15, "Extracting verified product metadata & localization script"
            )

            if _is_job_cancelled(session, normalized_job_id):
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

            script_data = generate_localized_script(
                metadata,
                target_language=target_language,
                ad_angle=ad_angle,
                custom_props=custom_props,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
            )
            effective_duration = float(script_data.get("duration_ms", 4000)) / 1000.0
            _transition(
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

            audio_path = synthesize_voiceover_wav(
                normalized_job_id,
                script_data,
                output_dir=audio_dir,
                duration_seconds=effective_duration,
            )

            img_bytes, img_mime = _resolve_reference_product_image(
                session,
                workspace_id=workspace_id,
                custom_props=custom_props,
                scraped_image_url=str(metadata.get("image_url") or ""),
            )

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
            source_clip_path = veo_result.local_clip_path
            job.veo_gcs_uri = veo_result.gcs_uri

            if _is_job_cancelled(session, normalized_job_id):
                if audio_path:
                    audio_path.unlink(missing_ok=True)
                if source_clip_path:
                    source_clip_path.unlink(missing_ok=True)
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
            _transition(
                "RENDERING",
                80,
                "Compositing final ad overlays and validating MP4 container",
                script_data,
            )

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
            # Remove duplicate staging render copy; private storage asset is now canonical.
            final_mp4_path.unlink(missing_ok=True)
            if audio_path:
                audio_path.unlink(missing_ok=True)
            if source_clip_path:
                source_clip_path.unlink(missing_ok=True)

            completed_at = utcnow()
            if "COMPLETED" not in history:
                history.append("COMPLETED")
            script_data["final_mp4_size_bytes"] = validation["size_bytes"]
            script_data["video_validation"] = validation
            script_data["status_history"] = list(history)

            # Atomic conditional transition guarantees a late cancel is never overwritten
            upd_res = session.execute(
                update(VideoJob)
                .where(VideoJob.id == normalized_job_id, VideoJob.status != "CANCELLED")
                .values(
                    storage_rel_path=asset.storage_rel_path,
                    final_mp4_url=f"/api/v1/renders/{job.id}",
                    completed_at=completed_at,
                    status="COMPLETED",
                    progress_pct=100,
                    stage_detail="Completed and verified in workspace private storage",
                    script_json=dict(script_data),
                    updated_at=completed_at,
                )
            )
            if upd_res.rowcount == 0:
                resolve_workspace_rel_path(workspace_id, asset.storage_rel_path).unlink(
                    missing_ok=True
                )
                session.delete(asset)
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

            finalize_credit_deduction(
                session,
                workspace_id=workspace_id,
                job_id=normalized_job_id,
                user_id=user_id,
                cost=cost,
            )
            session.commit()
            session.refresh(job)

            log_audit_event(
                "video_job_completed",
                user_id=user_id,
                workspace_id=workspace_id,
                details={"job_id": job.id, "size_bytes": validation["size_bytes"]},
            )
            return {
                "id": job.id,
                "workspace_id": job.workspace_id,
                "status": job.status,
                "veo_gcs_uri": job.veo_gcs_uri,
                "final_mp4_url": job.final_mp4_url,
                "script_json": job.script_json,
            }

        except Exception as exc:
            session.rollback()
            if audio_path:
                audio_path.unlink(missing_ok=True)
            if source_clip_path:
                source_clip_path.unlink(missing_ok=True)

            failed_job = session.get(VideoJob, normalized_job_id)
            if failed_job is not None and failed_job.status != "CANCELLED":
                failed_job.status = "FAILED"
                failed_job.progress_pct = 0
                failed_job.stage_detail = "Generation failed — reserved credit refunded"
                failed_job.error_code = type(exc).__name__[:64]
                failed_job.error_message = str(exc)[:500]
                failed_job.updated_at = utcnow()
                if "FAILED" not in history:
                    history.append("FAILED")
                err_payload = dict(failed_job.script_json or {})
                err_payload["error"] = str(exc)[:500]
                err_payload["status_history"] = list(history)
                failed_job.script_json = err_payload
                session.commit()

            refunded_balance = refund_credit_atomically(
                session,
                workspace_id=workspace_id,
                job_id=normalized_job_id,
                user_id=user_id,
                cost=cost,
                reason=f"Refund for failed job ({type(exc).__name__})",
            )
            session.commit()
            log_audit_event(
                "video_job_failed",
                level="ERROR",
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


def recover_interrupted_jobs(min_age_seconds: int = 0) -> int:
    """Recover in-flight jobs left incomplete by an unclean worker shutdown cleanly."""
    in_flight_statuses = (
        "CREATED",
        "QUEUED",
        "PROCESSING",
        "RENDERING",
        "PENDING",
        "GENERATING_CLIPS",
        "COMPOSITING",
    )
    recovered = 0
    with db_module.SessionLocal() as session:
        stmt = select(VideoJob).where(VideoJob.status.in_(in_flight_statuses))
        if min_age_seconds > 0:
            cutoff = utcnow() - timedelta(seconds=min_age_seconds)
            stmt = stmt.where(VideoJob.updated_at <= cutoff)
        jobs = list(session.scalars(stmt).all())
        for job in jobs:
            job.status = "FAILED"
            job.progress_pct = 0
            job.error_code = "WORKER_INTERRUPTED"
            job.error_message = (
                "Worker restarted while job was in progress; reserved credit refunded."
            )
            job.stage_detail = "Interrupted by server restart — credit refunded"
            job.updated_at = utcnow()
            refund_credit_atomically(
                session,
                workspace_id=job.workspace_id,
                job_id=job.id,
                user_id=job.user_id,
                cost=int(job.reserved_credits or 1),
                reason="Automatic refund for interrupted job on worker recovery",
            )
            recovered += 1
        session.commit()
    if recovered:
        log_audit_event("worker_recovered_interrupted_jobs", details={"recovered_count": recovered})
    return recovered
