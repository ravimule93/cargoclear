"""Domain error hierarchy for CargoClear.

All application-level errors should inherit from CargoClearError.
The ErrorEnvelopeMiddleware converts them to the standard JSON envelope.
"""

from typing import Any


class CargoClearError(Exception):
    """Base application error.

    Attributes:
        code:        Machine-readable error code (SCREAMING_SNAKE_CASE).
        message:     Human-readable summary.
        http_status: HTTP status code to use in the response.
        detail:      Optional structured detail dict.
    """

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFoundError(CargoClearError):
    code = "NOT_FOUND"
    http_status = 404


class ValidationError(CargoClearError):
    code = "VALIDATION_ERROR"
    http_status = 422


class ConflictError(CargoClearError):
    code = "CONFLICT"
    http_status = 409


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
