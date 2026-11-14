"""Celery application and video ad generation pipeline task."""

from __future__ import annotations

import os
from typing import Any

from celery import Celery

import app.db as db_module
from app.compositor import composite_final_video
from app.config import is_redis_reachable, settings
from app.db import VideoJob, normalize_uuid, refund_credit_atomically
from app.scraper import scrape_product_url
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


@celery_app.task(name="worker.process_video_job")
def process_video_job(
    job_id: str,
    ad_angle: str = "problem_solution",
    simulate_failure: bool = False,
    custom_props: dict[str, Any] | None = None,
    duration_seconds: float = 2.0,
) -> dict[str, Any]:
    """Execute the end-to-end localized video ad pipeline for a VideoJob.

    Transitions:
        PENDING -> GENERATING_CLIPS -> COMPOSITING -> COMPLETED
    On exception:
        Sets status = FAILED and refunds 1 credit atomically to the workspace.
    """
    normalized_job_id = normalize_uuid(job_id)
    status_history: list[str] = ["PENDING"]

    with db_module.SessionLocal() as session:
        job = session.get(VideoJob, normalized_job_id)
        if job is None:
            raise ValueError(f"VideoJob {normalized_job_id} not found")

        workspace_id = job.workspace_id
        product_url = job.product_url
        target_language = job.target_language

        try:
            # Step 1: Scrape product & generate localized RTL/LTR script
            metadata = scrape_product_url(product_url, target_language=target_language)
            script_data = generate_localized_script(
                metadata,
                target_language=target_language,
                ad_angle=ad_angle,
                custom_props=custom_props,
                duration_seconds=duration_seconds,
            )
            effective_duration = float(script_data.get("duration_ms", 2000)) / 1000.0

            job.status = "GENERATING_CLIPS"
            status_history.append("GENERATING_CLIPS")
            script_data["status_history"] = list(status_history)
            job.script_json = dict(script_data)
            session.commit()

            if simulate_failure or "simulate-fail" in product_url.lower():
                raise RuntimeError("Simulated Vertex AI Veo / pipeline failure")

            # Step 2: Generate voiceover WAV and Veo 3.1 9:16 video clip
            wav_path = synthesize_voiceover_wav(
                normalized_job_id,
                script_data,
                duration_seconds=effective_duration,
            )
            veo_client = VeoClient()
            veo_result = veo_client.generate_clip(
                job_id=normalized_job_id,
                prompt=script_data["veo_prompt"],
                target_language=target_language,
                duration_seconds=effective_duration,
            )

            job.veo_gcs_uri = veo_result.gcs_uri
            job.status = "COMPOSITING"
            status_history.append("COMPOSITING")
            script_data["status_history"] = list(status_history)
            script_data["voiceover_url"] = f"/static/audio/{normalized_job_id}.wav"
            script_data["veo_mocked"] = veo_result.mocked
            job.script_json = dict(script_data)
            session.commit()

            # Step 3: Composite final 9:16 MP4 with burned-in captions & audio
            final_mp4_path = composite_final_video(
                job_id=normalized_job_id,
                source_video_path=veo_result.local_clip_path,
                voiceover_wav_path=wav_path,
                script_json=script_data,
            )

            job.final_mp4_url = f"/static/renders/{final_mp4_path.name}"
            job.status = "COMPLETED"
            status_history.append("COMPLETED")
            script_data["status_history"] = list(status_history)
            script_data["final_mp4_size_bytes"] = final_mp4_path.stat().st_size
            job.script_json = dict(script_data)
            session.commit()
            session.refresh(job)

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
            failed_job = session.get(VideoJob, normalized_job_id)
            if failed_job is not None:
                failed_job.status = "FAILED"
                status_history.append("FAILED")
                err_payload = dict(failed_job.script_json or {})
                err_payload["error"] = str(exc)
                err_payload["status_history"] = list(status_history)
                failed_job.script_json = err_payload
                session.commit()

            refunded_balance = refund_credit_atomically(
                session,
                workspace_id=workspace_id,
                job_id=normalized_job_id,
                reason="video_render_failed_refund",
            )
            return {
                "id": normalized_job_id,
                "workspace_id": workspace_id,
                "status": "FAILED",
                "error": str(exc),
                "credit_balance": refunded_balance,
            }
