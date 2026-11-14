"""Product URL scraper and deterministic D2C metadata extractor."""

from __future__ import annotations

import hashlib
import json
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


def _extract_json_ld_product(soup: BeautifulSoup) -> dict[str, Any]:
    """Extract schema.org Product attributes from embedded JSON-LD blocks."""

    def _find_product(node: Any) -> dict[str, Any] | None:
        if isinstance(node, list):
            for item in node:
                found = _find_product(item)
                if found:
                    return found
        elif isinstance(node, dict):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(t).lower() == "product" for t in types if t):
                return node
            if "@graph" in node:
                return _find_product(node["@graph"])
        return None

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_text = script.string or script.get_text()
        if not raw_text:
            continue
        try:
            parsed = json.loads(raw_text)
        except Exception:
            continue
        product = _find_product(parsed)
        if not product:
            continue

        result: dict[str, Any] = {}
        if product.get("name"):
            result["name"] = str(product["name"]).strip()
        brand_obj = product.get("brand")
        if isinstance(brand_obj, dict) and brand_obj.get("name"):
            result["brand"] = str(brand_obj["name"]).strip()
        elif isinstance(brand_obj, str) and brand_obj.strip():
            result["brand"] = brand_obj.strip()
        if product.get("description"):
            result["description"] = str(product["description"]).strip()

        image_val = product.get("image")
        if isinstance(image_val, list) and image_val:
            first_img = image_val[0]
            if isinstance(first_img, dict):
                image_val = first_img.get("url") or first_img.get("contentUrl")
            else:
                image_val = first_img
        elif isinstance(image_val, dict):
            image_val = image_val.get("url") or image_val.get("contentUrl")
        if isinstance(image_val, str) and image_val.strip():
            result["image"] = image_val.strip()

        offers = product.get("offers")
        offer = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offer, dict):
            if offer.get("priceCurrency"):
                result["currency"] = str(offer["priceCurrency"]).strip()
            if offer.get("price") is not None:
                result["price_amount"] = str(offer["price"]).strip()
        return result

    return {}


def parse_product_html(
    html: str,
    product_url: str,
    target_language: str = "ur",
) -> dict[str, Any]:
    """Parse OpenGraph, JSON-LD Product schema, and HTML tags into normalized metadata."""
    soup = BeautifulSoup(html, "html.parser")
    fallback = _fallback_metadata(product_url, target_language)
    json_ld = _extract_json_ld_product(soup)

    og_title = soup.find("meta", property="og:title")
    title_tag = soup.find("title")
    title = (
        (og_title.get("content") if og_title else None)
        or json_ld.get("name")
        or (title_tag.get_text(strip=True) if title_tag else None)
        or fallback["title"]
    )

    og_site = soup.find("meta", property="og:site_name")
    brand = (
        (og_site.get("content") if og_site else None)
        or json_ld.get("brand")
        or fallback["brand"]
    )

    og_price = soup.find("meta", property="product:price:amount")
    og_currency = soup.find("meta", property="product:price:currency")
    currency = (
        (og_currency.get("content") if og_currency else None)
        or json_ld.get("currency")
        or fallback["currency"]
    )
    raw_amount = (og_price.get("content") if og_price else None) or json_ld.get("price_amount")
    price = f"{currency} {raw_amount}" if raw_amount else fallback["price"]

    og_image = soup.find("meta", property="og:image")
    image_url = (
        (og_image.get("content") if og_image else None)
        or json_ld.get("image")
        or fallback["image_url"]
    )

    og_desc = soup.find("meta", property="og:description")
    meta_desc = soup.find("meta", attrs={"name": "description"})
    description = (
        (og_desc.get("content") if og_desc else None)
        or (meta_desc.get("content") if meta_desc else None)
        or json_ld.get("description")
        or ""
    )
    description = re.sub(r"\s+", " ", str(description)).strip()[:220]

    bullets = [
        li.get_text(strip=True)
        for li in soup.select("ul li")
        if 8 <= len(li.get_text(strip=True)) <= 120
    ][:3]
    if bullets:
        features = bullets
    elif description:
        sentences = [s.strip() for s in re.split(r"[.!?]+", description) if len(s.strip()) >= 8]
        features = sentences[:3] if sentences else fallback["features"]
    else:
        features = fallback["features"]

    return {
        "product_url": product_url,
        "title": str(title).strip(),
        "brand": str(brand).strip(),
        "category": fallback["category"],
        "currency": str(currency).strip(),
        "price": str(price).strip(),
        "features": features,
        "description": description,
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


def _should_skip_live_fetch(product_url: str) -> bool:
    """Skip external HTTP calls for local/example/test hosts to keep tests offline-safe."""
    parsed = urlparse(product_url)
    host = (parsed.hostname or "").lower()
    if "simulate-fail" in product_url.lower():
        return True
    if host in {"localhost", "127.0.0.1", "example.com", "example.org", "example.net"}:
        return True
    return host.endswith((".local", ".test", ".example", ".invalid"))


def scrape_product_url(
    product_url: str,
    target_language: str = "ur",
    fetch_live: bool = True,
) -> dict[str, Any]:
    """Scrape live e-commerce metadata when reachable, falling back to deterministic tokens."""
    if fetch_live and not _should_skip_live_fetch(product_url):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            with httpx.Client(timeout=5.0, follow_redirects=True, headers=headers) as client:
                response = client.get(product_url)
                body_lower = response.text.lower()
                if response.status_code == 200 and ("<html" in body_lower or "<meta" in body_lower):
                    return parse_product_html(response.text, product_url, target_language)
        except httpx.HTTPError:
            pass
    return _fallback_metadata(product_url, target_language)
