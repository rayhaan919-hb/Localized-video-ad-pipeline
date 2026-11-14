"""Localized ad script generator (Urdu, Arabic, Hindi, English) and TTS WAV synthesizer."""

from __future__ import annotations

import base64
import json
import math
import re
import struct
import wave
from pathlib import Path
from typing import Any

import httpx

from app.config import AUDIO_DIR, settings

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


def _cap(text: str, highlight_word: str) -> dict[str, str]:
    return {"text": text, "highlight_word": highlight_word}


ANGLE_OVERRIDES: dict[str, dict[str, dict[str, Any]]] = {
    "ugc_testimonial": {
        "ur": {
            "hook_template": "میرا ذاتی تجربہ: صرف 7 دن میں {title} نے کمال کر دکھایا!",
            "cta_text": "خود آزمائیں — 100% منی بیک گارنٹی کے ساتھ",
            "captions": [
                _cap("پہلے میں بھی شک میں تھی مگر رزلٹ حیران کن ہے!", "حیران"),
                _cap("روزانہ استعمال سے واضح اور قدرتی فرق محسوس کریں", "قدرتی"),
                _cap("ہزاروں مطمئن کسٹمرز کی اولین پسند — ابھی منگوائیں!", "اولین"),
            ],
        },
        "ar": {
            "hook_template": "تجربتي الحقيقية: لم أتوقع هذه النتيجة من {title}!",
            "cta_text": "اطلبه الآن وجرّبه بنفسك مع ضمان الجودة",
            "captions": [
                _cap("من أول أسبوع لاحظت فرقاً واضحاً ومذهلاً!", "مذهلاً"),
                _cap("ملمس فاخر وسهل الاستخدام في روتينك اليومي", "فاخر"),
                _cap("أكثر من 10,000 عميل سعيد — انضم إليهم اليوم!", "سعيد"),
            ],
        },
        "hi": {
            "hook_template": "मेरा असली रिव्यू: 7 दिनों में {title} ने सब बदल दिया!",
            "cta_text": "आज ही ट्राई करें — हजारों खुश ग्राहकों की पसंद",
            "captions": [
                _cap("पहले मुझे भी यकीन नहीं था, पर रिजल्ट देख कर दंग रह गई!", "रिजल्ट"),
                _cap("हल्का फॉर्मूला जो हर दिन बेहतरीन असर दिखाए", "बेहतरीन"),
                _cap("सीमित स्टॉक बाकी — अभी अपना ऑर्डर बुक करें!", "बुक"),
            ],
        },
        "en": {
            "hook_template": "Honest 7-day review: why everyone is switching to {title}.",
            "cta_text": "Try It Risk-Free — Cash on Delivery & Express Shipping",
            "captions": [
                _cap("I was skeptical at first until day three hit.", "day three"),
                _cap("Lightweight texture with immediate, visible payoff.", "immediate"),
                _cap("Over 10,000 verified five-star D2C reviews.", "five-star"),
            ],
        },
    },
    "flash_sale": {
        "ur": {
            "hook_template": "فلیش سیل الرٹ! {title} پر آج تک کی سب سے بڑی رعایت!",
            "cta_text": "فوری آرڈر کریں — 40% فلیش ڈسکاؤنٹ صرف آج!",
            "captions": [
                _cap("صرف آج کے لیے خصوصی قیمت — موقع ہاتھ سے نہ جانے دیں!", "خصوصی"),
                _cap("پریمیم کوالٹی اب ناقابلِ یقین رعایت کے ساتھ دستیاب", "رعایت"),
                _cap("آخری چند یونٹس باقی — ابھی کلک کر کے بک کریں!", "آخری"),
            ],
        },
        "ar": {
            "hook_template": "عرض خاطف لفترة محدودة! احصل على {title} بخصم استثنائي!",
            "cta_text": "تسوق الآن — خصم حصري حتى نفاد الكمية",
            "captions": [
                _cap("تخفيض استثنائي ينتهي منتصف الليل — لا تفوته!", "استثنائي"),
                _cap("نفس الجودة الفاخرة بسعر لا يُقارن اليوم فقط", "الفاخرة"),
                _cap("كمية محدودة جداً — اضغط للطلب الفوري الآن!", "الفوري"),
            ],
        },
        "hi": {
            "hook_template": "फ्लैश सेल लाइव! {title} पर पाएं साल का सबसे बड़ा डिस्काउंट!",
            "cta_text": "अभी खरीदें — आज रात 12 बजे ऑफर समाप्त",
            "captions": [
                _cap("सिर्फ आज के लिए भारी छूट — मौका हाथ से न जाने दें!", "भारी छूट"),
                _cap("प्रीमियम क्वालिटी अब बेहद किफायती दाम में", "किफायती"),
                _cap("स्टॉक तेजी से खत्म हो रहा है — अभी ऑर्डर करें!", "खत्म"),
            ],
        },
        "en": {
            "hook_template": "Flash drop active now — save big on {title} before midnight!",
            "cta_text": "Claim Offer Now — Limited Inventory Remaining",
            "captions": [
                _cap("Today-only pricing while launch batch lasts.", "Today-only"),
                _cap("Same flagship quality at our lowest drop price.", "flagship"),
                _cap("Almost sold out — lock yours in before the timer hits zero.", "sold out"),
            ],
        },
    },
    "unboxing": {
        "ur": {
            "hook_template": "آئیے ان باکس کرتے ہیں جدید {title} — فرسٹ امپریشن!",
            "cta_text": "اپنا پیکج آرڈر کریں — 48 گھنٹے میں ڈلیوری",
            "captions": [
                _cap("لگژری پیکجنگ اور شاندار فنشنگ پہلی نظر میں بھا جائے!", "لگژری"),
                _cap("باکس کھولتے ہی پریمیم معیار کا واضح احساس", "پریمیم"),
                _cap("آج ہی منگوائیں اور خود ان باکسنگ کا مزہ لیں!", "ان باکسنگ"),
            ],
        },
        "ar": {
            "hook_template": "فتح صندوق {title} الجديد — نظرة أولى عن قرب!",
            "cta_text": "اطلب نسختك الآن مع تغليف فاخر وشحن سريع",
            "captions": [
                _cap("تغليف أنيق وتفاصيل متقنة من اللحظة الأولى!", "أنيق"),
                _cap("تصميم عملي وجودة تستحق كل ريال تدفعه", "متقنة"),
                _cap("متوفر الآن للتوصيل السريع — اطلبه اليوم!", "السريع"),
            ],
        },
        "hi": {
            "hook_template": "चलिए अनबॉक्स करते हैं प्रीमियम {title} — फर्स्ट लुक!",
            "cta_text": "अपना बॉक्स मंगाएं — सुरक्षित और तेज डिलीवरी",
            "captions": [
                _cap("लग्ज़री पैकेजिंग और शानदार फर्स्ट इम्प्रेशन!", "लग्ज़री"),
                _cap("बॉक्स के अंदर हर डिटेल परफेक्ट क्वालिटी के साथ", "परफेक्ट"),
                _cap("आज ही ऑर्डर करें और प्रीमियम अनुभव पाएं!", "प्रीमियम"),
            ],
        },
        "en": {
            "hook_template": "Unbox the flagship {title} with us — crisp studio close-up.",
            "cta_text": "Order Yours Today — Arrives in Gift-Ready Packaging",
            "captions": [
                _cap("Tactile matte unboxing engineered down to the seal.", "Tactile"),
                _cap("Precision finish and daily-ready accessories inside.", "Precision"),
                _cap("Shipping daily — tap to get yours delivered fast.", "Shipping"),
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
    """Normalize caption timing spans across the requested render duration."""
    count = max(1, len(raw_captions))
    total_ms = max(1000, int(round(duration_seconds * 1000)))
    step_ms = total_ms // count
    scaled: list[dict[str, Any]] = []

    near_default = abs(duration_seconds - 2.0) < 0.05
    for idx, cap in enumerate(raw_captions):
        explicit_start = cap.get("start_ms")
        explicit_end = cap.get("end_ms")
        if explicit_start is not None and explicit_end is not None and near_default:
            start_ms = int(explicit_start)
            end_ms = int(explicit_end)
        else:
            start_ms = idx * step_ms
            end_ms = total_ms if idx == count - 1 else (idx + 1) * step_ms

        raw_sf = cap.get("startFrame")
        raw_ef = cap.get("endFrame")
        start_frame = (
            int(raw_sf)
            if raw_sf is not None and near_default
            else int(round((start_ms / 1000.0) * fps))
        )
        end_frame = (
            int(raw_ef)
            if raw_ef is not None and near_default
            else int(round((end_ms / 1000.0) * fps))
        )
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
    """Optionally enhance ad copy via Gemini REST when GOOGLE_API_KEY is active in live mode."""
    api_key = settings.effective_google_api_key
    if not api_key or settings.is_mock_veo:
        return None

    lang_name = LANGUAGE_PROFILES.get(lang, LANGUAGE_PROFILES["en"])["language_name"]
    title = product_metadata.get("title", "Product")
    brand = product_metadata.get("brand", "Brand")
    price = product_metadata.get("price", "")
    features = ", ".join(product_metadata.get("features", [])[:3])
    description = product_metadata.get("description", "")

    prompt = (
        f"You are a direct-response D2C video ad copywriter. Write native {lang_name} ({lang}) "
        f"vertical short-form ad copy for angle '{ad_angle}'.\n"
        f"Product: {title} by {brand} ({price}). Features: {features}. {description}\n"
        'Return strict JSON only: {"hook": "...", "cta_text": "...", '
        '"captions": [{"text": "...", "highlight_word": "..."}, '
        '{"text": "...", "highlight_word": "..."}, {"text": "...", "highlight_word": "..."}]}'
    )
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6},
    }
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(endpoint, json=payload)
            if resp.status_code != 200:
                return None
            data = resp.json()
        raw_text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
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
    duration_seconds: float = 2.0,
) -> dict[str, Any]:
    """Generate a localized 9:16 D2C video ad script with RTL/Nastaliq metadata and captions."""
    lang = target_language if target_language in LANGUAGE_PROFILES else "en"
    profile = LANGUAGE_PROFILES[lang]
    props = custom_props or {}

    resolved_angle = str(
        props.get("adAngle") or props.get("ad_angle") or ad_angle or "problem_solution"
    )
    angle_block = ANGLE_OVERRIDES.get(resolved_angle, {}).get(lang, {})

    fps = int(props.get("fps") or 30)
    if props.get("durationInFrames") and duration_seconds == 2.0:
        duration_seconds = max(1.0, min(15.0, float(props["durationInFrames"]) / max(1, fps)))
    duration_seconds = max(1.0, min(15.0, float(duration_seconds)))

    title = str(
        props.get("productTitle")
        or props.get("product_title")
        or product_metadata.get("title")
        or "Signature D2C Product"
    ).strip()
    brand = str(
        props.get("brandName")
        or props.get("brand")
        or product_metadata.get("brand")
        or "Aura D2C"
    ).strip()
    price = str(
        props.get("priceDisplay")
        or props.get("price_badge")
        or product_metadata.get("price")
        or "$39.00"
    ).strip()
    currency = str(props.get("currency") or product_metadata.get("currency") or "USD").strip()
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

    veo_prompt = str(
        props.get("veoPrompt")
        or (
            f"Vertical 9:16 cinematic commercial b-roll of {title} by {brand}, "
            f"angle: {resolved_angle}, studio rim lighting, macro product hero shot, "
            f"high-contrast luxury D2C aesthetic, 30fps photorealistic motion."
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
        "aspect_ratio": "9:16",
        "fps": fps,
        "duration_ms": int(round(duration_seconds * 1000)),
        "duration_in_frames": int(round(duration_seconds * fps)),
    }


def _try_cloud_tts_wav(wav_path: Path, script_json: dict[str, Any], lang: str) -> bool:
    """Call Google Cloud Text-to-Speech v1 REST API when live credentials are configured."""
    if settings.is_mock_veo:
        return False
    api_key = settings.effective_google_api_key
    token = settings.effective_vertex_access_token
    if not api_key and not token:
        return False

    lang_codes = {"ur": "ur-PK", "ar": "ar-XA", "hi": "hi-IN", "en": "en-US"}
    text_to_speak = str(script_json.get("tts_text") or script_json.get("hook") or "").strip()
    if not text_to_speak:
        return False

    url = "https://texttospeech.googleapis.com/v1/text:synthesize"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        url = f"{url}?key={api_key}"
    elif token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "input": {"text": text_to_speak[:900]},
        "voice": {"languageCode": lang_codes.get(lang, "en-US")},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000},
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                return False
            encoded = resp.json().get("audioContent")
            if not encoded:
                return False
            wav_bytes = base64.b64decode(encoded)
            if len(wav_bytes) < 512:
                return False
            wav_path.write_bytes(wav_bytes)
            return True
    except Exception:
        return False


def synthesize_voiceover_wav(
    job_id: str,
    script_json: dict[str, Any],
    output_dir: Path | None = None,
    duration_seconds: float | None = None,
    sample_rate: int = 24000,
) -> Path:
    """Synthesize a real 16-bit PCM WAV voiceover (Cloud TTS live or vocal-formant cadence)."""
    target_dir = output_dir or AUDIO_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    wav_path = target_dir / f"{job_id}.wav"

    lang = str(script_json.get("target_language", "en"))
    if _try_cloud_tts_wav(wav_path, script_json, lang):
        return wav_path

    if duration_seconds is None:
        duration_seconds = float(script_json.get("duration_ms", 2000)) / 1000.0
    duration_seconds = max(1.0, min(15.0, float(duration_seconds)))

    profile = LANGUAGE_PROFILES.get(lang, LANGUAGE_PROFILES["en"])
    base_freq = float(profile.get("base_freq", 190.0))

    captions = script_json.get("captions") or []
    pause_windows = [
        (float(cap.get("end_ms", 0)) / 1000.0)
        for cap in captions[:-1]
        if isinstance(cap, dict) and cap.get("end_ms")
    ]

    total_samples = int(duration_seconds * sample_rate)
    frames = bytearray()

    for i in range(total_samples):
        t = i / sample_rate
        # Syllable modulation (~5.2 syllables/sec) plus brief dips between caption phrases
        vibrato = 0.3 * math.sin(2.0 * math.pi * 1.1 * t)
        syllable_wave = 0.55 + 0.45 * math.sin(2.0 * math.pi * 5.2 * t + vibrato)
        phrase_pause = 1.0
        for pw in pause_windows:
            dist = abs(t - pw)
            if dist < 0.055:
                phrase_pause = min(phrase_pause, max(0.12, dist / 0.055))

        fade_in = min(1.0, t / 0.05)
        fade_out = min(1.0, (duration_seconds - t) / 0.08)
        envelope = max(0.0, syllable_wave * phrase_pause * fade_in * fade_out)

        # Prosody pitch contour + glottal F0 + vocal-tract F1/F2 formant emphasis
        intonation = 1.0 + 0.11 * math.sin(2.0 * math.pi * 1.4 * t) - 0.08 * (t / duration_seconds)
        f0 = base_freq * intonation
        f1 = 520.0 + 180.0 * math.sin(2.0 * math.pi * 2.1 * t)
        f2 = 1480.0 + 360.0 * math.cos(2.0 * math.pi * 1.7 * t)

        glottal = (
            math.sin(2.0 * math.pi * f0 * t)
            + 0.48 * math.sin(2.0 * math.pi * (f0 * 2.0) * t)
            + 0.24 * math.sin(2.0 * math.pi * (f0 * 3.0) * t)
        )
        formant = 0.30 * math.sin(2.0 * math.pi * f1 * t) + 0.16 * math.sin(2.0 * math.pi * f2 * t)

        sample_val = int(9600.0 * envelope * (glottal + formant) / 2.18)
        sample_val = max(-32767, min(32767, sample_val))
        frames.extend(struct.pack("<h", sample_val))

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))

    return wav_path
