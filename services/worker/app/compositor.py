"""FFmpeg compositor merging 9:16 Veo video clips, TTS voiceover, and caption metadata."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.config import RENDERS_DIR, REPO_ROOT, settings
from app.veo import ensure_sample_fixture, get_ffmpeg_binary


def _format_ass_ts(ms: int) -> str:
    """Convert milliseconds to ASS timestamp format H:MM:SS.cc."""
    clamped = max(0, int(ms))
    total_cs = clamped // 10
    cs = total_cs % 100
    total_s = total_cs // 100
    sec = total_s % 60
    minutes = (total_s // 60) % 60
    hours = total_s // 3600
    return f"{hours}:{minutes:02d}:{sec:02d}.{cs:02d}"


def _escape_ass(text: str) -> str:
    """Escape curly braces and line breaks for safe ASS dialogue rendering."""
    cleaned = str(text or "").replace("{", "(").replace("}", ")")
    return cleaned.replace("\r\n", "\\N").replace("\n", "\\N").strip()


def _highlight_caption_ass(text: str, highlight_word: str) -> str:
    """Apply Indigo (#6366F1 -> BGR &HF16663&) emphasis to the caption highlight word."""
    escaped = _escape_ass(text)
    hw = _escape_ass(highlight_word)
    if hw and hw in escaped:
        accent = f"{{\\c&HF16663&}}{hw}{{\\c&HFAFAFA&}}"
        return escaped.replace(hw, accent, 1)
    return escaped


def _build_ass_subtitles(script_json: dict[str, Any]) -> str:
    """Build an ASS subtitle script with RTL/LTR banner, hook, timed captions, and CTA."""
    font_name = str(script_json.get("font_family") or "Arial").strip() or "Arial"
    total_ms = max(1500, int(script_json.get("duration_ms") or 2000))
    end_ts = _format_ass_ts(total_ms)

    brand = _escape_ass(str(script_json.get("brand") or "Localized D2C"))
    price = _escape_ass(str(script_json.get("price_badge") or ""))
    discount = _escape_ass(str(script_json.get("discount_badge") or ""))
    banner_parts = [part for part in [brand, price, discount] if part]
    banner_line = "  |  ".join(banner_parts)

    hook_line = _escape_ass(str(script_json.get("hook") or script_json.get("product_title") or ""))
    cta_line = _escape_ass(str(script_json.get("cta_text") or ""))

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 540",
        "PlayResY: 960",
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
            "&HA609090B,1,0,0,0,100,100,0,0,1,2.5,1,8,34,34,116,1"
        ),
        (
            f"Style: Caption,{font_name},28,&H00FAFAFA,&H00FFFFFF,&H0009090B,"
            "&HB309090B,1,0,0,0,100,100,0,0,1,3,1,2,32,32,188,1"
        ),
        (
            f"Style: CtaDock,{font_name},20,&H00FFFFFF,&H00FFFFFF,&H00463731,"
            "&H00F16663,1,0,0,0,100,100,0,0,1,1.5,0,2,36,36,48,1"
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
        "productTitle": script_json.get("product_title", "Signature Product"),
        "brandName": script_json.get("brand", "Localized D2C"),
        "priceDisplay": script_json.get("price_badge", ""),
        "originalPriceDisplay": script_json.get("original_price_display", ""),
        "discountBadge": script_json.get("discount_badge", ""),
        "currency": script_json.get("currency", "USD"),
        "targetLanguage": script_json.get("target_language", "ur"),
        "adAngle": script_json.get("ad_angle", "problem_solution"),
        "hookText": script_json.get("hook", ""),
        "ctaText": script_json.get("cta_text", ""),
        "captions": script_json.get("captions", []),
        "durationInFrames": script_json.get("duration_in_frames", 60),
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
        return final_mp4_path.exists() and final_mp4_path.stat().st_size > 1024
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
    """Run FFmpeg with optional video filters and voiceover AAC audio mux."""
    has_wav = voiceover_wav_path.exists()
    cmd: list[str] = [ffmpeg_exe, "-y", "-i", str(source_video_path)]
    if has_wav:
        cmd.extend(["-i", str(voiceover_wav_path), "-map", "0:v:0", "-map", "1:a:0"])
    else:
        cmd.extend(["-map", "0:v:0", "-map", "0:a:0?"])

    if vf_chain:
        cmd.extend(
            ["-vf", vf_chain, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        )
    else:
        cmd.extend(["-c:v", "copy"])

    if has_wav:
        cmd.extend(["-c:a", "aac", "-b:a", "128k", "-shortest"])

    cmd.extend(
        [
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
    )
    return final_mp4_path.exists() and final_mp4_path.stat().st_size > 1024


def composite_final_video(
    job_id: str,
    source_video_path: Path,
    voiceover_wav_path: Path,
    script_json: dict[str, Any],
    output_dir: Path | None = None,
) -> Path:
    """Composite the 9:16 clip with burned-in RTL/LTR overlays and TTS voiceover."""
    target_dir = output_dir or RENDERS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    final_mp4_path = target_dir / f"{job_id}.mp4"

    duration_seconds = float(script_json.get("duration_ms", 2000)) / 1000.0
    if not source_video_path.exists():
        source_video_path = ensure_sample_fixture(duration_seconds=duration_seconds)

    if _try_remotion_cli_render(job_id, script_json, final_mp4_path):
        return final_mp4_path

    ass_path = target_dir / f"{job_id}.ass"
    drawbox_filter = (
        "drawbox=x=0:y=0:w=iw:h=88:color=0x09090B@0.82:t=fill,"
        "drawbox=x=24:y=102:w=iw-48:h=126:color=0x18181B@0.76:t=fill,"
        "drawbox=x=20:y=660:w=iw-40:h=142:color=0x09090B@0.78:t=fill,"
        "drawbox=x=28:y=874:w=iw-56:h=58:color=0x6366F1@0.94:t=fill"
    )

    try:
        ffmpeg_exe = get_ffmpeg_binary()
        ass_path.write_text(_build_ass_subtitles(script_json), encoding="utf-8")

        # Pass relative ass filename with cwd=target_dir so Windows drive colons never break libass.
        full_vf = f"{drawbox_filter},ass={ass_path.name}"
        try:
            if _run_ffmpeg_encode(
                ffmpeg_exe,
                source_video_path,
                voiceover_wav_path,
                final_mp4_path,
                script_json,
                vf_chain=full_vf,
                cwd=target_dir,
            ):
                return final_mp4_path
        except Exception:
            pass

        # Fallback 1: drawbox tonal chrome without libass
        try:
            if _run_ffmpeg_encode(
                ffmpeg_exe,
                source_video_path,
                voiceover_wav_path,
                final_mp4_path,
                script_json,
                vf_chain=drawbox_filter,
            ):
                return final_mp4_path
        except Exception:
            pass

        # Fallback 2: direct stream copy + AAC audio mux
        try:
            if _run_ffmpeg_encode(
                ffmpeg_exe,
                source_video_path,
                voiceover_wav_path,
                final_mp4_path,
                script_json,
                vf_chain=None,
            ):
                return final_mp4_path
        except Exception:
            pass
    finally:
        ass_path.unlink(missing_ok=True)

    shutil.copyfile(source_video_path, final_mp4_path)
    return final_mp4_path
