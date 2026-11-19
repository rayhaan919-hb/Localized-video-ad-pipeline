"""Vertex AI Veo 3.1 client with strict validation, GCS download, and explicit mock boundary."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import imageio_ffmpeg

from app.config import FIXTURES_DIR, settings
from app.storage import VideoValidationError, validate_mp4_file

SAMPLE_FIXTURE_PATH = FIXTURES_DIR / "sample_9_16.mp4"
VALID_ASPECT_RATIOS = {"9:16", "16:9"}
_FIXTURE_LOCK = threading.Lock()
VALID_VEO_DURATIONS = {4, 6, 8}
VALID_VEO_MODELS = {
    "veo-3.1-generate-001",
    "veo-3.1-fast-generate-001",
    "veo-3.0-generate-001",
    "veo-2.0-generate-001",
}


class VeoError(Exception):
    """Base Vertex AI Veo error."""


class VeoValidationError(VeoError):
    """Raised when Veo generation parameters fail validation."""


class VeoConfigurationError(VeoError):
    """Raised when Vertex AI credentials or GCP settings are missing."""


class VeoProviderError(VeoError):
    """Raised when Vertex AI generation or GCS clip download fails."""


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
    duration_seconds: float = 4.0,
    aspect_ratio: str = "9:16",
) -> Path:
    """Create a synthetic studio test clip strictly for explicit MOCK_VERTEX_VEO=true mode."""
    dur = max(1.0, min(15.0, float(duration_seconds)))
    ratio_tag = "16_9" if aspect_ratio == "16:9" else "9_16"
    size_expr = "960x540" if aspect_ratio == "16:9" else "540x960"
    if fixture_path is not None:
        target = fixture_path
    else:
        target = FIXTURES_DIR / f"sample_{ratio_tag}_{dur:.1f}s.mp4"

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1024:
        return target

    ffmpeg_exe = get_ffmpeg_binary()
    studio_bg_filter = (
        "drawbox=x=24:y=120:w=iw-48:h=ih-280:color=0x18181B@0.92:t=fill,"
        "drawbox=x=24:y=120:w=iw-48:h=4:color=0x6366F1@0.95:t=fill"
    )
    with _FIXTURE_LOCK:
        if target.exists() and target.stat().st_size > 1024:
            return target
        tmp_target = target.with_name(f".{target.stem}.{uuid.uuid4().hex[:8]}.tmp.mp4")
        cmd = [
            ffmpeg_exe,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x09090B:size={size_expr}:rate=30",
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
            str(tmp_target),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.replace(tmp_target, target)
        finally:
            tmp_target.unlink(missing_ok=True)
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


def parse_gs_uri(gs_uri: str) -> tuple[str, str]:
    """Parse 'gs://bucket/path/to/object.mp4' into (bucket, object_path)."""
    parsed = urlparse(gs_uri.strip())
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise VeoProviderError(f"Invalid GCS URI returned by Vertex AI: {gs_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def download_gcs_object(
    gs_uri: str,
    dest_path: Path,
    *,
    bearer_token: str,
    max_attempts: int = 3,
    client: httpx.Client | None = None,
) -> Path:
    """Download a generated Veo clip genuinely from Google Cloud Storage HTTP JSON API."""
    bucket, obj_path = parse_gs_uri(gs_uri)
    url = (
        f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}"
        f"/o/{quote(obj_path, safe='')}?alt=media"
    )
    headers = {"Authorization": f"Bearer {bearer_token}"}
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    last_err: Exception | None = None
    owns_client = client is None
    http_client = client or httpx.Client(timeout=60.0)
    try:
        for attempt in range(max_attempts):
            try:
                resp = http_client.get(url, headers=headers)
                if resp.status_code == 200 and len(resp.content) > 1024:
                    dest_path.write_bytes(resp.content)
                    return dest_path
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise VeoProviderError(
                    f"GCS object download failed for {gs_uri} "
                    f"(HTTP {resp.status_code}, {len(resp.content)} bytes)."
                )
            except httpx.HTTPError as exc:
                last_err = exc
                if attempt < max_attempts - 1:
                    time.sleep(0.5 * (2**attempt))
                    continue
        raise VeoProviderError(f"GCS download failed after {max_attempts} attempts: {last_err}")
    finally:
        if owns_client:
            http_client.close()


@dataclass
class VeoGenerationResult:
    """Result from a Vertex AI Veo 3.1 clip generation call."""

    job_id: str
    model: str
    gcs_uri: str
    local_clip_path: Path
    mocked: bool
    aspect_ratio: str = "9:16"
    duration_seconds: float = 4.0


class VeoClient:
    """Client for dispatching 9:16 / 16:9 video generation jobs to Vertex AI Veo 3.1."""

    def __init__(
        self,
        project_id: str | None = None,
        gcs_bucket: str | None = None,
        model: str | None = None,
        mock_mode: bool | None = None,
    ) -> None:
        self.project_id = (
            project_id if project_id is not None else settings.effective_gcp_project_id
        ).strip()
        raw_bucket = (
            gcs_bucket if gcs_bucket is not None else settings.effective_gcs_bucket
        ).strip()
        self.gcs_bucket = raw_bucket.rstrip("/")
        self.location = settings.effective_vertex_location
        self.model = (model or settings.VEO_MODEL).strip()
        self.mock_mode = settings.is_mock_veo if mock_mode is None else mock_mode

        if settings.is_production and self.mock_mode:
            raise VeoConfigurationError("Mock Veo mode is forbidden when APP_ENV=production.")

    @property
    def vertex_endpoint(self) -> str:
        return (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/{self.location}/publishers/google/models/{self.model}:predictLongRunning"
        )

    @property
    def fetch_operation_endpoint(self) -> str:
        return (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/{self.location}/publishers/google/models/{self.model}:fetchPredictOperation"
        )

    def build_gcs_output_prefix(self, workspace_id: str, job_id: str) -> str:
        base = self.gcs_bucket or "gs://unconfigured-bucket"
        return f"{base}/workspaces/{workspace_id}/jobs/{job_id}/"

    def _validate_request_params(
        self,
        *,
        prompt: str,
        duration_seconds: float,
        aspect_ratio: str,
    ) -> int:
        if self.model not in VALID_VEO_MODELS and not self.model.startswith("veo-"):
            raise VeoValidationError(f"Unsupported Veo model '{self.model}'.")
        if aspect_ratio not in VALID_ASPECT_RATIOS:
            raise VeoValidationError(
                f"Unsupported aspect ratio '{aspect_ratio}'. Allowed: {sorted(VALID_ASPECT_RATIOS)}"
            )
        cleaned_prompt = (prompt or "").strip()
        if len(cleaned_prompt) < 5 or len(cleaned_prompt) > 4000:
            raise VeoValidationError("Veo prompt must be between 5 and 4000 characters.")

        rounded_dur = int(round(float(duration_seconds)))
        if not self.mock_mode and rounded_dur not in VALID_VEO_DURATIONS:
            raise VeoValidationError(
                f"Vertex AI Veo requires duration_seconds in {sorted(VALID_VEO_DURATIONS)}, "
                f"got {duration_seconds}."
            )
        return max(1, min(15, rounded_dur))

    def _poll_long_running_operation(
        self,
        client: httpx.Client,
        operation_name: str,
        headers: dict[str, str],
        max_polls: int = 36,
        poll_interval_seconds: float = 5.0,
    ) -> dict[str, Any]:
        """Poll Vertex AI fetchPredictOperation until done or timeout."""
        for attempt in range(max_polls):
            poll_resp = client.post(
                self.fetch_operation_endpoint,
                headers=headers,
                json={"operationName": operation_name},
            )
            if poll_resp.status_code in (429, 500, 502, 503, 504):
                if attempt < max_polls - 1:
                    time.sleep(poll_interval_seconds)
                    continue
            poll_resp.raise_for_status()
            body = poll_resp.json()
            if body.get("done"):
                if body.get("error"):
                    raise VeoProviderError(f"Vertex AI Veo operation failed: {body['error']}")
                return body
            if attempt < max_polls - 1:
                time.sleep(poll_interval_seconds)
        raise VeoProviderError(f"Timed out waiting for Vertex AI operation {operation_name}")

    def _post_predict_with_retry(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        payload: dict[str, Any],
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = client.post(self.vertex_endpoint, headers=headers, json=payload)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                    time.sleep(0.75 * (2**attempt))
                    continue
                if response.status_code >= 400:
                    raise VeoProviderError(
                        "Vertex AI Veo rejected generation request "
                        f"(HTTP {response.status_code}): {response.text[:300]}"
                    )
                return response.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(0.75 * (2**attempt))
                    continue
        raise VeoProviderError(f"Vertex AI Veo request failed: {last_exc}")

    def generate_clip(
        self,
        job_id: str,
        prompt: str,
        target_language: str = "ur",
        work_dir: Path | None = None,
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        workspace_id: str = "00000000-0000-0000-0000-000000000000",
        product_image_bytes: bytes | None = None,
        product_image_mime: str | None = None,
    ) -> VeoGenerationResult:
        """Generate a video clip via Vertex AI Veo 3.1 or explicit mock fixture mode."""
        if settings.is_production and self.mock_mode:
            raise VeoConfigurationError("Mock Veo mode is forbidden when APP_ENV=production.")

        validated_dur = self._validate_request_params(
            prompt=prompt,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
        )

        dest_dir = work_dir or (FIXTURES_DIR / "work")
        dest_dir.mkdir(parents=True, exist_ok=True)
        clip_copy = dest_dir / f"{job_id}_veo_source.mp4"
        output_prefix = self.build_gcs_output_prefix(workspace_id, job_id)

        if self.mock_mode:
            fixture = ensure_sample_fixture(
                duration_seconds=float(duration_seconds),
                aspect_ratio=aspect_ratio,
            )
            shutil.copyfile(fixture, clip_copy)
            return VeoGenerationResult(
                job_id=job_id,
                model=self.model,
                gcs_uri=f"mock://local-fixture/{job_id}.mp4",
                local_clip_path=clip_copy,
                mocked=True,
                aspect_ratio=aspect_ratio,
                duration_seconds=float(duration_seconds),
            )

        if not self.project_id:
            raise VeoConfigurationError("GCP_PROJECT_ID is required for Vertex AI Veo live mode.")
        if not self.gcs_bucket.startswith("gs://"):
            raise VeoConfigurationError(
                "GCS_BUCKET (gs://...) is required for Vertex AI Veo live mode."
            )

        token = _resolve_vertex_bearer_token()
        if not token:
            raise VeoConfigurationError(
                "Vertex AI live mode requires VERTEX_ACCESS_TOKEN, "
                "Google ADC (google-auth), or gcloud CLI auth."
            )

        instance: dict[str, Any] = {"prompt": prompt.strip()}
        if product_image_bytes and product_image_mime:
            instance["image"] = {
                "bytesBase64Encoded": base64.b64encode(product_image_bytes).decode("ascii"),
                "mimeType": product_image_mime,
            }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "instances": [instance],
            "parameters": {
                "aspectRatio": aspect_ratio,
                "sampleCount": 1,
                "durationSeconds": validated_dur,
                "storageUri": output_prefix,
                "language": target_language,
            },
        }

        actual_gcs_uri = ""
        with httpx.Client(timeout=45.0) as client:
            op_data = self._post_predict_with_retry(client, headers, payload)
            if isinstance(op_data, dict) and op_data.get("name") and not op_data.get("done"):
                op_data = self._poll_long_running_operation(
                    client,
                    operation_name=str(op_data["name"]),
                    headers=headers,
                )

            response_block = op_data.get("response", {}) if isinstance(op_data, dict) else {}
            videos = response_block.get("videos") or response_block.get("predictions") or []
            if not videos or not isinstance(videos[0], dict):
                raise VeoProviderError(
                    "Vertex AI Veo operation completed without any video output."
                )

            first_video = videos[0]
            actual_gcs_uri = str(first_video.get("gcsUri") or "").strip()
            encoded = first_video.get("bytesBase64Encoded")
            if isinstance(encoded, str) and encoded.strip():
                clip_copy.write_bytes(base64.b64decode(encoded))
            elif actual_gcs_uri.startswith("gs://"):
                download_gcs_object(actual_gcs_uri, clip_copy, bearer_token=token, client=client)
            else:
                raise VeoProviderError(
                    "Vertex AI Veo response omitted both bytesBase64Encoded and gcsUri."
                )

        try:
            validate_mp4_file(clip_copy, require_audio=False, min_duration_seconds=0.5)
        except VideoValidationError as exc:
            clip_copy.unlink(missing_ok=True)
            raise VeoProviderError(f"Generated Veo clip failed MP4 validation: {exc}") from exc

        return VeoGenerationResult(
            job_id=job_id,
            model=self.model,
            gcs_uri=actual_gcs_uri or output_prefix,
            local_clip_path=clip_copy,
            mocked=False,
            aspect_ratio=aspect_ratio,
            duration_seconds=float(validated_dur),
        )
