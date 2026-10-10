"""Gateway middleware: request id + log context, security headers, and the error envelope.

All three are pure ASGI middleware (no ``BaseHTTPMiddleware``): a streaming response, such as the SSE stream, passes
through them without being wrapped or buffered.

Error envelope (every error answers it, whoever raised it):
    {
        "code": "DOMAIN_ERROR_CODE",
        "message": "Human-readable description",
        "detail": {...},          # optional structured detail
        "request_id": "..."       # the same id as the X-Request-ID response header
    }
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.gateway.errors import CargoClearError

logger = structlog.get_logger(__name__)

# A client-supplied X-Request-ID is only kept if it looks like this; anything else is replaced.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")

_HTTP_ERRORS = {
    404: ("NOT_FOUND", "Resource not found."),
    405: ("METHOD_NOT_ALLOWED", "Method not allowed."),
}
_GENERIC_HTTP_MESSAGE = "The request could not be processed."


def request_id_of(scope: Scope) -> str:
    """The id RequestContextMiddleware gave this request ("unknown" only if that middleware is not in front)."""
    return (scope.get("state") or {}).get("request_id") or "unknown"


def envelope(
    scope: Scope,
    status_code: int,
    code: str,
    message: str,
    detail: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """The standard error response. ``headers`` are extra response headers (Retry-After, Allow, ...)."""
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "detail": detail, "request_id": request_id_of(scope)},
        headers=headers,
    )


class RequestContextMiddleware:
    """Gives every request one id (X-Request-ID) and binds it, with the method and path, into the log context."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = Headers(scope=scope).get("x-request-id")
        request_id = inbound if inbound is not None and REQUEST_ID_PATTERN.fullmatch(inbound) else str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.perf_counter()

        # Bind context for all log statements in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, method=scope["method"], path=scope["path"])

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
                elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
                logger.info("request_completed", status=message["status"], elapsed_ms=elapsed_ms)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware:
    """X-Content-Type-Options and Referrer-Policy on every response; Cache-Control: no-store on JSON that sets none.

    SSE, PDFs and HTML keep whatever caching headers they have (or none).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                if "cache-control" not in headers and headers.get("content-type", "").lower().startswith("application/json"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


class ErrorEnvelopeMiddleware:
    """Converts CargoClearError and unhandled exceptions to the error envelope.

    Pure ASGI, so the SSE stream passes through untouched. Once a response has started it cannot be replaced by an
    envelope: such an exception propagates (the stream generator handles its own errors).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except CargoClearError as exc:
            if started:
                raise
            logger.warning("domain_error", code=exc.code, message=exc.message)
            response = envelope(scope, exc.http_status, exc.code, exc.message, exc.detail, exc.headers)
            await response(scope, receive, send)
        except Exception as exc:
            if started:
                raise
            logger.exception("unhandled_exception", exc_info=exc)
            response = envelope(scope, 500, "INTERNAL_ERROR", "An unexpected error occurred. Please retry.")
            await response(scope, receive, send)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 in the envelope. Only where / what / which kind is reported, never the offending input."""
    errors = [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
    return envelope(request.scope, 422, "VALIDATION_ERROR", "The request is not valid.", {"errors": errors})


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """404 / 405 / any other Starlette HTTPException in the envelope, with a fixed message (never ``exc.detail``)."""
    code, message = _HTTP_ERRORS.get(exc.status_code, (f"HTTP_{exc.status_code}", _GENERIC_HTTP_MESSAGE))
    headers = dict(exc.headers) if exc.headers else None
    return envelope(request.scope, exc.status_code, code, message, None, headers)
