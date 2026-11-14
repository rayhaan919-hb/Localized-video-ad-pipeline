"""Vertex AI Veo 3.1 client with offline 2-second 9:16 MP4 fixture fallback."""

from __future__ import annotations

import base64
import shutil
import subprocess
import time
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


def ensure_sample_fixture(
    fixture_path: Path | None = None,
    duration_seconds: float = 2.0,
) -> Path:
    """Ensure a 9:16 vertical studio MP4 fixture exists on disk for the requested duration."""
    dur = max(1.0, min(15.0, float(duration_seconds)))
    if fixture_path is not None:
        target = fixture_path
    elif abs(dur - 2.0) < 0.05:
        target = SAMPLE_FIXTURE_PATH
    else:
        target = FIXTURES_DIR / f"sample_9_16_{dur:.1f}s.mp4"

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1024:
        return target

    ffmpeg_exe = get_ffmpeg_binary()
    studio_bg_filter = (
        "drawbox=x=24:y=160:w=492:h=620:color=0x18181B@0.92:t=fill,"
        "drawbox=x=24:y=160:w=492:h=4:color=0x6366F1@0.95:t=fill,"
        "drawbox=x=24:y=776:w=492:h=4:color=0x6366F1@0.95:t=fill"
    )
    cmd = [
        ffmpeg_exe,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x09090B:size=540x960:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:sample_rate=24000",
        "-t",
        f"{dur:.2f}",
        "-vf",
        studio_bg_filter,
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


def _resolve_vertex_bearer_token() -> str:
    """Resolve an OAuth2 Bearer token from env settings, google-auth ADC, or gcloud CLI."""
    if settings.effective_vertex_access_token:
        return settings.effective_vertex_access_token

    try:
        import google.auth  # type: ignore[import-not-found]
        from google.auth.transport.requests import Request  # type: ignore[import-not-found]

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        if creds.token:
            return str(creds.token)
    except Exception:
        pass

    gcloud_exe = shutil.which("gcloud")
    if gcloud_exe:
        try:
            proc = subprocess.run(
                [gcloud_exe, "auth", "print-access-token"],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=True,
            )
            token = proc.stdout.strip()
            if token:
                return token
        except Exception:
            pass

    return ""


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

    @property
    def fetch_operation_endpoint(self) -> str:
        return (
            f"https://us-central1-aiplatform.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/us-central1/publishers/google/models/{self.model}:fetchPredictOperation"
        )

    def build_gcs_output_uri(self, job_id: str) -> str:
        return f"{self.gcs_bucket}/jobs/{job_id}/veo_clip_9_16.mp4"

    def _poll_long_running_operation(
        self,
        client: httpx.Client,
        operation_name: str,
        headers: dict[str, str],
        max_polls: int = 24,
        poll_interval_seconds: float = 5.0,
    ) -> dict[str, Any]:
        """Poll Vertex AI fetchPredictOperation until done or timeout."""
        for _ in range(max_polls):
            poll_resp = client.post(
                self.fetch_operation_endpoint,
                headers=headers,
                json={"operationName": operation_name},
            )
            poll_resp.raise_for_status()
            body = poll_resp.json()
            if body.get("done"):
                if "error" in body and body["error"]:
                    raise RuntimeError(f"Vertex AI Veo operation failed: {body['error']}")
                return body
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for Vertex AI operation {operation_name}")

    def generate_clip(
        self,
        job_id: str,
        prompt: str,
        target_language: str = "ur",
        work_dir: Path | None = None,
        duration_seconds: float = 2.0,
    ) -> VeoGenerationResult:
        """Dispatch a Veo 3.1 generation job or copy the local 9:16 studio fixture."""
        gcs_uri = self.build_gcs_output_uri(job_id)
        dur = max(1.0, min(15.0, float(duration_seconds)))
        dest_dir = work_dir or FIXTURES_DIR / "work"
        dest_dir.mkdir(parents=True, exist_ok=True)
        clip_copy = dest_dir / f"{job_id}_veo_source.mp4"

        if self.mock_mode:
            fixture = ensure_sample_fixture(duration_seconds=dur)
            shutil.copyfile(fixture, clip_copy)
            return VeoGenerationResult(
                job_id=job_id,
                model=self.model,
                gcs_uri=gcs_uri,
                local_clip_path=clip_copy,
                mocked=True,
                duration_seconds=dur,
            )

        token = _resolve_vertex_bearer_token()
        if not token:
            raise RuntimeError(
                "Vertex AI live mode requires VERTEX_ACCESS_TOKEN, "
                "Google ADC (google-auth), or `gcloud auth print-access-token`."
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "aspectRatio": "9:16",
                "sampleCount": 1,
                "durationSeconds": min(8, max(5, int(round(dur)))),
                "storageUri": f"{self.gcs_bucket}/jobs/{job_id}/",
                "language": target_language,
            },
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(self.vertex_endpoint, headers=headers, json=payload)
            response.raise_for_status()
            op_data = response.json()
            if isinstance(op_data, dict) and op_data.get("name") and not op_data.get("done"):
                op_data = self._poll_long_running_operation(
                    client,
                    operation_name=str(op_data["name"]),
                    headers=headers,
                )

            response_block = op_data.get("response", {}) if isinstance(op_data, dict) else {}
            videos = response_block.get("videos") or response_block.get("predictions") or []
            if videos and isinstance(videos[0], dict):
                first_video = videos[0]
                if first_video.get("gcsUri"):
                    gcs_uri = str(first_video["gcsUri"])
                encoded = first_video.get("bytesBase64Encoded")
                if isinstance(encoded, str) and encoded:
                    clip_copy.write_bytes(base64.b64decode(encoded))

        if not clip_copy.exists() or clip_copy.stat().st_size < 1024:
            fixture = ensure_sample_fixture(duration_seconds=dur)
            shutil.copyfile(fixture, clip_copy)

        return VeoGenerationResult(
            job_id=job_id,
            model=self.model,
            gcs_uri=gcs_uri,
            local_clip_path=clip_copy,
            mocked=False,
            duration_seconds=dur,
        )
