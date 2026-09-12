"""Cross-cutting observability and abuse protection.

* Request-ID middleware: every request gets an X-Request-ID (honors an
  incoming one), attached to the logging context so every log line for a
  request is correlatable. Response carries it back for support workflows.
* Structured logging: JSON formatter in production (machine-parseable),
  readable console format otherwise. Logs NEVER contain raw audio or
  biometric embeddings — those never enter log calls anywhere.
* Rate limiting: sliding-window counter per API key (or client IP when auth
  is open). Redis-backed when available so limits hold across workers;
  in-process fallback otherwise.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app import config

_REQUEST_ID_HEADER = "X-Request-ID"

logger = logging.getLogger("satyavoice")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get(_REQUEST_ID_HEADER) or str(uuid.uuid4())
        # Expose to logging filters and route handlers.
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        response.headers[_REQUEST_ID_HEADER] = request_id
        logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(elapsed_ms, 1),
                "client": request.client.host if request.client else None,
            },
        )
        return response


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "call_id", "tenant_id", "model_version", "stage", "latency_ms", "duration_ms", "method", "path", "status", "client"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    root = logging.getLogger("satyavoice")
    root.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if config.LOG_JSON else logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
    ))
    root.handlers = [handler]
    root.propagate = False


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class _MemoryWindow:
    """Process-local sliding window (single-worker fallback)."""

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        now = time.time()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False, window_seconds
        hits.append(now)
        return True, 0


class RateLimiter:
    """Sliding-window limiter; Redis-backed when reachable, else in-process."""

    def __init__(self) -> None:
        self._memory = _MemoryWindow()
        self._redis = None
        if config.RATE_LIMIT_ENABLED and config.RATE_LIMIT_REDIS_URL:
            try:
                import redis

                client = redis.Redis.from_url(config.RATE_LIMIT_REDIS_URL, decode_responses=True)
                client.ping()
                self._redis = client
            except Exception:
                logger.warning("Redis unavailable for rate limiting; using in-process window (per-worker limits).")

    def check(self, identifier: str) -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        if not config.RATE_LIMIT_ENABLED:
            return True, 0

        limit = config.RATE_LIMIT_REQUESTS
        window = config.RATE_LIMIT_WINDOW_SECONDS

        if self._redis is not None:
            now = time.time()
            bucket = f"ratelimit:{identifier}"
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(bucket, 0, now - window)
            pipe.zcard(bucket)
            pipe.zadd(bucket, {str(now): now})
            pipe.expire(bucket, window)
            results = pipe.execute()
            count = int(results[1])
            if count >= limit:
                return False, window
            return True, 0

        return self._memory.check(identifier, limit, window)


rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in {"/health", "/health/live", "/health/ready"}:
            return await call_next(request)

        # Prefer the authenticated identity; fall back to client IP.
        auth = getattr(request.state, "auth_context", None)
        identifier = getattr(auth, "tenant_id", None) or (
            request.client.host if request.client else "unknown"
        )

        allowed, retry_after = rate_limiter.check(identifier)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Slow down and retry."},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
