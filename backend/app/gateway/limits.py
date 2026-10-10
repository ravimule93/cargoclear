"""Request limits: a body-size guard and a per-client rate limiter.

Both are pure ASGI middleware that answer the standard error envelope themselves, so they sit in front of the app and
refuse a request before the application (and the multipart parser) has read it.

The API runs as ONE instance (Cloud Run max-instances=1), so the rate limiter keeps its counters in this process.
"""

from __future__ import annotations

import ipaddress
import math
import re
import time
from collections.abc import Callable

import structlog
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.gateway.middleware import envelope

logger = structlog.get_logger(__name__)

_UPLOAD_PATH = re.compile(r"^/api/v1/bundles/[^/]+/documents/?$")
_MULTIPART_OVERHEAD_BYTES = 1024 * 1024
_LIMITED_METHODS = frozenset({"POST", "PUT"})


class _BodyTooLarge(Exception):
    """Raised into the application when the streamed body crossed the limit (the 413 has already been sent)."""


def body_limit_for(scope: Scope) -> tuple[int, str]:
    """(limit in bytes, 413 message) for this request: the upload limit for POST .../documents, else the JSON limit."""
    if scope["method"] == "POST" and _UPLOAD_PATH.match(scope["path"]):
        limit = settings.max_upload_bytes + _MULTIPART_OVERHEAD_BYTES
        return limit, f"The file is larger than {settings.max_upload_mb:g} MB."
    return int(settings.max_json_body_kb * 1024), f"The request body is larger than {settings.max_json_body_kb:g} KB."


def _declared_length(scope: Scope) -> int | None:
    value = Headers(scope=scope).get("content-length")
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError:
        return None
    return length if length >= 0 else None


class BodySizeLimitMiddleware:
    """413 PAYLOAD_TOO_LARGE for a POST/PUT body over the limit.

    With a Content-Length the request is refused before its body is read. Without one the bytes are counted while they
    stream, and the response is sent as soon as the limit is crossed (the application then sees a failed read and
    anything it answers afterwards is dropped).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _LIMITED_METHODS:
            await self.app(scope, receive, send)
            return

        limit, message = body_limit_for(scope)
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await self._refuse(scope, receive, send, limit, message, declared)
            return

        refused = False
        counted = 0

        async def counting_receive() -> Message:
            nonlocal refused, counted
            event = await receive()
            if event["type"] == "http.request":
                counted += len(event.get("body", b""))
                if counted > limit and not refused:
                    refused = True
                    await self._refuse(scope, receive, send, limit, message, counted)
                    raise _BodyTooLarge
            return event

        async def guarded_send(event: Message) -> None:
            if not refused:  # after the 413 the application's own (error) response is dropped
                await send(event)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            pass

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, limit: int, message: str, seen: int) -> None:
        logger.warning("payload_too_large", limit_bytes=limit, bytes_seen=seen, path=scope["path"])
        response = envelope(scope, 413, "PAYLOAD_TOO_LARGE", message, {"max_bytes": limit})
        await response(scope, receive, send)


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------

_WRITE_PATHS = re.compile(r"^/api/v1/(bundles/?|bundles/[^/]+/documents/?|demo/case-c/?)$")
_RUN_PATHS = re.compile(r"^/api/v1/bundles/[^/]+/(analyze|reassess)/?$")


def classify_request(method: str, path: str) -> str | None:
    """"writes" (create a bundle, upload a document, the demo bundle), "runs" (analyze / reassess), or None (unlimited)."""
    if method != "POST":
        return None
    if _RUN_PATHS.match(path):
        return "runs"
    if _WRITE_PATHS.match(path):
        return "writes"
    return None


def client_key(scope: Scope) -> str:
    """The address a request is counted under: the socket peer, or (TRUST_FORWARDED_FOR) the first valid IP in
    X-Forwarded-For. A header with no valid IP falls back to the peer."""
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    if settings.trust_forwarded_for:
        for candidate in (Headers(scope=scope).get("x-forwarded-for") or "").split(","):
            try:
                return str(ipaddress.ip_address(candidate.strip()))
            except ValueError:
                continue
    return peer


class RateLimiter:
    """Fixed-window counters per (class, client). The clock is injectable so that tests never sleep."""

    WINDOW_SECONDS = 60.0

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[tuple[str, str], list[float]] = {}  # (class, client) -> [window start, hits]
        self._next_sweep = 0.0

    def hit(self, klass: str, client: str, limit: int) -> int | None:
        """Count one request. None if it may proceed, else the whole seconds (>= 1) until the window ends."""
        if limit <= 0:  # 0 switches the class off
            return None
        now = self._clock()
        self._sweep(now)
        key = (klass, client)
        bucket = self._buckets.get(key)
        if bucket is None or now - bucket[0] >= self.WINDOW_SECONDS:
            bucket = self._buckets[key] = [now, 0]
        bucket[1] += 1
        if bucket[1] > limit:
            return max(1, math.ceil(bucket[0] + self.WINDOW_SECONDS - now))
        return None

    def _sweep(self, now: float) -> None:
        """Drop buckets whose window is over (at most once a window), so the table cannot grow without bound."""
        if now < self._next_sweep:
            return
        self._next_sweep = now + self.WINDOW_SECONDS
        for key in [k for k, (start, _) in self._buckets.items() if now - start >= self.WINDOW_SECONDS]:
            del self._buckets[key]

    def reset(self) -> None:
        self._buckets.clear()
        self._next_sweep = 0.0


# The limiter the middleware uses (looked up at request time, so that tests can swap in one with a fake clock)
rate_limiter = RateLimiter()


class RateLimitMiddleware:
    """429 RATE_LIMITED (with Retry-After) once a client exceeds RATE_LIMIT_WRITES_PER_MINUTE or
    RATE_LIMIT_RUNS_PER_MINUTE. GET routes and the SSE stream are never limited. A refused request is refused before its
    body is read."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            klass = classify_request(scope["method"], scope["path"])
            if klass is not None:
                limit = settings.rate_limit_writes_per_minute if klass == "writes" else settings.rate_limit_runs_per_minute
                client = client_key(scope)
                retry_after = rate_limiter.hit(klass, client, limit)
                if retry_after is not None:
                    logger.warning("rate_limited", limit_class=klass, client=client, retry_after_seconds=retry_after)
                    response = envelope(
                        scope, 429, "RATE_LIMITED", f"Too many requests. Try again in {retry_after} seconds.",
                        {"retry_after_seconds": retry_after}, {"Retry-After": str(retry_after)},
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
