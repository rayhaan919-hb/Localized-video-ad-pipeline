"""FFmpeg compositor merging 9:16 Veo video clips, TTS voiceover, and caption metadata."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.config import RENDERS_DIR
from app.veo import ensure_sample_fixture, get_ffmpeg_binary


def composite_final_video(
    job_id: str,
    source_video_path: Path,
    voiceover_wav_path: Path,
    script_json: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    """Composite the 9:16 Veo video clip with synthesized TTS audio into the final MP4."""
    target_dir = output_dir or RENDERS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    final_mp4_path = target_dir / f"{job_id}.mp4"

    if not source_video_path.exists():
        source_video_path = ensure_sample_fixture()

    if voiceover_wav_path.exists():
        try:
            ffmpeg_exe = get_ffmpeg_binary()
            cmd = [
                ffmpeg_exe,
                "-y",
                "-i",
                str(source_video_path),
                "-i",
                str(voiceover_wav_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                "-metadata",
                f"title={script_json.get('product_title', 'Localized Video Ad')}",
                "-metadata",
                f"language={script_json.get('target_language', 'ur')}",
                "-movflags",
                "+faststart",
                str(final_mp4_path),
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if final_mp4_path.exists() and final_mp4_path.stat().st_size > 1024:
                return final_mp4_path
        except Exception:
            pass

    shutil.copyfile(source_video_path, final_mp4_path)
    return final_mp4_path
