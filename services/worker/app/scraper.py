"""Honest, SSRF-hardened product URL metadata extractor and image fetcher."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings

_ALLOWED_IMAGE_MAGIC: dict[bytes, tuple[str, str]] = {
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
}

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
    "::1",
    "0.0.0.0",
}


class ScraperError(Exception):
    """Base scraper error."""


class UnsafeUrlError(ScraperError):
    """Raised when a URL fails SSRF / private-network / scheme validation."""


def _is_forbidden_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
        or (
            isinstance(ip_obj, ipaddress.IPv6Address)
            and ip_obj.ipv4_mapped is not None
            and _is_forbidden_ip(ip_obj.ipv4_mapped)
        )
    )


def validate_public_http_url(url: str, *, allow_private_in_test: bool = False) -> str:
    """Validate HTTP(S) URL and block loopback, private, link-local, and metadata hosts."""
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise UnsafeUrlError("URL must be an absolute http:// or https:// address.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Embedded credentials in URL are not permitted.")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UnsafeUrlError("URL host is missing.")
    if allow_private_in_test:
        return cleaned

    if host in _BLOCKED_HOSTNAMES or host.endswith((".internal", ".local", ".localhost")):
        raise UnsafeUrlError(f"Blocked internal or metadata hostname: {host}")

    # Direct IP literal check first
    try:
        ip_literal = ipaddress.ip_address(host)
        if _is_forbidden_ip(ip_literal):
            raise UnsafeUrlError(f"Blocked private or non-routable IP address: {host}")
        return cleaned
    except ValueError:
        pass

    # DNS resolution check to defeat DNS-to-internal rebinding
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        for info in infos:
            sockaddr = info[4]
            resolved_ip = sockaddr[0].split("%")[0]
            ip_obj = ipaddress.ip_address(resolved_ip)
            if _is_forbidden_ip(ip_obj):
                raise UnsafeUrlError(f"URL host resolved to forbidden private IP: {resolved_ip}")
    except UnsafeUrlError:
        raise
    except OSError:
        # Unresolvable host will fail cleanly during httpx request instead of crashing here
        pass

    return cleaned


def _humanize_slug_suggestion(url: str) -> tuple[str, str]:
    """Derive a best-effort unverified label suggestion from the URL slug and hostname."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").replace("www.", "")
    brand_raw = host.split(".")[0].replace("-", " ").replace("_", " ").strip() if host else ""
    brand = brand_raw.title() if brand_raw else ""

    ignored = ("products", "product", "p", "item", "shop", "en", "ar", "ur", "hi", "collections")
    path_segments = [
        seg for seg in unquote(parsed.path).split("/") if seg and seg.lower() not in ignored
    ]
    if path_segments:
        last_seg = re.sub(r"\.(html?|php|aspx|jsp)$", "", path_segments[-1], flags=re.IGNORECASE)
        words = [w for w in re.split(r"[-_+]+", last_seg) if w and not w.isdigit()]
        if words:
            return " ".join(w.capitalize() for w in words)[:120], brand

    return "", brand


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

        images: list[str] = []
        image_val = product.get("image")
        raw_imgs = image_val if isinstance(image_val, list) else ([image_val] if image_val else [])
        for img_item in raw_imgs:
            if isinstance(img_item, dict):
                candidate = img_item.get("url") or img_item.get("contentUrl")
            else:
                candidate = img_item
            if isinstance(candidate, str) and candidate.strip():
                images.append(candidate.strip())
        if images:
            result["image"] = images[0]
            result["images"] = images[:5]

        offers = product.get("offers")
        offer = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offer, dict):
            if offer.get("priceCurrency"):
                result["currency"] = str(offer["priceCurrency"]).strip().upper()
            if offer.get("price") is not None and str(offer["price"]).strip():
                result["price_amount"] = str(offer["price"]).strip()
        return result

    return {}


def parse_product_html(
    html: str,
    product_url: str,
    target_language: str = "ur",
) -> dict[str, Any]:
    """Parse real OpenGraph, JSON-LD Product schema, and HTML tags honestly without fabrication."""
    soup = BeautifulSoup(html, "html.parser")
    json_ld = _extract_json_ld_product(soup)
    slug_title, slug_brand = _humanize_slug_suggestion(product_url)

    verified_fields: list[str] = []
    missing_fields: list[str] = []

    og_title = soup.find("meta", property="og:title")
    h1_tag = soup.find("h1")
    title_tag = soup.find("title")
    extracted_title = (
        (og_title.get("content") if og_title else None)
        or json_ld.get("name")
        or (h1_tag.get_text(" ", strip=True) if h1_tag else None)
        or (title_tag.get_text(" ", strip=True) if title_tag else None)
    )
    if extracted_title and str(extracted_title).strip():
        title = str(extracted_title).strip()[:160]
        verified_fields.append("title")
    else:
        title = slug_title
        missing_fields.append("title")

    og_site = soup.find("meta", property="og:site_name")
    extracted_brand = (og_site.get("content") if og_site else None) or json_ld.get("brand")
    if extracted_brand and str(extracted_brand).strip():
        brand = str(extracted_brand).strip()[:80]
        verified_fields.append("brand")
    else:
        brand = slug_brand
        missing_fields.append("brand")

    og_price = soup.find("meta", property="product:price:amount")
    og_currency = soup.find("meta", property="product:price:currency")
    raw_currency = (
        (og_currency.get("content") if og_currency else None) or json_ld.get("currency") or ""
    )
    raw_amount = (
        (og_price.get("content") if og_price else None) or json_ld.get("price_amount") or ""
    )
    currency = str(raw_currency).strip().upper()
    amount_str = str(raw_amount).strip()
    if amount_str:
        price = f"{currency} {amount_str}".strip()
        verified_fields.append("price")
    else:
        price = ""
        missing_fields.append("price")

    # Gather image candidates cleanly
    image_candidates: list[str] = []
    og_image = soup.find("meta", property="og:image")
    for raw_candidate in [
        og_image.get("content") if og_image else None,
        *(json_ld.get("images") or [json_ld.get("image")]),
    ]:
        if isinstance(raw_candidate, str) and raw_candidate.strip():
            abs_url = urljoin(product_url, raw_candidate.strip())
            if abs_url.startswith(("http://", "https://")) and abs_url not in image_candidates:
                image_candidates.append(abs_url)

    for img_tag in soup.find_all("img"):
        src = img_tag.get("src") or img_tag.get("data-src")
        if isinstance(src, str) and src.strip() and not src.strip().startswith("data:"):
            abs_url = urljoin(product_url, src.strip())
            if abs_url.startswith(("http://", "https://")) and abs_url not in image_candidates:
                image_candidates.append(abs_url)
        if len(image_candidates) >= 6:
            break

    image_url = image_candidates[0] if image_candidates else ""
    if image_url:
        verified_fields.append("image_url")
    else:
        missing_fields.append("image_url")

    og_desc = soup.find("meta", property="og:description")
    meta_desc = soup.find("meta", attrs={"name": "description"})
    description = (
        (og_desc.get("content") if og_desc else None)
        or (meta_desc.get("content") if meta_desc else None)
        or json_ld.get("description")
        or ""
    )
    description = re.sub(r"\s+", " ", str(description)).strip()[:400]
    if description:
        verified_fields.append("description")

    bullets = [
        re.sub(r"\s+", " ", li.get_text(" ", strip=True))
        for li in soup.select("ul li")
        if 8 <= len(li.get_text(strip=True)) <= 140
    ][:5]
    if bullets:
        features = bullets
        verified_fields.append("features")
    elif description:
        sentences = [s.strip() for s in re.split(r"[.!?]+", description) if len(s.strip()) >= 8]
        features = sentences[:4]
        if features:
            verified_fields.append("features")
        else:
            missing_fields.append("features")
    else:
        features = []
        missing_fields.append("features")

    confidence = round(len(verified_fields) / 6.0, 2)
    requires_confirmation = bool(missing_fields) or ("title" not in verified_fields)

    return {
        "product_url": product_url,
        "title": title,
        "brand": brand,
        "category": "",
        "currency": currency,
        "price": price,
        "features": features,
        "description": description,
        "image_url": image_url,
        "image_candidates": image_candidates,
        "target_language": target_language,
        "scrape_status": "scraped" if not missing_fields else "partial",
        "verified_fields": verified_fields,
        "missing_fields": missing_fields,
        "verification_confidence": confidence,
        "requires_user_confirmation": requires_confirmation,
        "error": None,
    }


def _fetch_with_ssrf_redirects(
    url: str, *, headers: dict[str, str], allow_private_in_test: bool = False
) -> httpx.Response:
    """Perform an HTTP GET resolving redirects manually so every hop is SSRF-validated."""
    current_url = validate_public_http_url(url, allow_private_in_test=allow_private_in_test)
    max_hops = 5
    with httpx.Client(timeout=8.0, follow_redirects=False, headers=headers) as client:
        for _ in range(max_hops + 1):
            resp = client.get(current_url)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                next_url = urljoin(current_url, resp.headers["location"].strip())
                current_url = validate_public_http_url(
                    next_url,
                    allow_private_in_test=allow_private_in_test,
                )
                continue
            return resp
    raise ScraperError("Exceeded maximum redirect hops while fetching product URL.")


def scrape_product_url(
    product_url: str,
    target_language: str = "ur",
    fetch_live: bool = True,
    allow_private_in_test: bool = False,
) -> dict[str, Any]:
    """Fetch and parse live product HTML honestly; never fabricate unverified product data."""
    validate_public_http_url(product_url, allow_private_in_test=allow_private_in_test)
    slug_title, slug_brand = _humanize_slug_suggestion(product_url)
    lang = target_language if target_language in ("ur", "ar", "hi", "en") else "en"

    unreached = {
        "product_url": product_url,
        "title": slug_title,
        "brand": slug_brand,
        "category": "",
        "currency": "",
        "price": "",
        "features": [],
        "description": "",
        "image_url": "",
        "image_candidates": [],
        "target_language": lang,
        "scrape_status": "unreachable",
        "verified_fields": [],
        "missing_fields": ["title", "brand", "price", "image_url", "description", "features"],
        "verification_confidence": 0.0,
        "requires_user_confirmation": True,
        "error": None,
    }

    if not fetch_live:
        unreached["error"] = "Live fetch disabled; please confirm product details manually."
        return unreached

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        response = _fetch_with_ssrf_redirects(
            product_url,
            headers=headers,
            allow_private_in_test=allow_private_in_test,
        )
        body_lower = response.text.lower()
        if response.status_code == 200 and ("<html" in body_lower or "<meta" in body_lower):
            return parse_product_html(response.text, str(response.url), lang)
        unreached["error"] = (
            f"Target site returned HTTP {response.status_code} "
            "without readable HTML product metadata."
        )
    except UnsafeUrlError:
        raise
    except httpx.HTTPError as exc:
        unreached["error"] = f"Could not reach target product URL ({type(exc).__name__})."
    except ScraperError as exc:
        unreached["error"] = str(exc)

    return unreached


def validate_image_bytes(data: bytes) -> tuple[str, str]:
    """Validate uploaded/fetched image magic bytes (JPEG, PNG, WEBP) and size limit."""
    if not data:
        raise ScraperError("Image payload is empty.")
    if len(data) > int(settings.MAX_ASSET_UPLOAD_BYTES):
        raise ScraperError(
            f"Image exceeds maximum allowed size of {settings.MAX_ASSET_UPLOAD_BYTES} bytes."
        )
    for magic, (mime, ext) in _ALLOWED_IMAGE_MAGIC.items():
        if data.startswith(magic):
            return mime, ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise ScraperError("Unsupported or invalid image binary (allowed: JPEG, PNG, WEBP).")


def download_and_validate_product_image(
    image_url: str,
    *,
    allow_private_in_test: bool = False,
) -> tuple[bytes, str, str]:
    """SSRF-safely download and magic-byte-validate a remote product image."""
    headers = {"Accept": "image/jpeg,image/png,image/webp,*/*;q=0.5"}
    resp = _fetch_with_ssrf_redirects(
        image_url,
        headers=headers,
        allow_private_in_test=allow_private_in_test,
    )
    if resp.status_code != 200:
        raise ScraperError(f"Failed to download product image (HTTP {resp.status_code}).")
    data = resp.content
    mime, ext = validate_image_bytes(data)
    return data, mime, ext
