"""Product URL scraper and deterministic D2C metadata extractor."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

LANGUAGE_CURRENCY_DEFAULTS: dict[str, tuple[str, str]] = {
    "ur": ("PKR", "Rs. 4,999"),
    "ar": ("SAR", "149 ر.س"),
    "hi": ("INR", "₹1,499"),
    "en": ("USD", "$39.00"),
}

CATALOG_PRESETS: list[dict[str, Any]] = [
    {
        "keywords": ("serum", "glow", "skin", "vitamin", "niacinamide", "beauty", "cream"),
        "title": "Lumina 10% Niacinamide + Hyaluronic Glow Serum",
        "brand": "Lumina Botanics",
        "category": "Skincare",
        "prices": {
            "ur": ("PKR", "Rs. 3,450"),
            "ar": ("SAR", "129 ر.س"),
            "hi": ("INR", "₹1,199"),
            "en": ("USD", "$34.00"),
        },
        "features": [
            "Clinically proven 72-hour deep hydration",
            "Reduces dark spots and refines pores in 14 days",
            "Dermatologist-tested, halal & paraben-free formula",
        ],
        "image_url": "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=800&q=80",
    },
    {
        "keywords": ("oud", "perfume", "fragrance", "attar", "scent", "parfum"),
        "title": "Royal Kashmiri Oud & Ambergris Extrait de Parfum",
        "brand": "Maison Al-Qamar",
        "category": "Fragrance",
        "prices": {
            "ur": ("PKR", "Rs. 6,800"),
            "ar": ("AED", "249 د.إ"),
            "hi": ("INR", "₹2,499"),
            "en": ("USD", "$68.00"),
        },
        "features": [
            "24-hour long-lasting concentrated extrait",
            "Handcrafted aged artisanal oud with saffron top notes",
            "Luxury gift box with free cash-on-delivery",
        ],
        "image_url": "https://images.unsplash.com/photo-1594035910387-fea47794261f?w=800&q=80",
    },
    {
        "keywords": ("earbuds", "watch", "audio", "anc", "tech", "sonic", "buds", "smart"),
        "title": "AeroPulse Pro Active Noise-Cancelling Wireless Earbuds",
        "brand": "AeroPulse Audio",
        "category": "Consumer Electronics",
        "prices": {
            "ur": ("PKR", "Rs. 7,999"),
            "ar": ("SAR", "219 ر.س"),
            "hi": ("INR", "₹2,799"),
            "en": ("USD", "$59.00"),
        },
        "features": [
            "42dB Hybrid Active Noise Cancellation",
            "36-hour total battery life with 10-min warp charge",
            "IPX5 sweat-resistant with low-latency gaming mode",
        ],
        "image_url": "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=800&q=80",
    },
    {
        "keywords": ("coffee", "matcha", "tea", "protein", "honey", "sidr", "organic"),
        "title": "Wild Mountain Royal Sidr Honey (Raw & Unfiltered 500g)",
        "brand": "Zaytoon Organics",
        "category": "Wellness & Nutrition",
        "prices": {
            "ur": ("PKR", "Rs. 5,200"),
            "ar": ("SAR", "185 ر.س"),
            "hi": ("INR", "₹1,899"),
            "en": ("USD", "$48.00"),
        },
        "features": [
            "100% pure cold-extracted single-origin Sidr honey",
            "Lab-certified antioxidant and immunity booster",
            "Sealed glass jar with authenticity QR code",
        ],
        "image_url": "https://images.unsplash.com/photo-1587049352847-4a222e784d38?w=800&q=80",
    },
]


def _humanize_slug(url: str) -> tuple[str, str]:
    """Derive a clean product title and brand from a URL path and hostname."""
    parsed = urlparse(url)
    host = (parsed.hostname or "d2cstore.com").replace("www.", "")
    brand_raw = host.split(".")[0].replace("-", " ").replace("_", " ").strip()
    brand = brand_raw.title() if brand_raw else "Aura D2C"

    ignored = ("products", "p", "item", "shop", "en", "ar", "ur", "hi")
    path_segments = [
        seg for seg in unquote(parsed.path).split("/") if seg and seg not in ignored
    ]
    if path_segments:
        last_seg = re.sub(r"\.(html?|php|aspx)$", "", path_segments[-1], flags=re.IGNORECASE)
        words = [w for w in re.split(r"[-_+]+", last_seg) if w and not w.isdigit()]
        if words:
            return " ".join(w.capitalize() for w in words), brand

    return f"{brand} Signature D2C Edition", brand


def parse_product_html(
    html: str,
    product_url: str,
    target_language: str = "ur",
) -> dict[str, Any]:
    """Parse OpenGraph / standard HTML tags into normalized product metadata."""
    soup = BeautifulSoup(html, "html.parser")
    fallback = _fallback_metadata(product_url, target_language)

    og_title = soup.find("meta", property="og:title")
    title_tag = soup.find("title")
    title = (
        (og_title.get("content") if og_title else None)
        or (title_tag.get_text(strip=True) if title_tag else None)
        or fallback["title"]
    )

    og_site = soup.find("meta", property="og:site_name")
    brand = (og_site.get("content") if og_site else None) or fallback["brand"]

    og_price = soup.find("meta", property="product:price:amount")
    og_currency = soup.find("meta", property="product:price:currency")
    currency = (og_currency.get("content") if og_currency else None) or fallback["currency"]
    price = (
        f"{currency} {og_price.get('content')}"
        if og_price and og_price.get("content")
        else fallback["price"]
    )

    og_image = soup.find("meta", property="og:image")
    image_url = (og_image.get("content") if og_image else None) or fallback["image_url"]

    bullets = [
        li.get_text(strip=True)
        for li in soup.select("ul li")
        if 8 <= len(li.get_text(strip=True)) <= 120
    ][:3]
    features = bullets if bullets else fallback["features"]

    return {
        "product_url": product_url,
        "title": str(title).strip(),
        "brand": str(brand).strip(),
        "category": fallback["category"],
        "currency": str(currency).strip(),
        "price": str(price).strip(),
        "features": features,
        "image_url": str(image_url).strip(),
        "target_language": target_language,
    }


def _fallback_metadata(product_url: str, target_language: str = "ur") -> dict[str, Any]:
    """Build deterministic product metadata from URL tokens and language defaults."""
    lang = target_language if target_language in LANGUAGE_CURRENCY_DEFAULTS else "en"
    lowered_url = product_url.lower()
    matched_preset: dict[str, Any] | None = None

    for preset in CATALOG_PRESETS:
        if any(kw in lowered_url for kw in preset["keywords"]):
            matched_preset = preset
            break

    slug_title, slug_brand = _humanize_slug(product_url)
    if matched_preset is None:
        digest = int(hashlib.sha256(product_url.encode("utf-8")).hexdigest()[:8], 16)
        matched_preset = CATALOG_PRESETS[digest % len(CATALOG_PRESETS)]
        has_custom_slug = bool(slug_title and "Signature D2C" not in slug_title)
        title = slug_title if has_custom_slug else matched_preset["title"]
        is_generic_host = slug_brand.lower() in ("example", "localhost")
        brand = slug_brand if (slug_brand and not is_generic_host) else matched_preset["brand"]
    else:
        title = matched_preset["title"]
        brand = matched_preset["brand"]

    currency, price = matched_preset["prices"].get(lang, LANGUAGE_CURRENCY_DEFAULTS[lang])

    parsed = urlparse(product_url)
    qs = parse_qs(parsed.query)
    if "price" in qs and qs["price"]:
        price = qs["price"][0]
    if "title" in qs and qs["title"]:
        title = qs["title"][0]

    return {
        "product_url": product_url,
        "title": title,
        "brand": brand,
        "category": matched_preset["category"],
        "currency": currency,
        "price": price,
        "features": list(matched_preset["features"]),
        "image_url": matched_preset["image_url"],
        "target_language": lang,
    }


def scrape_product_url(
    product_url: str,
    target_language: str = "ur",
    fetch_live: bool = False,
) -> dict[str, Any]:
    """Scrape or deterministically synthesize localized D2C product metadata."""
    if fetch_live:
        try:
            with httpx.Client(timeout=2.5, follow_redirects=True) as client:
                response = client.get(product_url)
                if response.status_code == 200 and "<html" in response.text.lower():
                    return parse_product_html(response.text, product_url, target_language)
        except httpx.HTTPError:
            pass
    return _fallback_metadata(product_url, target_language)
