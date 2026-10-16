"""Request limits: a body-size guard and a per-client rate limiter.

Both are pure ASGI middleware that answer the standard error envelope themselves, so they sit in front of the app and
refuse a request before the application (and the multipart parser) has read it.

The counters live in this process (RATE_LIMIT_BACKEND=memory: demo mode and a single instance) or in Firestore
(RATE_LIMIT_BACKEND=firestore: shared by every instance, so a user's limit does not multiply with the number of instances).
Behind the UI's server-side proxy every request has the proxy as its socket peer: CLIENT_IP_HEADER is how the proxy
passes on who the user is, so that the limits are per user and not one bucket shared by everybody.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import math
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import structlog
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.gateway.middleware import envelope
from app.repo import firestore, leases

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

_WRITE_PATHS = re.compile(
    r"^/api/v1/(bundles/?|bundles/[^/]+/documents/?|bundles/[^/]+/corrections/?|bundles/[^/]+/corrections/[^/]+/revert/?|bundles/[^/]+/audit/sign/?|demo/case-[cd]/?)$"
)
_RUN_PATHS = re.compile(r"^/api/v1/bundles/[^/]+/(analyze|reassess|recompute)/?$")
_DELETE_PATHS = re.compile(r"^/api/v1/bundles/[^/]+/documents/[^/]+/?$")


def classify_request(method: str, path: str) -> str | None:
    """"writes" (create a bundle, upload or delete a document, a correction or its undo, a demo bundle), "runs" (analyze / reassess /
    recompute), or None (unlimited)."""
    if method == "DELETE":
        return "writes" if _DELETE_PATHS.match(path) else None
    if method != "POST":
        return None
    if _RUN_PATHS.match(path):
        return "runs"
    if _WRITE_PATHS.match(path):
        return "writes"
    return None


def client_key(scope: Scope) -> str:
    """The address a request is counted under: the end user's IP from CLIENT_IP_HEADER (a trusted caller sets it), or
    (TRUST_FORWARDED_FOR) the first valid IP in X-Forwarded-For, or the socket peer. A header with no valid IP falls
    through to the next source: a missing or garbled header can never exempt a request from the limit."""
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    if settings.client_ip_header:
        value = (Headers(scope=scope).get(settings.client_ip_header) or "").strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            pass
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


class SharedRateLimiter:
    """The same fixed-window counters, kept in Firestore so that every API instance counts the same requests.

    One document per (class, client, minute) in ``ratelimits``; the client is stored as a hash (no IP addresses at rest) and
    each document carries ``expires_at`` for a Firestore TTL policy (infra/firestore/setup_ttl.sh), so the collection cleans
    itself. A count is a transaction (read, +1, write); concurrent requests of one client contend and are retried by the
    library, which is fine at tens of requests a minute.
    """

    WINDOW_SECONDS = 60
    COLLECTION = "ratelimits"
    KEEP_FOR = timedelta(hours=2)
    MAX_ATTEMPTS = 25  # a burst from one client contends on one document: more retries than the library's 5

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    @staticmethod
    def _document_id(klass: str, client: str, window: int) -> str:
        return f"{klass}-{hashlib.sha256(client.encode('utf-8')).hexdigest()[:24]}-{window}"

    async def hit(self, klass: str, client: str, limit: int) -> int | None:
        """Count one request. None if it may proceed, else the whole seconds (>= 1) until the window ends.
        Raises when Firestore cannot be reached or answers an error: the caller decides what that means."""
        if limit <= 0:
            return None
        store = firestore._get_firestore_client()
        if store is None:
            raise RuntimeError("no Firestore client")
        now = self._clock()
        window = int(now // self.WINDOW_SECONDS)
        ref = store.collection(self.COLLECTION).document(self._document_id(klass, client, window))
        expires = datetime.fromtimestamp((window + 1) * self.WINDOW_SECONDS, timezone.utc) + self.KEEP_FOR

        async def count(transaction: object) -> int:
            snapshot = await ref.get(transaction=transaction)
            hits = int((snapshot.to_dict() or {}).get("count", 0)) + 1 if snapshot.exists else 1
            transaction.set(ref, {"class": klass, "window": window, "count": hits, "expires_at": expires})  # type: ignore[attr-defined]
            return hits

        hits = await leases.transact(store, count, max_attempts=self.MAX_ATTEMPTS)
        if hits > limit:
            return max(1, math.ceil((window + 1) * self.WINDOW_SECONDS - now))
        return None


shared_rate_limiter = SharedRateLimiter()

# A slow Firestore must not stall every write: past this, the request is counted in this process instead
_SHARED_TIMEOUT_SECONDS = 2.0


async def count_request(klass: str, client: str, limit: int) -> int | None:
    """Count one request with the configured backend: None to proceed, else the seconds to wait.

    With ``RATE_LIMIT_BACKEND=firestore`` the count is shared by all instances. If Firestore is unreachable or slow the request
    is counted by this process's own limiter instead (a degraded but still bounded limit): protection never disappears, and
    an outage of the counter never becomes an outage of the product.
    """
    if settings.rate_limit_backend == "firestore" and firestore._get_firestore_client() is not None:
        try:
            return await asyncio.wait_for(shared_rate_limiter.hit(klass, client, limit), _SHARED_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - includes the timeout
            logger.warning("shared_rate_limit_unavailable", limit_class=klass, error_type=type(exc).__name__)
    return rate_limiter.hit(klass, client, limit)


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
                retry_after = await count_request(klass, client, limit)
                if retry_after is not None:
                    logger.warning("rate_limited", limit_class=klass, client=client, retry_after_seconds=retry_after)
                    response = envelope(
                        scope, 429, "RATE_LIMITED", f"Too many requests. Try again in {retry_after} seconds.",
                        {"retry_after_seconds": retry_after}, {"Retry-After": str(retry_after)},
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
