"""FFmpeg / Remotion compositor merging Veo clips, TTS voiceover, and validated MP4 output."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.config import RENDERS_DIR, REPO_ROOT, settings
from app.storage import validate_mp4_file
from app.veo import get_ffmpeg_binary


class CompositorError(Exception):
    """Raised when final video composition or validation fails."""


def _format_ass_ts(ms: int) -> str:
    clamped = max(0, int(ms))
    total_cs = clamped // 10
    cs = total_cs % 100
    total_s = total_cs // 100
    sec = total_s % 60
    minutes = (total_s // 60) % 60
    hours = total_s // 3600
    return f"{hours}:{minutes:02d}:{sec:02d}.{cs:02d}"


def _escape_ass(text: str) -> str:
    cleaned = str(text or "").replace("{", "(").replace("}", ")")
    return cleaned.replace("\r\n", "\\N").replace("\n", "\\N").strip()


def _highlight_caption_ass(text: str, highlight_word: str) -> str:
    escaped = _escape_ass(text)
    hw = _escape_ass(highlight_word)
    if hw and hw in escaped:
        accent = f"{{\\c&HF16663&}}{hw}{{\\c&HFAFAFA&}}"
        return escaped.replace(hw, accent, 1)
    return escaped


def _build_ass_subtitles(script_json: dict[str, Any]) -> str:
    raw_font = str(script_json.get("font_family") or "Arial")
    font_name = re.sub(r"[^A-Za-z0-9 _-]", "", raw_font).strip() or "Arial"
    total_ms = max(1500, int(script_json.get("duration_ms") or 4000))
    end_ts = _format_ass_ts(total_ms)
    ratio = str(script_json.get("aspect_ratio") or "9:16")
    play_x, play_y = (960, 540) if ratio == "16:9" else (540, 960)

    brand = _escape_ass(str(script_json.get("brand") or ""))
    price = _escape_ass(str(script_json.get("price_badge") or ""))
    discount = _escape_ass(str(script_json.get("discount_badge") or ""))
    banner_parts = [part for part in [brand, price, discount] if part]
    banner_line = "  |  ".join(banner_parts)

    hook_line = _escape_ass(str(script_json.get("hook") or script_json.get("product_title") or ""))
    cta_line = _escape_ass(str(script_json.get("cta_text") or ""))

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_x}",
        f"PlayResY: {play_y}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: BrandBanner,{font_name},18,&H00EBE7FF,&H00FFFFFF,&H0009090B,"
            "&H9909090B,1,0,0,0,100,100,0,0,1,2,0,8,28,28,36,1"
        ),
        (
            f"Style: HookTitle,{font_name},24,&H00FAFAFA,&H00FFFFFF,&H0009090B,"
            "&HA609090B,1,0,0,0,100,100,0,0,1,2.5,1,8,34,34,108,1"
        ),
        (
            f"Style: Caption,{font_name},28,&H00FAFAFA,&H00FFFFFF,&H0009090B,"
            "&HB309090B,1,0,0,0,100,100,0,0,1,3,1,2,32,32,140,1"
        ),
        (
            f"Style: CtaDock,{font_name},20,&H00FFFFFF,&H00FFFFFF,&H00463731,"
            "&H00F16663,1,0,0,0,100,100,0,0,1,1.5,0,2,36,36,44,1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    if banner_line:
        lines.append(f"Dialogue: 0,0:00:00.00,{end_ts},BrandBanner,,0,0,0,,{banner_line}")
    if hook_line:
        lines.append(f"Dialogue: 0,0:00:00.00,{end_ts},HookTitle,,0,0,0,,{hook_line}")
    if cta_line:
        lines.append(f"Dialogue: 0,0:00:00.00,{end_ts},CtaDock,,0,0,0,,{cta_line}")

    captions = script_json.get("captions") or []
    for cap in captions:
        if not isinstance(cap, dict):
            continue
        text = str(cap.get("text") or "").strip()
        if not text:
            continue
        start_ts = _format_ass_ts(int(cap.get("start_ms") or 0))
        cap_end_ts = _format_ass_ts(int(cap.get("end_ms") or total_ms))
        highlight = str(cap.get("highlight_word") or cap.get("highlightWord") or "")
        styled = _highlight_caption_ass(text, highlight)
        lines.append(f"Dialogue: 1,{start_ts},{cap_end_ts},Caption,,0,0,0,,{styled}")

    return "\n".join(lines) + "\n"


def _try_remotion_cli_render(
    job_id: str,
    script_json: dict[str, Any],
    final_mp4_path: Path,
) -> bool:
    """Optionally render full React composition via Remotion CLI when USE_REMOTION_CLI=true."""
    if not settings.use_remotion_cli:
        return False
    remotion_dir = REPO_ROOT / "packages" / "remotion"
    npx_exe = shutil.which("npx")
    if not remotion_dir.exists() or not npx_exe:
        return False

    props_path = final_mp4_path.parent / f"{job_id}_props.json"
    props_payload = {
        "productTitle": script_json.get("product_title", "Featured Product"),
        "brandName": script_json.get("brand", ""),
        "priceDisplay": script_json.get("price_badge", ""),
        "originalPriceDisplay": script_json.get("original_price_display", ""),
        "discountBadge": script_json.get("discount_badge", ""),
        "currency": script_json.get("currency", ""),
        "targetLanguage": script_json.get("target_language", "ur"),
        "adAngle": script_json.get("ad_angle", "problem_solution"),
        "hookText": script_json.get("hook", ""),
        "ctaText": script_json.get("cta_text", ""),
        "captions": script_json.get("captions", []),
        "durationInFrames": script_json.get("duration_in_frames", 120),
    }
    lang_code = str(script_json.get("target_language") or "ur").upper()
    comp_id = f"VerticalAd-{lang_code if lang_code in {'UR', 'AR', 'HI', 'EN'} else 'UR'}"
    try:
        props_path.write_text(json.dumps(props_payload, ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            [
                npx_exe,
                "remotion",
                "render",
                "src/index.ts",
                comp_id,
                str(final_mp4_path),
                f"--props={props_path}",
            ],
            cwd=str(remotion_dir),
            check=True,
            timeout=120.0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        validate_mp4_file(final_mp4_path, require_audio=False, min_duration_seconds=0.5)
        return True
    except Exception:
        return False
    finally:
        props_path.unlink(missing_ok=True)


def _run_ffmpeg_encode(
    ffmpeg_exe: str,
    source_video_path: Path,
    voiceover_wav_path: Path,
    final_mp4_path: Path,
    script_json: dict[str, Any],
    vf_chain: str | None,
    cwd: Path | None = None,
) -> bool:
    """Run FFmpeg muxing source video, localized overlays, and required WAV voiceover."""
    if not voiceover_wav_path.exists():
        raise CompositorError(f"Voiceover WAV missing at {voiceover_wav_path}")

    cmd: list[str] = [
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
    ]
    if vf_chain:
        cmd.extend(
            ["-vf", vf_chain, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        )
    else:
        cmd.extend(["-c:v", "copy"])

    cmd.extend(
        [
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
    )
    subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120.0,
    )
    validate_mp4_file(final_mp4_path, require_audio=True, min_duration_seconds=0.5)
    return True


def composite_final_video(
    job_id: str,
    source_video_path: Path,
    voiceover_wav_path: Path,
    script_json: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    """Composite source video + localized overlays + voiceover into a verified MP4."""
    if not source_video_path.exists():
        raise CompositorError(f"Source video clip does not exist: {source_video_path}")
    if not voiceover_wav_path.exists():
        raise CompositorError(f"Voiceover audio file does not exist: {voiceover_wav_path}")

    target_dir = output_dir or RENDERS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    final_mp4_path = target_dir / f"{job_id}.mp4"

    if _try_remotion_cli_render(job_id, script_json, final_mp4_path):
        return final_mp4_path

    ass_path = target_dir / f"{job_id}.ass"
    drawbox_filter = (
        "drawbox=x=0:y=0:w=iw:h=88:color=0x09090B@0.82:t=fill,"
        "drawbox=x=24:y=102:w=iw-48:h=120:color=0x18181B@0.76:t=fill,"
        "drawbox=x=20:y=ih-280:w=iw-40:h=142:color=0x09090B@0.78:t=fill,"
        "drawbox=x=28:y=ih-88:w=iw-56:h=58:color=0x6366F1@0.94:t=fill"
    )

    try:
        ffmpeg_exe = get_ffmpeg_binary()
        ass_path.write_text(_build_ass_subtitles(script_json), encoding="utf-8")

        for vf_chain, cwd in [
            (f"{drawbox_filter},ass={ass_path.name}", target_dir),
            (drawbox_filter, None),
            (None, None),
        ]:
            try:
                if _run_ffmpeg_encode(
                    ffmpeg_exe,
                    source_video_path,
                    voiceover_wav_path,
                    final_mp4_path,
                    script_json,
                    vf_chain=vf_chain,
                    cwd=cwd,
                ):
                    return final_mp4_path
            except Exception:
                final_mp4_path.unlink(missing_ok=True)
                continue
    finally:
        ass_path.unlink(missing_ok=True)

    raise CompositorError(f"All FFmpeg encoding attempts failed for job {job_id}.")
