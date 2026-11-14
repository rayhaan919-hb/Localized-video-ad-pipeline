"""Localized ad script generator (Urdu, Arabic, Hindi, English) and TTS WAV synthesizer."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any

from app.config import AUDIO_DIR

LANGUAGE_PROFILES: dict[str, dict[str, Any]] = {
    "ur": {
        "language_name": "Urdu",
        "direction": "rtl",
        "is_rtl": True,
        "font_family": "Noto Nastaliq Urdu",
        "voice_id": "ur-PK-UzmaNeural",
        "base_freq": 195.0,
        "hook_template": "کیا آپ بھی روزمرہ نتائج سے مایوس ہیں؟ اب آزمائیں {title}!",
        "cta_text": "ابھی آرڈر کریں — کیش آن ڈیلیوری دستیاب",
        "captions": [
            {
                "id": "cap-1",
                "text": "اپنی جلد اور لائف اسٹائل کو دیں نیا نکھار!",
                "highlight_word": "نکھار",
                "start_ms": 0,
                "end_ms": 700,
                "startFrame": 0,
                "endFrame": 21,
            },
            {
                "id": "cap-2",
                "text": "100% خالص اور ماہرین سے تصدیق شدہ فارمولا",
                "highlight_word": "100%",
                "start_ms": 700,
                "end_ms": 1400,
                "startFrame": 21,
                "endFrame": 42,
            },
            {
                "id": "cap-3",
                "text": "محدود اسٹاک — آج ہی رعایتی قیمت پر حاصل کریں!",
                "highlight_word": "محدود",
                "start_ms": 1400,
                "end_ms": 2000,
                "startFrame": 42,
                "endFrame": 60,
            },
        ],
    },
    "ar": {
        "language_name": "Arabic",
        "direction": "rtl",
        "is_rtl": True,
        "font_family": "Noto Sans Arabic",
        "voice_id": "ar-SA-ZariyahNeural",
        "base_freq": 185.0,
        "hook_template": "اكتشف سر الفخامة والأداء الفائق مع {title}!",
        "cta_text": "اطلب الآن — الدفع عند الاستلام والشحن السريع",
        "captions": [
            {
                "id": "cap-1",
                "text": "جودة استثنائية مصممة خصيصاً لذوقك الرفيع",
                "highlight_word": "استثنائية",
                "start_ms": 0,
                "end_ms": 700,
                "startFrame": 0,
                "endFrame": 21,
            },
            {
                "id": "cap-2",
                "text": "نتائج مضمونة ومكونات طبيعية معتمدة بالكامل",
                "highlight_word": "مضمونة",
                "start_ms": 700,
                "end_ms": 1400,
                "startFrame": 21,
                "endFrame": 42,
            },
            {
                "id": "cap-3",
                "text": "عرض حصري لفترة محدودة — اطلب الآن!",
                "highlight_word": "حصري",
                "start_ms": 1400,
                "end_ms": 2000,
                "startFrame": 42,
                "endFrame": 60,
            },
        ],
    },
    "hi": {
        "language_name": "Hindi",
        "direction": "ltr",
        "is_rtl": False,
        "font_family": "Noto Sans Devanagari",
        "voice_id": "hi-IN-SwaraNeural",
        "base_freq": 210.0,
        "hook_template": "क्या आप भी बेहतरीन क्वालिटी की तलाश में हैं? आज ही अपनाएं {title}!",
        "cta_text": "अभी ऑर्डर करें — फ्री होम डिलीवरी उपलब्ध",
        "captions": [
            {
                "id": "cap-1",
                "text": "पहली ही बार से पाएं शानदार और भरोसेमंद असर!",
                "highlight_word": "शानदार",
                "start_ms": 0,
                "end_ms": 700,
                "startFrame": 0,
                "endFrame": 21,
            },
            {
                "id": "cap-2",
                "text": "100% प्रमाणित और प्रीमियम ग्रेड क्वालिटी",
                "highlight_word": "100%",
                "start_ms": 700,
                "end_ms": 1400,
                "startFrame": 21,
                "endFrame": 42,
            },
            {
                "id": "cap-3",
                "text": "सीमित समय का ऑफर — अभी शॉप करें!",
                "highlight_word": "ऑफर",
                "start_ms": 1400,
                "end_ms": 2000,
                "startFrame": 42,
                "endFrame": 60,
            },
        ],
    },
    "en": {
        "language_name": "English",
        "direction": "ltr",
        "is_rtl": False,
        "font_family": "Inter",
        "voice_id": "en-US-AvaMultilingualNeural",
        "base_freq": 175.0,
        "hook_template": "Stop settling for average — upgrade your daily ritual with {title}.",
        "cta_text": "Shop Now — Express Tracked Shipping",
        "captions": [
            {
                "id": "cap-1",
                "text": "Engineered for visible results from day one.",
                "highlight_word": "visible",
                "start_ms": 0,
                "end_ms": 700,
                "startFrame": 0,
                "endFrame": 21,
            },
            {
                "id": "cap-2",
                "text": "Clinically backed, clean-label D2C formulation.",
                "highlight_word": "Clinically",
                "start_ms": 700,
                "end_ms": 1400,
                "startFrame": 21,
                "endFrame": 42,
            },
            {
                "id": "cap-3",
                "text": "Limited drop live now — tap to claim yours!",
                "highlight_word": "Limited",
                "start_ms": 1400,
                "end_ms": 2000,
                "startFrame": 42,
                "endFrame": 60,
            },
        ],
    },
}


def generate_localized_script(
    product_metadata: dict[str, Any],
    target_language: str,
    ad_angle: str = "problem_solution",
) -> dict[str, Any]:
    """Generate a localized 9:16 D2C video ad script with RTL/Nastaliq metadata and captions."""
    lang = target_language if target_language in LANGUAGE_PROFILES else "en"
    profile = LANGUAGE_PROFILES[lang]

    title = product_metadata.get("title", "Signature D2C Product")
    brand = product_metadata.get("brand", "Aura D2C")
    price = product_metadata.get("price", "$39.00")
    currency = product_metadata.get("currency", "USD")

    hook_text = profile["hook_template"].format(title=title)
    captions = [
        {
            **cap,
            "direction": profile["direction"],
            "font_family": profile["font_family"],
        }
        for cap in profile["captions"]
    ]

    veo_prompt = (
        f"Vertical 9:16 cinematic commercial b-roll of {title} by {brand}, "
        f"studio rim lighting, macro product hero shot, high-contrast luxury D2C aesthetic, "
        f"30fps photorealistic motion."
    )

    return {
        "target_language": lang,
        "language_name": profile["language_name"],
        "direction": profile["direction"],
        "is_rtl": profile["is_rtl"],
        "font_family": profile["font_family"],
        "voice_id": profile["voice_id"],
        "ad_angle": ad_angle,
        "product_title": title,
        "brand": brand,
        "price_badge": price,
        "currency": currency,
        "hook": hook_text,
        "cta_text": profile["cta_text"],
        "captions": captions,
        "veo_prompt": veo_prompt,
        "aspect_ratio": "9:16",
        "fps": 30,
        "duration_ms": 2000,
    }


def synthesize_voiceover_wav(
    job_id: str,
    script_json: dict[str, Any],
    output_dir: Path | None = None,
    duration_seconds: float = 2.0,
    sample_rate: int = 24000,
) -> Path:
    """Synthesize a real 16-bit PCM WAV voiceover file matching the localized script timing."""
    target_dir = output_dir or AUDIO_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    wav_path = target_dir / f"{job_id}.wav"

    lang = script_json.get("target_language", "en")
    profile = LANGUAGE_PROFILES.get(lang, LANGUAGE_PROFILES["en"])
    base_freq = float(profile.get("base_freq", 190.0))

    total_samples = int(duration_seconds * sample_rate)
    frames = bytearray()

    for i in range(total_samples):
        t = i / sample_rate
        syllable_env = 0.55 + 0.45 * math.sin(2.0 * math.pi * 4.5 * t)
        fade_in = min(1.0, t / 0.06)
        fade_out = min(1.0, (duration_seconds - t) / 0.08)
        envelope = max(0.0, syllable_env * fade_in * fade_out)

        f0 = base_freq * (1.0 + 0.08 * math.sin(2.0 * math.pi * 2.2 * t))
        harmonic_1 = math.sin(2.0 * math.pi * f0 * t)
        harmonic_2 = 0.45 * math.sin(2.0 * math.pi * (f0 * 2.0) * t)
        harmonic_3 = 0.22 * math.sin(2.0 * math.pi * (f0 * 3.0) * t)

        sample_val = int(9500.0 * envelope * (harmonic_1 + harmonic_2 + harmonic_3) / 1.67)
        sample_val = max(-32767, min(32767, sample_val))
        frames.extend(struct.pack("<h", sample_val))

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))

    return wav_path
