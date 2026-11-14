"""Security middleware, in-process rate limiting, and structured audit logging."""

from __future__ import annotations

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
    """Thread-safe in-memory sliding-window rate limiter keyed by bucket + subject."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

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
    """Extract caller IP cleanly from forwarded header or peer address."""
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Enforce request body size limits, attach X-Request-ID, and emit structured access logs."""

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
