"""Workspace-isolated private file storage, signed URLs, and FFmpeg MP4 validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import imageio_ffmpeg
from sqlalchemy.orm import Session

from app.config import settings
from app.db import WorkspaceAsset, utcnow

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_VIDEO_RE = re.compile(r"Video:\s*([a-zA-Z0-9_]+).*?(\d{2,5})x(\d{2,5})", re.IGNORECASE)
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_AUDIO_RE = re.compile(r"Audio:\s*([a-zA-Z0-9_]+)", re.IGNORECASE)


class StorageError(Exception):
    """Base private storage or asset error."""


class VideoValidationError(StorageError):
    """Raised when a rendered or downloaded video fails container/codec validation."""


def sanitize_filename(name: str, default: str = "file.bin") -> str:
    base = Path(name or default).name
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._")
    return (cleaned or default)[:180]


def get_workspace_subdir(workspace_id: str, category: str) -> Path:
    """Return a path-traversal-safe private directory scoped strictly to workspace_id."""
    ws_str = str(uuid.UUID(str(workspace_id)))
    safe_cat = sanitize_filename(category, "misc")
    root = settings.effective_storage_root.resolve()
    target = (root / "workspaces" / ws_str / safe_cat).resolve()
    if not target.is_relative_to(root):
        raise StorageError("Invalid workspace storage path.")
    target.mkdir(parents=True, exist_ok=True)
    return target


def resolve_workspace_rel_path(workspace_id: str, storage_rel_path: str) -> Path:
    """Resolve and verify that storage_rel_path lies strictly inside workspace_id's directory."""
    ws_str = str(uuid.UUID(str(workspace_id)))
    root = settings.effective_storage_root.resolve()
    expected_prefix = (root / "workspaces" / ws_str).resolve()
    candidate = (root / storage_rel_path).resolve()
    if not candidate.is_relative_to(expected_prefix):
        raise StorageError("Cross-workspace or path traversal storage access denied.")
    return candidate


def register_workspace_file(
    session: Session,
    *,
    workspace_id: str,
    user_id: str | None,
    asset_kind: str,
    filename: str,
    content_type: str,
    data: bytes,
    source_url: str | None = None,
) -> WorkspaceAsset:
    """Persist bytes inside workspace private storage and register a WorkspaceAsset record."""
    if len(data) == 0:
        raise StorageError("Uploaded asset cannot be empty.")
    max_bytes = (
        settings.effective_max_rendered_video_bytes
        if asset_kind == "rendered_video"
        else int(settings.MAX_ASSET_UPLOAD_BYTES)
    )
    if len(data) > max_bytes:
        raise StorageError(f"Asset size exceeds maximum allowed limit of {max_bytes} bytes.")

    safe_name = sanitize_filename(filename, "asset.bin")
    ext = Path(safe_name).suffix[:16] or ".bin"
    asset_id = str(uuid.uuid4())
    dest_dir = get_workspace_subdir(workspace_id, asset_kind)
    dest_file = (dest_dir / f"{asset_id}{ext}").resolve()
    dest_file.write_bytes(data)

    root = settings.effective_storage_root.resolve()
    rel_path = dest_file.relative_to(root).as_posix()
    digest = hashlib.sha256(data).hexdigest()

    record = WorkspaceAsset(
        id=asset_id,
        workspace_id=str(uuid.UUID(str(workspace_id))),
        user_id=str(uuid.UUID(str(user_id))) if user_id else None,
        asset_kind=asset_kind,
        filename=safe_name,
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest,
        storage_rel_path=rel_path,
        source_url=source_url,
        created_at=utcnow(),
    )
    session.add(record)
    session.flush()
    return record


def create_signed_download_token(
    *,
    job_id: str,
    workspace_id: str,
    expires_in_seconds: int | None = None,
) -> tuple[str, int]:
    """Sign a short-lived HMAC token authorizing download of job_id within workspace_id."""
    secret = settings.effective_signed_url_secret
    if not secret:
        raise RuntimeError("SIGNED_URL_SECRET / AUTH_JWT_SECRET is not configured.")
    ttl = int(expires_in_seconds or settings.SIGNED_URL_TTL_SECONDS)
    exp = int(time.time()) + max(30, ttl)
    msg = f"{uuid.UUID(str(job_id))}:{uuid.UUID(str(workspace_id))}:{exp}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    token = f"{exp}.{sig}"
    return token, exp


def verify_signed_download_token(
    *,
    token: str,
    job_id: str,
    workspace_id: str,
) -> bool:
    """Verify signed download token matches job_id, workspace_id, and has not expired."""
    secret = settings.effective_signed_url_secret
    if not secret or "." not in token:
        return False
    exp_str, supplied_sig = token.split(".", 1)
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    if exp <= int(time.time()):
        return False
    msg = f"{uuid.UUID(str(job_id))}:{uuid.UUID(str(workspace_id))}:{exp}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, supplied_sig.strip())


def validate_mp4_file(
    file_path: Path,
    *,
    require_audio: bool = False,
    min_duration_seconds: float = 0.5,
) -> dict[str, Any]:
    """Validate an MP4 artifact using header inspection and FFmpeg stream inspection."""
    if not file_path.exists() or not file_path.is_file():
        raise VideoValidationError(f"Video file not found: {file_path}")

    size_bytes = file_path.stat().st_size
    if size_bytes < 1024:
        raise VideoValidationError(f"Video file is suspiciously small ({size_bytes} bytes).")

    with file_path.open("rb") as fh:
        header = fh.read(64)
    if b"ftyp" not in header:
        raise VideoValidationError("File does not contain a valid MP4 ISO BMFF 'ftyp' box.")

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ffmpeg_exe, "-hide_banner", "-i", str(file_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    probe_text = (proc.stderr or "") + "\n" + (proc.stdout or "")

    vid_match = _VIDEO_RE.search(probe_text)
    if not vid_match:
        raise VideoValidationError("FFmpeg found no playable video stream in MP4 file.")

    codec = vid_match.group(1).lower()
    width = int(vid_match.group(2))
    height = int(vid_match.group(3))
    if width <= 0 or height <= 0:
        raise VideoValidationError(f"Invalid video dimensions: {width}x{height}.")

    dur_match = _DURATION_RE.search(probe_text)
    if not dur_match:
        raise VideoValidationError("FFmpeg could not determine MP4 duration.")
    hours, minutes, seconds = (
        float(dur_match.group(1)),
        float(dur_match.group(2)),
        float(dur_match.group(3)),
    )
    duration_seconds = hours * 3600.0 + minutes * 60.0 + seconds
    if duration_seconds < min_duration_seconds:
        raise VideoValidationError(
            f"Video duration {duration_seconds:.2f}s is shorter than minimum "
            f"{min_duration_seconds:.2f}s."
        )

    audio_match = _AUDIO_RE.search(probe_text)
    has_audio = audio_match is not None
    if require_audio and not has_audio:
        raise VideoValidationError("Completed video ad is missing an audio track.")

    return {
        "valid": True,
        "size_bytes": size_bytes,
        "codec": codec,
        "width": width,
        "height": height,
        "duration_seconds": round(duration_seconds, 3),
        "has_audio": has_audio,
    }


def load_json_metadata(raw: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}
    return {}
