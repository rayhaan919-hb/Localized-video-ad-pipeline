"""Security middleware, in-process rate limiting, and structured audit logging."""

from __future__ import annotations

import hmac
import json
import logging
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger("localized_video_ad_worker")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

_SAFE_REQ_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "signature",
    "credential",
    "cookie",
    "private_key",
)


def sanitize_log_data(value: Any) -> Any:
    """Recursively redact secrets, tokens, passwords, and signatures before logging."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for k, v in value.items():
            key_lower = str(k).lower()
            if any(part in key_lower for part in _SENSITIVE_KEY_PARTS):
                sanitized[str(k)] = "[REDACTED]"
            else:
                sanitized[str(k)] = sanitize_log_data(v)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_log_data(item) for item in value]
    if isinstance(value, str) and len(value) > 512:
        return value[:500] + "...[truncated]"
    return value


def log_audit_event(
    event: str,
    *,
    level: str = "INFO",
    request_id: str | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Emit a structured JSON audit log event with automatic secret redaction."""
    payload: dict[str, Any] = {
        "ts": round(time.time(), 3),
        "level": level.upper(),
        "event": event,
    }
    if request_id:
        payload["request_id"] = request_id
    if user_id:
        payload["user_id"] = str(user_id)
    if workspace_id:
        payload["workspace_id"] = str(workspace_id)
    if ip_address:
        payload["ip_address"] = ip_address
    if details:
        payload["details"] = sanitize_log_data(details)

    serialized = json.dumps(payload, default=str)
    if level.upper() == "ERROR":
        logger.error(serialized)
    elif level.upper() == "WARNING":
        logger.warning(serialized)
    else:
        logger.info(serialized)


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter with bounded key eviction."""

    def __init__(self, max_keys: int = 10_000) -> None:
        self._lock = threading.Lock()
        self._max_keys = max(1, int(max_keys))
        self._last_sweep = time.monotonic()
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def _sweep_stale_locked(self, now: float, cutoff: float) -> None:
        expired_keys: list[tuple[str, str]] = []
        for k, q in self._events.items():
            while q and q[0] <= cutoff:
                q.popleft()
            if not q:
                expired_keys.append(k)
        for k in expired_keys:
            del self._events[k]
        self._last_sweep = now

    def check(
        self,
        bucket: str,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        """Record a hit and return (allowed, retry_after_seconds)."""
        if limit <= 0:
            return True, 0
        now = time.monotonic()
        cutoff = now - float(window_seconds)
        composite = (bucket, key)
        with self._lock:
            if (
                len(self._events) > 512
                or (now - self._last_sweep) >= 60.0
                or len(self._events) >= self._max_keys
            ):
                self._sweep_stale_locked(now, cutoff)

            if composite not in self._events and len(self._events) >= self._max_keys:
                # Evict bucket with oldest leading timestamp to keep memory strictly bounded.
                oldest_key = min(
                    self._events.items(),
                    key=lambda item: item[1][0] if item[1] else float("-inf"),
                )[0]
                del self._events[oldest_key]

            queue = self._events[composite]
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if len(queue) >= limit:
                oldest = queue[0]
                retry_after = max(1, int(window_seconds - (now - oldest)) + 1)
                return False, retry_after
            queue.append(now)
            return True, 0

    def reset(self, bucket: str | None = None) -> None:
        """Clear rate-limiter buckets (primarily for test isolation)."""
        with self._lock:
            if bucket is None:
                self._events.clear()
            else:
                for k in [k for k in self._events if k[0] == bucket]:
                    del self._events[k]


rate_limiter = SlidingWindowRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract caller IP safely; only trust proxy X-Forwarded-For when explicitly enabled.

    When TRUST_PROXY_HEADERS=true behind a reverse proxy, we take the rightmost
    non-empty entry appended by the proxy so client-supplied left-side values
    cannot spoof rate limits. Otherwise we strictly use the peer TCP address.
    """
    if settings.effective_trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").strip()
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            if parts:
                return parts[-1]
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _is_exempt_from_worker_api_key(request: Request) -> bool:
    path = request.url.path
    if request.method == "OPTIONS" or path == "/health":
        return True
    if path == "/v1/billing/webhooks/stripe":
        return True
    if path.startswith("/v1/videos/") and path.endswith("/download"):
        if bool(request.query_params.get("token")):
            return True
    return False


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Enforce request limits, worker API key gate, X-Request-ID, and structured access logs."""

    async def dispatch(self, request: Request, call_next):
        raw_req_id = request.headers.get("x-request-id", "").strip()
        req_id = raw_req_id if _SAFE_REQ_ID_RE.match(raw_req_id) else str(uuid.uuid4())
        request.state.request_id = req_id

        max_bytes = max(1024, int(settings.MAX_REQUEST_BODY_BYTES))
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_len = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header.", "request_id": req_id},
                    headers={"X-Request-ID": req_id},
                )
            if declared_len > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"Request payload exceeds maximum limit of {max_bytes} bytes.",
                        "request_id": req_id,
                    },
                    headers={"X-Request-ID": req_id},
                )

        # Also read-check body length for chunked/missing Content-Length on mutating methods.
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"Request payload exceeds maximum limit of {max_bytes} bytes.",
                        "request_id": req_id,
                    },
                    headers={"X-Request-ID": req_id},
                )

        # Enforce internal BFF-to-Worker API key when configured or required in production.
        if request.url.path.startswith("/v1/") and not _is_exempt_from_worker_api_key(request):
            configured_key = settings.effective_worker_api_key
            if settings.is_production and not configured_key:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Worker internal key is not configured.",
                        "request_id": req_id,
                    },
                    headers={"X-Request-ID": req_id},
                )
            if configured_key:
                supplied = request.headers.get("x-worker-api-key", "").strip()
                if not supplied or not hmac.compare_digest(supplied, configured_key):
                    log_audit_event(
                        "worker_api_key_rejected",
                        level="WARNING",
                        request_id=req_id,
                        ip_address=get_client_ip(request),
                        details={"path": request.url.path},
                    )
                    return JSONResponse(
                        status_code=401,
                        content={
                            "detail": "Invalid or missing worker service API key.",
                            "request_id": req_id,
                        },
                        headers={"X-Request-ID": req_id},
                    )

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        response.headers["X-Request-ID"] = req_id

        if request.url.path != "/health":
            log_audit_event(
                "http_request",
                request_id=req_id,
                ip_address=get_client_ip(request),
                details={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        return response
