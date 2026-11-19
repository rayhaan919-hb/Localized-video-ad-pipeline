"""Security middleware, distributed rate limiting, structured logging, and ops metrics."""

from __future__ import annotations

import hmac
import importlib.util
import json
import logging
import math
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import is_redis_reachable, settings

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
            if key_lower != "fencing_token" and any(
                part in key_lower for part in _SENSITIVE_KEY_PARTS
            ):
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


@dataclass
class RateLimitDecision:
    """Outcome from evaluating a rate-limit window."""

    allowed: bool
    retry_after: int
    remaining: int
    limit: int


class SharedRateLimitStore:
    """Thread-safe shared sliding-window backend matching Redis ZSET semantics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._zsets: dict[str, list[tuple[float, str]]] = defaultdict(list)

    def check_sliding_window(
        self,
        full_key: str,
        *,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> RateLimitDecision:
        if limit <= 0:
            return RateLimitDecision(allowed=True, retry_after=0, remaining=limit, limit=limit)
        ts = now if now is not None else time.time()
        cutoff = ts - float(window_seconds)
        with self._lock:
            entries = [pair for pair in self._zsets.get(full_key, []) if pair[0] > cutoff]
            if not entries:
                self._zsets.pop(full_key, None)
            if len(entries) >= limit:
                oldest_ts = entries[0][0]
                retry_after = max(1, int(window_seconds - (ts - oldest_ts)) + 1)
                self._zsets[full_key] = entries
                return RateLimitDecision(
                    allowed=False,
                    retry_after=retry_after,
                    remaining=0,
                    limit=limit,
                )
            entries.append((ts, uuid.uuid4().hex))
            self._zsets[full_key] = entries
            return RateLimitDecision(
                allowed=True,
                retry_after=0,
                remaining=max(0, limit - len(entries)),
                limit=limit,
            )

    def reset(self, prefix: str | None = None) -> None:
        with self._lock:
            if prefix is None:
                self._zsets.clear()
            else:
                for k in [k for k in self._zsets if k.startswith(prefix)]:
                    del self._zsets[k]


_REDIS_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_after = math.ceil((tonumber(oldest[2]) + window_ms - now_ms) / 1000)
  if retry_after < 1 then retry_after = 1 end
  return {0, retry_after, 0}
end
redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms + 1000)
return {1, 0, limit - count - 1}
"""


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

    def check_with_metadata(
        self,
        bucket: str,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitDecision:
        if limit <= 0:
            return RateLimitDecision(allowed=True, retry_after=0, remaining=limit, limit=limit)
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
                return RateLimitDecision(
                    allowed=False,
                    retry_after=retry_after,
                    remaining=0,
                    limit=limit,
                )
            queue.append(now)
            return RateLimitDecision(
                allowed=True,
                retry_after=0,
                remaining=max(0, limit - len(queue)),
                limit=limit,
            )

    def check(
        self,
        bucket: str,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        """Record a hit and return (allowed, retry_after_seconds)."""
        decision = self.check_with_metadata(bucket, key, limit, window_seconds)
        return decision.allowed, decision.retry_after

    def reset(self, bucket: str | None = None) -> None:
        """Clear rate-limiter buckets (primarily for test isolation)."""
        with self._lock:
            if bucket is None:
                self._events.clear()
            else:
                for k in [k for k in self._events if k[0] == bucket]:
                    del self._events[k]


class DistributedRateLimiter:
    """Redis-backed sliding-window rate limiter with atomic Lua & burst protection."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        shared_store: SharedRateLimitStore | None = None,
        max_keys: int = 10_000,
    ) -> None:
        self._explicit_redis_url = redis_url
        self._shared_store = shared_store
        self._local = SlidingWindowRateLimiter(max_keys=max_keys)
        self._redis_client: Any | None = None
        self._redis_script: Any | None = None
        self._redis_lock = threading.Lock()

    @property
    def backend_mode(self) -> str:
        if self._shared_store is not None:
            return "shared_store"
        if self._get_redis_script() is not None:
            return "redis"
        return "local_memory_fallback"

    def _get_redis_script(self):
        target_url = (
            self._explicit_redis_url
            if self._explicit_redis_url is not None
            else settings.effective_redis_url
        )
        if not target_url or not target_url.startswith(("redis://", "rediss://")):
            return None
        if importlib.util.find_spec("redis") is None:
            return None
        if not is_redis_reachable(target_url, timeout=0.15):
            return None
        with self._redis_lock:
            if self._redis_client is None:
                import redis  # type: ignore[import-not-found]

                self._redis_client = redis.Redis.from_url(
                    target_url, socket_connect_timeout=0.5, socket_timeout=0.5
                )
                self._redis_script = self._redis_client.register_script(_REDIS_SLIDING_WINDOW_LUA)
            return self._redis_script

    def _check_single_window(
        self,
        bucket: str,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        if limit <= 0:
            return RateLimitDecision(allowed=True, retry_after=0, remaining=limit, limit=limit)
        env_tag = settings.effective_app_env
        full_key = f"ratelimit:{env_tag}:{bucket}:{key}"

        if self._shared_store is not None:
            return self._shared_store.check_sliding_window(
                full_key, limit=limit, window_seconds=window_seconds
            )

        script = self._get_redis_script()
        if script is not None:
            try:
                now_ms = int(time.time() * 1000)
                window_ms = max(1000, int(window_seconds) * 1000)
                member = f"{now_ms}:{uuid.uuid4().hex}"
                res = script(keys=[full_key], args=[now_ms, window_ms, limit, member])
                allowed_int, retry_after, remaining = int(res[0]), int(res[1]), int(res[2])
                return RateLimitDecision(
                    allowed=bool(allowed_int),
                    retry_after=max(0, retry_after),
                    remaining=max(0, remaining),
                    limit=limit,
                )
            except Exception as exc:
                if settings.is_production and settings.effective_require_redis_broker:
                    log_audit_event(
                        "rate_limiter_redis_error",
                        level="ERROR",
                        details={"bucket": bucket, "error": type(exc).__name__},
                    )
                    raise RuntimeError("Distributed Redis rate limiter is unavailable.") from exc

        if settings.is_production and settings.effective_require_redis_broker:
            raise RuntimeError("Distributed Redis rate limiter is required in production.")
        return self._local.check_with_metadata(bucket, key, limit, window_seconds)

    def check_with_metadata(
        self,
        bucket: str,
        key: str,
        limit: int,
        window_seconds: int = 60,
        *,
        burst_limit: int | None = None,
        burst_window_seconds: int | None = None,
    ) -> RateLimitDecision:
        """Evaluate optional short burst window and sustained sliding window."""
        if burst_limit and burst_limit > 0 and burst_window_seconds and burst_window_seconds > 0:
            burst_res = self._check_single_window(
                f"{bucket}:burst",
                key,
                limit=burst_limit,
                window_seconds=burst_window_seconds,
            )
            if not burst_res.allowed:
                return burst_res

        return self._check_single_window(bucket, key, limit=limit, window_seconds=window_seconds)

    def check(
        self,
        bucket: str,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        """Backward-compatible helper returning (allowed, retry_after_seconds)."""
        decision = self.check_with_metadata(bucket, key, limit, window_seconds)
        return decision.allowed, decision.retry_after

    def reset(self, bucket: str | None = None) -> None:
        self._local.reset(bucket)
        if self._shared_store is not None:
            env_tag = settings.effective_app_env
            prefix = f"ratelimit:{env_tag}:{bucket}:" if bucket else None
            self._shared_store.reset(prefix)


class MetricsRegistry:
    """Thread-safe in-process observability counters and bounded latency histograms."""

    def __init__(self, max_samples: int = 1000) -> None:
        self._lock = threading.Lock()
        self._max_samples = max(50, int(max_samples))
        self._counters: dict[str, int] = defaultdict(int)
        self._timings_ms: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._max_samples)
        )

    def incr(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += int(value)

    def observe_ms(self, metric: str, duration_ms: float) -> None:
        with self._lock:
            self._timings_ms[metric].append(max(0.0, float(duration_ms)))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            timings: dict[str, dict[str, float]] = {}
            for name, samples in self._timings_ms.items():
                if not samples:
                    continue
                ordered = sorted(samples)
                n = len(ordered)
                p50 = ordered[int(0.50 * (n - 1))]
                p95 = ordered[min(n - 1, math.ceil(0.95 * n) - 1)]
                p99 = ordered[min(n - 1, math.ceil(0.99 * n) - 1)]
                timings[name] = {
                    "count": n,
                    "avg_ms": round(sum(ordered) / n, 2),
                    "p50_ms": round(p50, 2),
                    "p95_ms": round(p95, 2),
                    "p99_ms": round(p99, 2),
                    "max_ms": round(ordered[-1], 2),
                }
            return {
                "counters": dict(sorted(self._counters.items())),
                "timings": timings,
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._timings_ms.clear()


rate_limiter = DistributedRateLimiter()
metrics_registry = MetricsRegistry()


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
        metrics_registry.incr(f"http.status.{response.status_code}")
        metrics_registry.observe_ms("http.request", duration_ms)

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
