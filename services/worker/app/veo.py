"""Vertex AI Veo 3.1 client with offline 2-second 9:16 MP4 fixture fallback."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import imageio_ffmpeg

from app.config import FIXTURES_DIR, settings

SAMPLE_FIXTURE_PATH = FIXTURES_DIR / "sample_9_16.mp4"


def get_ffmpeg_binary() -> str:
    """Resolve the FFmpeg executable path via imageio-ffmpeg or system PATH."""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        raise RuntimeError("FFmpeg binary not available via imageio-ffmpeg or PATH")


def ensure_sample_fixture(fixture_path: Path | None = None) -> Path:
    """Ensure the 2-second 9:16 vertical sample MP4 fixture exists on disk."""
    target = fixture_path or SAMPLE_FIXTURE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1024:
        return target

    ffmpeg_exe = get_ffmpeg_binary()
    cmd = [
        ffmpeg_exe,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=540x960:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:sample_rate=24000",
        "-t",
        "2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-movflags",
        "+faststart",
        str(target),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return target


@dataclass
class VeoGenerationResult:
    """Result from a Vertex AI Veo 3.1 clip generation call."""

    job_id: str
    model: str
    gcs_uri: str
    local_clip_path: Path
    mocked: bool
    aspect_ratio: str = "9:16"
    duration_seconds: float = 2.0


class VeoClient:
    """Client for dispatching 9:16 video generation jobs to Vertex AI Veo 3.1."""

    def __init__(
        self,
        project_id: str | None = None,
        gcs_bucket: str | None = None,
        model: str | None = None,
        mock_mode: bool | None = None,
    ) -> None:
        self.project_id = project_id or settings.GCP_PROJECT_ID
        self.gcs_bucket = (gcs_bucket or settings.GCS_BUCKET).rstrip("/")
        self.model = model or settings.VEO_MODEL
        self.mock_mode = settings.is_mock_veo if mock_mode is None else mock_mode

    @property
    def vertex_endpoint(self) -> str:
        return (
            f"https://us-central1-aiplatform.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/us-central1/publishers/google/models/{self.model}:predictLongRunning"
        )

    def build_gcs_output_uri(self, job_id: str) -> str:
        return f"{self.gcs_bucket}/jobs/{job_id}/veo_clip_9_16.mp4"

    def generate_clip(
        self,
        job_id: str,
        prompt: str,
        target_language: str = "ur",
        work_dir: Path | None = None,
    ) -> VeoGenerationResult:
        """Dispatch a Veo 3.1 generation job or copy the local 2-second 9:16 fixture."""
        gcs_uri = self.build_gcs_output_uri(job_id)

        if self.mock_mode:
            fixture = ensure_sample_fixture()
            dest_dir = work_dir or FIXTURES_DIR / "work"
            dest_dir.mkdir(parents=True, exist_ok=True)
            clip_copy = dest_dir / f"{job_id}_veo_source.mp4"
            shutil.copyfile(fixture, clip_copy)
            return VeoGenerationResult(
                job_id=job_id,
                model=self.model,
                gcs_uri=gcs_uri,
                local_clip_path=clip_copy,
                mocked=True,
            )

        payload: dict[str, Any] = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "aspectRatio": "9:16",
                "sampleCount": 1,
                "durationSeconds": 6,
                "storageUri": f"{self.gcs_bucket}/jobs/{job_id}/",
                "language": target_language,
            },
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(self.vertex_endpoint, json=payload)
            response.raise_for_status()

        fixture = ensure_sample_fixture()
        return VeoGenerationResult(
            job_id=job_id,
            model=self.model,
            gcs_uri=gcs_uri,
            local_clip_path=fixture,
            mocked=False,
        )
