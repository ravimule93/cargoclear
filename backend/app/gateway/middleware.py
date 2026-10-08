"""Gateway middleware: request context injection + error envelope."""

import time
import uuid
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.gateway.errors import CargoClearError

logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Injects X-Request-ID and structured logging context for every request."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start = time.perf_counter()

        # Bind context for all log statements in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

        response.headers["X-Request-ID"] = request_id
        logger.info("request_completed", status=response.status_code, elapsed_ms=elapsed_ms)
        return response


class ErrorEnvelopeMiddleware(BaseHTTPMiddleware):
    """Converts all unhandled exceptions and CargoClearError to a consistent JSON envelope.

    Envelope shape:
        {
            "code": "DOMAIN_ERROR_CODE",
            "message": "Human-readable description",
            "detail": {...},          # optional structured detail
            "request_id": "uuid"
        }

    NOTE: This middleware MUST NOT wrap the SSE stream endpoint — streaming responses
    cannot be re-wrapped once the generator has started. The stream router is still
    included but any errors emitted before the first yield are caught here correctly;
    errors inside the generator are emitted as SSE error events instead.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except CargoClearError as exc:
            request_id = request.headers.get("X-Request-ID", "unknown")
            logger.warning("domain_error", code=exc.code, message=exc.message)
            return JSONResponse(
                status_code=exc.http_status,
                content={
                    "code": exc.code,
                    "message": exc.message,
                    "detail": exc.detail,
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        except Exception as exc:
            request_id = request.headers.get("X-Request-ID", "unknown")
            logger.exception("unhandled_exception", exc_info=exc)
            return JSONResponse(
                status_code=500,
                content={
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please retry.",
                    "detail": None,
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
