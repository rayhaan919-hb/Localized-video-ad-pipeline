"""Localized ad script generator (Urdu, Arabic, Hindi, English) and Cloud TTS v1 synthesizer."""

from __future__ import annotations

import base64
import io
import json
import math
import re
import struct
import time
import wave
from pathlib import Path
from typing import Any

import httpx

from app.config import AUDIO_DIR, settings
from app.veo import _resolve_vertex_bearer_token


class TTSError(Exception):
    """Base TTS synthesis error."""


class TTSConfigurationError(TTSError):
    """Raised when Cloud TTS credentials are missing in live mode."""


class TTSProviderError(TTSError):
    """Raised when Google Cloud TTS returns an error or invalid audio."""


LANGUAGE_PROFILES: dict[str, dict[str, Any]] = {
    "ur": {
        "language_name": "Urdu",
        "direction": "rtl",
        "is_rtl": True,
        "font_family": "Noto Nastaliq Urdu",
        "voice_id": "ur-PK-Standard-A",
        "cloud_lang": "ur-PK",
        "base_freq": 195.0,
        "hook_template": "کیا آپ بھی روزمرہ نتائج سے مایوس ہیں؟ اب آزمائیں {title}!",
        "cta_text": "ابھی آرڈر کریں — کیش آن ڈیلیوری دستیاب",
        "captions": [
            {
                "id": "cap-1",
                "text": "اپنی جلد اور لائف اسٹائل کو دیں نیا نکھار!",
                "highlight_word": "نکھار",
            },
            {
                "id": "cap-2",
                "text": "خالص اور معیاری فارمولا روزمرہ استعمال کے لیے",
                "highlight_word": "معیاری",
            },
            {
                "id": "cap-3",
                "text": "محدود اسٹاک — آج ہی آرڈر کریں!",
                "highlight_word": "محدود",
            },
        ],
    },
    "ar": {
        "language_name": "Arabic",
        "direction": "rtl",
        "is_rtl": True,
        "font_family": "Noto Sans Arabic",
        "voice_id": "ar-XA-Wavenet-A",
        "cloud_lang": "ar-XA",
        "base_freq": 185.0,
        "hook_template": "اكتشف روعة الأداء مع {title}!",
        "cta_text": "اطلب الآن — الشحن السريع والدفع عند الاستلام",
        "captions": [
            {
                "id": "cap-1",
                "text": "جودة استثنائية مصممة بعناية لذوقك",
                "highlight_word": "استثنائية",
            },
            {
                "id": "cap-2",
                "text": "تجربة يومية عملية بنتائج واضحة",
                "highlight_word": "عملية",
            },
            {
                "id": "cap-3",
                "text": "عرض حصري لفترة محدودة — اطلب الآن!",
                "highlight_word": "حصري",
            },
        ],
    },
    "hi": {
        "language_name": "Hindi",
        "direction": "ltr",
        "is_rtl": False,
        "font_family": "Noto Sans Devanagari",
        "voice_id": "hi-IN-Wavenet-A",
        "cloud_lang": "hi-IN",
        "base_freq": 210.0,
        "hook_template": "क्या आप भी बेहतरीन क्वालिटी की तलाश में हैं? आज ही अपनाएं {title}!",
        "cta_text": "अभी ऑर्डर करें — तेज़ होम डिलीवरी उपलब्ध",
        "captions": [
            {
                "id": "cap-1",
                "text": "पहली ही बार से पाएं शानदार और भरोसेमंद अनुभव!",
                "highlight_word": "शानदार",
            },
            {
                "id": "cap-2",
                "text": "प्रीमियम ग्रेड क्वालिटी हर रोज़ के लिए",
                "highlight_word": "प्रीमियम",
            },
            {
                "id": "cap-3",
                "text": "सीमित समय का ऑफर — अभी शॉप करें!",
                "highlight_word": "ऑफर",
            },
        ],
    },
    "en": {
        "language_name": "English",
        "direction": "ltr",
        "is_rtl": False,
        "font_family": "Inter",
        "voice_id": "en-US-Journey-F",
        "cloud_lang": "en-US",
        "base_freq": 175.0,
        "hook_template": "Upgrade your daily routine with {title}.",
        "cta_text": "Shop Now — Express Tracked Shipping",
        "captions": [
            {
                "id": "cap-1",
                "text": "Engineered for effortless daily performance.",
                "highlight_word": "performance",
            },
            {
                "id": "cap-2",
                "text": "Crafted with clean, high-grade materials.",
                "highlight_word": "high-grade",
            },
            {
                "id": "cap-3",
                "text": "Limited drop live now — claim yours today.",
                "highlight_word": "Limited",
            },
        ],
    },
}


def _cap(text: str, highlight_word: str) -> dict[str, str]:
    return {"text": text, "highlight_word": highlight_word}


ANGLE_OVERRIDES: dict[str, dict[str, dict[str, Any]]] = {
    "ugc_testimonial": {
        "ur": {
            "hook_template": "میرا ذاتی تجربہ: {title} نے روزمرہ روٹین آسان بنا دی!",
            "cta_text": "خود آزمائیں اور فرق محسوس کریں",
            "captions": [
                _cap("پہلے دن سے ہی استعمال میں بے حد آسان!", "آسان"),
                _cap("روزانہ استعمال سے واضح اور قدرتی فرق محسوس کریں", "قدرتی"),
                _cap("آج ہی اپنا آرڈر بک کروائیں!", "آرڈر"),
            ],
        },
        "ar": {
            "hook_template": "تجربتي الحقيقية مع {title} في روتيني اليومي!",
            "cta_text": "اطلبه الآن وجرّبه بنفسك",
            "captions": [
                _cap("من أول أسبوع لاحظت فرقاً واضحاً!", "واضحاً"),
                _cap("ملمس فاخر وسهل الاستخدام يومياً", "فاخر"),
                _cap("اطلبه اليوم قبل نفاد الكمية!", "اليوم"),
            ],
        },
        "hi": {
            "hook_template": "मेरा असली रिव्यू: {title} ने मेरा रूटीन बदल दिया!",
            "cta_text": "आज ही ट्राई करें और अनुभव साझा करें",
            "captions": [
                _cap("पहले दिन से इस्तेमाल में बेहद आसान!", "आसान"),
                _cap("हल्का और असरदार फॉर्मूला हर दिन के लिए", "असरदार"),
                _cap("सीमित स्टॉक — अभी अपना ऑर्डर बुक करें!", "बुक"),
            ],
        },
        "en": {
            "hook_template": "Honest review: why customers are switching to {title}.",
            "cta_text": "Try It Today — Fast Tracked Delivery",
            "captions": [
                _cap("Lightweight feel that fits any daily routine.", "daily"),
                _cap("Clean craftsmanship noticed from unboxing.", "craftsmanship"),
                _cap("Order now while launch batch lasts.", "launch"),
            ],
        },
    },
    "flash_sale": {
        "ur": {
            "hook_template": "خصوصی پیشکش! {title} محدود وقت کے لیے دستیاب!",
            "cta_text": "فوری آرڈر کریں اس سے پہلے کہ اسٹاک ختم ہو",
            "captions": [
                _cap("خصوصی آفر — موقع ہاتھ سے نہ جانے دیں!", "خصوصی"),
                _cap("پریمیم کوالٹی اب تیز ڈلیوری کے ساتھ", "پریمیم"),
                _cap("آخری چند یونٹس باقی — ابھی آرڈر کریں!", "آخری"),
            ],
        },
        "ar": {
            "hook_template": "عرض خاص لفترة محدودة على {title}!",
            "cta_text": "تسوق الآن حتى نفاد الكمية",
            "captions": [
                _cap("عرض استثنائي لفترة محدودة — لا تفوته!", "استثنائي"),
                _cap("نفس الجودة الفاخرة مع شحن سريع", "الفاخرة"),
                _cap("كمية محدودة جداً — اضغط للطلب الآن!", "الآن"),
            ],
        },
        "hi": {
            "hook_template": "स्पेशल ऑफर लाइव! {title} सीमित समय के लिए!",
            "cta_text": "अभी खरीदें — सीमित स्टॉक उपलब्ध",
            "captions": [
                _cap("सिर्फ सीमित समय की डील — मौका न चूकें!", "सीमित"),
                _cap("प्रीमियम क्वालिटी अब तेज़ डिलीवरी के साथ", "प्रीमियम"),
                _cap("स्टॉक तेजी से खत्म हो रहा है — अभी ऑर्डर करें!", "खत्म"),
            ],
        },
        "en": {
            "hook_template": "Limited drop active now — claim {title} before stock runs out!",
            "cta_text": "Claim Offer Now — Limited Inventory",
            "captions": [
                _cap("Active release window while stock remains.", "release"),
                _cap("Flagship quality shipped directly from our studio.", "Flagship"),
                _cap("Tap now to secure your order before it sells out.", "secure"),
            ],
        },
    },
    "unboxing": {
        "ur": {
            "hook_template": "آئیے ان باکس کرتے ہیں {title} — فرسٹ امپریشن!",
            "cta_text": "اپنا پیکج آج ہی آرڈر کریں",
            "captions": [
                _cap("شاندار پیکجنگ اور فنشنگ پہلی نظر میں بھا جائے!", "شاندار"),
                _cap("باکس کھولتے ہی پریمیم معیار کا واضح احساس", "پریمیم"),
                _cap("آج ہی منگوائیں اور خود ان باکسنگ کا مزہ لیں!", "ان باکسنگ"),
            ],
        },
        "ar": {
            "hook_template": "فتح صندوق {title} الجديد — نظرة أولى عن قرب!",
            "cta_text": "اطلب نسختك الآن مع تغليف أنيق",
            "captions": [
                _cap("تغليف أنيق وتفاصيل متقنة من اللحظة الأولى!", "أنيق"),
                _cap("تصميم عملي وجودة تستحق الاهتمام", "متقنة"),
                _cap("متوفر الآن للتوصيل السريع — اطلبه اليوم!", "السريع"),
            ],
        },
        "hi": {
            "hook_template": "चलिए अनबॉक्स करते हैं {title} — फर्स्ट लुक!",
            "cta_text": "अपना बॉक्स आज ही ऑर्डर करें",
            "captions": [
                _cap("प्रीमियम पैकेजिंग और शानदार फर्स्ट इम्प्रेशन!", "प्रीमियम"),
                _cap("बॉक्स के अंदर हर डिटेल बेहतरीन क्वालिटी के साथ", "बेहतरीन"),
                _cap("आज ही ऑर्डर करें और तेज़ डिलीवरी पाएं!", "डिलीवरी"),
            ],
        },
        "en": {
            "hook_template": "Unbox {title} with us — crisp studio close-up.",
            "cta_text": "Order Yours Today — Gift-Ready Packaging",
            "captions": [
                _cap("Tactile matte unboxing down to the seal.", "Tactile"),
                _cap("Precision finish and thoughtful essentials inside.", "Precision"),
                _cap("Shipping daily — tap to get yours fast.", "Shipping"),
            ],
        },
    },
}


def _scale_captions(
    raw_captions: list[dict[str, Any]],
    duration_seconds: float,
    fps: int,
    direction: str,
    font_family: str,
) -> list[dict[str, Any]]:
    """Normalize caption timing spans cleanly across the requested render duration."""
    count = max(1, len(raw_captions))
    total_ms = max(1000, int(round(duration_seconds * 1000)))
    step_ms = total_ms // count
    scaled: list[dict[str, Any]] = []

    for idx, cap in enumerate(raw_captions):
        start_ms = idx * step_ms
        end_ms = total_ms if idx == count - 1 else (idx + 1) * step_ms
        start_frame = int(round((start_ms / 1000.0) * fps))
        end_frame = int(round((end_ms / 1000.0) * fps))
        highlight = str(cap.get("highlight_word") or cap.get("highlightWord") or "").strip()

        scaled.append(
            {
                "id": str(cap.get("id") or f"cap-{idx + 1}"),
                "text": str(cap.get("text") or "").strip(),
                "highlight_word": highlight,
                "highlightWord": highlight,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "startFrame": start_frame,
                "endFrame": max(start_frame + 1, end_frame),
                "direction": direction,
                "font_family": font_family,
            }
        )
    return scaled


def _try_generate_gemini_copy(
    product_metadata: dict[str, Any],
    lang: str,
    ad_angle: str,
) -> dict[str, Any] | None:
    """Enhance ad copy via Gemini REST when GOOGLE_API_KEY is configured cleanly."""
    api_key = settings.effective_google_api_key
    if not api_key or settings.is_mock_veo:
        return None

    lang_name = LANGUAGE_PROFILES.get(lang, LANGUAGE_PROFILES["en"])["language_name"]
    title = str(product_metadata.get("title") or "Product").strip()
    brand = str(product_metadata.get("brand") or "").strip()
    price = str(product_metadata.get("price") or "").strip()
    features = ", ".join(product_metadata.get("features", [])[:3])
    description = str(product_metadata.get("description") or "").strip()

    facts = [f"Product: {title}"]
    if brand:
        facts.append(f"Brand: {brand}")
    if price:
        facts.append(f"Verified Price: {price}")
    if features:
        facts.append(f"Verified Features: {features}")
    if description:
        facts.append(f"Description: {description}")

    prompt = (
        f"You are a direct-response D2C video ad copywriter. Write native {lang_name} ({lang}) "
        f"vertical short-form ad copy for angle '{ad_angle}'. Only cite facts explicitly "
        "provided below; never invent prices, discounts, percentages, or medical claims not "
        "present in the facts.\n"
        + "\n".join(facts)
        + '\nReturn strict JSON only: {"hook": "...", "cta_text": "...", '
        '"captions": [{"text": "...", "highlight_word": "..."}, '
        '{"text": "...", "highlight_word": "..."}, {"text": "...", "highlight_word": "..."}]}'
    )
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.5},
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                endpoint,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
        raw_text = (
            data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        )
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            return None
        parsed = json.loads(match.group(0))
        if (
            isinstance(parsed, dict)
            and parsed.get("hook")
            and isinstance(parsed.get("captions"), list)
        ):
            return parsed
    except Exception:
        return None
    return None


def generate_localized_script(
    product_metadata: dict[str, Any],
    target_language: str,
    ad_angle: str = "problem_solution",
    custom_props: dict[str, Any] | None = None,
    duration_seconds: float = 4.0,
    aspect_ratio: str = "9:16",
) -> dict[str, Any]:
    """Generate a localized D2C video ad script strictly grounded in verified/user fields."""
    lang = target_language if target_language in LANGUAGE_PROFILES else "en"
    profile = LANGUAGE_PROFILES[lang]
    props = custom_props or {}

    resolved_angle = str(
        props.get("adAngle") or props.get("ad_angle") or ad_angle or "problem_solution"
    )
    angle_block = ANGLE_OVERRIDES.get(resolved_angle, {}).get(lang, {})

    fps = int(props.get("fps") or 30)
    duration_seconds = max(1.0, min(15.0, float(duration_seconds)))
    ratio = aspect_ratio if aspect_ratio in ("9:16", "16:9") else "9:16"

    title = str(
        props.get("productTitle")
        or props.get("product_title")
        or product_metadata.get("title")
        or "Featured Product"
    ).strip()
    brand = str(
        props.get("brandName") or props.get("brand") or product_metadata.get("brand") or ""
    ).strip()
    # Never fabricate a default "$39.00" price when price is missing!
    price = str(
        props.get("priceDisplay") or props.get("price_badge") or product_metadata.get("price") or ""
    ).strip()
    currency = str(props.get("currency") or product_metadata.get("currency") or "").strip()
    original_price = str(props.get("originalPriceDisplay") or "").strip()
    discount_badge = str(props.get("discountBadge") or "").strip()

    has_custom_copy = bool(props.get("hookText") and props.get("captions"))
    gemini_copy = (
        None
        if has_custom_copy
        else _try_generate_gemini_copy(product_metadata, lang, resolved_angle)
    )

    default_hook = (angle_block.get("hook_template") or profile["hook_template"]).format(
        title=title
    )
    hook_text = str(
        props.get("hookText")
        or props.get("hook")
        or (gemini_copy.get("hook") if gemini_copy else None)
        or default_hook
    ).strip()
    cta_text = str(
        props.get("ctaText")
        or props.get("cta_text")
        or (gemini_copy.get("cta_text") if gemini_copy else None)
        or angle_block.get("cta_text")
        or profile["cta_text"]
    ).strip()

    raw_captions: list[dict[str, Any]]
    if isinstance(props.get("captions"), list) and props["captions"]:
        raw_captions = props["captions"]
    elif gemini_copy and gemini_copy.get("captions"):
        raw_captions = gemini_copy["captions"]
    elif angle_block.get("captions"):
        raw_captions = angle_block["captions"]
    else:
        raw_captions = profile["captions"]

    captions = _scale_captions(
        raw_captions=raw_captions,
        duration_seconds=duration_seconds,
        fps=fps,
        direction=profile["direction"],
        font_family=profile["font_family"],
    )

    brand_phrase = f" by {brand}" if brand else ""
    veo_prompt = str(
        props.get("veoPrompt")
        or (
            f"Vertical {ratio} cinematic commercial showcase of {title}{brand_phrase}, "
            f"creative angle: {resolved_angle}, studio rim lighting, macro hero product framing, "
            f"30fps photorealistic commercial motion."
        )
    )

    tts_text = " ".join(
        part for part in [hook_text, *[c["text"] for c in captions], cta_text] if part
    )

    return {
        "target_language": lang,
        "language_name": profile["language_name"],
        "direction": profile["direction"],
        "is_rtl": profile["is_rtl"],
        "font_family": profile["font_family"],
        "voice_id": profile["voice_id"],
        "ad_angle": resolved_angle,
        "product_title": title,
        "brand": brand,
        "price_badge": price,
        "original_price_display": original_price,
        "discount_badge": discount_badge,
        "currency": currency,
        "hook": hook_text,
        "cta_text": cta_text,
        "captions": captions,
        "tts_text": tts_text,
        "veo_prompt": veo_prompt,
        "aspect_ratio": ratio,
        "fps": fps,
        "duration_ms": int(round(duration_seconds * 1000)),
        "duration_in_frames": int(round(duration_seconds * fps)),
    }


def _validate_wav_bytes(wav_bytes: bytes) -> float:
    """Validate WAV header, sample width/rate, and non-zero audio duration."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()
    except Exception as exc:
        raise TTSProviderError(f"Synthesized audio is not a valid RIFF/WAV stream: {exc}") from exc

    if nchannels < 1 or sampwidth < 1 or framerate < 8000 or nframes <= 0:
        raise TTSProviderError(
            "Synthesized WAV stream contains zero audio frames or invalid format."
        )
    return float(nframes) / float(framerate)


def _synthesize_cloud_tts_wav(
    wav_path: Path,
    script_json: dict[str, Any],
    lang: str,
    *,
    speaking_rate: float = 1.0,
    max_attempts: int = 3,
) -> Path:
    """Call Google Cloud Text-to-Speech v1 REST API with retries and WAV validation."""
    api_key = settings.effective_google_api_key
    token = settings.effective_vertex_access_token
    if not api_key and not token:
        token = _resolve_vertex_bearer_token()
    if not api_key and not token:
        raise TTSConfigurationError(
            "Google Cloud Text-to-Speech requires GOOGLE_API_KEY, "
            "VERTEX_ACCESS_TOKEN, or ADC credentials."
        )

    profile = LANGUAGE_PROFILES.get(lang, LANGUAGE_PROFILES["en"])
    text_to_speak = str(script_json.get("tts_text") or script_json.get("hook") or "").strip()
    if not text_to_speak:
        raise TTSProviderError("Cannot synthesize narration: script narration text is empty.")

    rate = max(0.5, min(2.0, float(speaking_rate)))
    url = settings.GOOGLE_CLOUD_TTS_ENDPOINT
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif api_key:
        headers["x-goog-api-key"] = api_key

    payload = {
        "input": {"text": text_to_speak[:900]},
        "voice": {
            "languageCode": profile["cloud_lang"],
        },
        "audioConfig": {
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": 24000,
            "speakingRate": rate,
        },
    }

    last_err: Exception | None = None
    with httpx.Client(timeout=15.0) as client:
        for attempt in range(max_attempts):
            try:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                    time.sleep(0.5 * (2**attempt))
                    continue
                if resp.status_code >= 400:
                    raise TTSProviderError(
                        f"Google Cloud TTS API failed (HTTP {resp.status_code}): {resp.text[:300]}"
                    )
                encoded = resp.json().get("audioContent")
                if not encoded:
                    raise TTSProviderError("Google Cloud TTS response omitted audioContent.")
                wav_bytes = base64.b64decode(encoded)
                _validate_wav_bytes(wav_bytes)
                wav_path.write_bytes(wav_bytes)
                return wav_path
            except TTSProviderError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_err = exc
                if attempt < max_attempts - 1:
                    time.sleep(0.5 * (2**attempt))
                    continue
    raise TTSProviderError(f"Google Cloud TTS failed after {max_attempts} attempts: {last_err}")


def _generate_mock_tts_fixture(
    wav_path: Path,
    script_json: dict[str, Any],
    lang: str,
    duration_seconds: float,
    sample_rate: int = 24000,
) -> Path:
    """Create a deterministic test PCM WAV track strictly when MOCK_TTS=true in non-production."""
    dur = max(1.0, min(15.0, float(duration_seconds)))
    profile = LANGUAGE_PROFILES.get(lang, LANGUAGE_PROFILES["en"])
    base_freq = float(profile.get("base_freq", 190.0))

    captions = script_json.get("captions") or []
    pause_windows = [
        (float(cap.get("end_ms", 0)) / 1000.0)
        for cap in captions[:-1]
        if isinstance(cap, dict) and cap.get("end_ms")
    ]

    total_samples = int(dur * sample_rate)
    frames = bytearray()
    for i in range(total_samples):
        t = i / sample_rate
        syllable_wave = 0.55 + 0.45 * math.sin(2.0 * math.pi * 5.2 * t)
        phrase_pause = 1.0
        for pw in pause_windows:
            dist = abs(t - pw)
            if dist < 0.055:
                phrase_pause = min(phrase_pause, max(0.12, dist / 0.055))
        envelope = max(
            0.0, syllable_wave * phrase_pause * min(1.0, t / 0.05) * min(1.0, (dur - t) / 0.08)
        )
        f0 = base_freq * (1.0 + 0.1 * math.sin(2.0 * math.pi * 1.4 * t))
        sample_val = int(9600.0 * envelope * math.sin(2.0 * math.pi * f0 * t))
        frames.extend(struct.pack("<h", max(-32767, min(32767, sample_val))))

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))
    return wav_path


def synthesize_voiceover_wav(
    job_id: str,
    script_json: dict[str, Any],
    output_dir: Path | None = None,
    duration_seconds: float | None = None,
    sample_rate: int = 24000,
    mock_mode: bool | None = None,
) -> Path:
    """Synthesize spoken voiceover WAV via Google Cloud TTS, or test fixture only when mocked."""
    use_mock = settings.is_mock_tts if mock_mode is None else mock_mode
    if settings.is_production and use_mock:
        raise TTSConfigurationError("MOCK_TTS is forbidden when APP_ENV=production.")

    target_dir = output_dir or AUDIO_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    wav_path = target_dir / f"{job_id}.wav"
    lang = str(script_json.get("target_language", "en"))

    if not use_mock:
        return _synthesize_cloud_tts_wav(wav_path, script_json, lang)

    dur = (
        duration_seconds
        if duration_seconds is not None
        else float(script_json.get("duration_ms", 4000)) / 1000.0
    )
    return _generate_mock_tts_fixture(wav_path, script_json, lang, dur, sample_rate=sample_rate)
