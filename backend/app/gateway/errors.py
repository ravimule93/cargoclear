"""Domain error hierarchy for CargoClear.

All application-level errors should inherit from CargoClearError.
The ErrorEnvelopeMiddleware converts them to the standard JSON envelope.
"""

import asyncio
from typing import Any


class CargoClearError(Exception):
    """Base application error.

    Attributes:
        code:        Machine-readable error code (SCREAMING_SNAKE_CASE).
        message:     Human-readable summary.
        http_status: HTTP status code to use in the response.
        detail:      Optional structured detail dict.
        headers:     Optional extra response headers (e.g. Retry-After).
    """

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.headers = headers  # extra response headers, e.g. Retry-After


class NotFoundError(CargoClearError):
    code = "NOT_FOUND"
    http_status = 404


class ValidationError(CargoClearError):
    code = "VALIDATION_ERROR"
    http_status = 422


class ConflictError(CargoClearError):
    code = "CONFLICT"
    http_status = 409


class PayloadTooLargeError(CargoClearError):
    """A request body or an uploaded file is larger than the configured limit."""

    code = "PAYLOAD_TOO_LARGE"
    http_status = 413


class RateLimitedError(CargoClearError):
    """A client sent too many requests of one class (see gateway/limits.py). Carries Retry-After."""

    code = "RATE_LIMITED"
    http_status = 429


class ServiceBusyError(CargoClearError):
    """MAX_CONCURRENT_RUNS analyses are already running. Carries Retry-After."""

    code = "SERVICE_BUSY"
    http_status = 429


class UpstreamError(CargoClearError):
    """Raised when a GCP service (GCS, Firestore, BigQuery, Vertex AI) fails."""

    code = "UPSTREAM_ERROR"
    http_status = 502


class ExtractionError(CargoClearError):
    """Raised when Gemini fails to produce a valid extraction schema after retries."""

    code = "EXTRACTION_FAILED"
    http_status = 422


class PipelineError(CargoClearError):
    """Raised when the assessment pipeline encounters an unrecoverable error."""

    code = "PIPELINE_ERROR"
    http_status = 500


class RunInterruptedError(CargoClearError):
    """A run still marked RUNNING whose heartbeat stopped: the process that was executing it is gone."""

    code = "RUN_INTERRUPTED"
    http_status = 500


class RunTimeoutError(CargoClearError):
    """The run exceeded RUN_TIMEOUT_SECONDS. Raised only when the deadline itself expired, never for a stray TimeoutError."""

    code = "RUN_TIMEOUT"
    http_status = 500


# What a client (run state, SSE) and the immutable audit log are told when a run ends badly. Raw exception text can
# contain file paths, bucket names or document content, so only these fixed texts and the messages of our own
# domain errors (which are written to be shown) ever leave the process.
CANCELLED_MESSAGE = "cancelled: the server is shutting down"
TIMEOUT_MESSAGE = "the analysis exceeded the time limit"
INTERRUPTED_MESSAGE = "The analysis was interrupted (no heartbeat)"


def public_error(exc: BaseException, run_id: str) -> dict[str, str]:
    """``{"code", "message"}`` that is safe to show to a client and to store in the audit log.

    - a CargoClearError: its own code and message (they are written for the user). The run deadline arrives as a
      ``RunTimeoutError``: the orchestrator raises it only when the deadline itself expired;
    - cancellation: a fixed text;
    - anything else (a stray ``TimeoutError`` from a socket or client included): ``INTERNAL_ERROR`` with a reference
      the operator can find in the logs. The raw text goes to ``logger.exception`` only.
    """
    if isinstance(exc, CargoClearError):
        return {"code": exc.code, "message": exc.message}
    if isinstance(exc, asyncio.CancelledError):
        return {"code": "RUN_CANCELLED", "message": CANCELLED_MESSAGE}
    return {"code": "INTERNAL_ERROR", "message": f"The analysis failed unexpectedly (reference: {run_id})."}

