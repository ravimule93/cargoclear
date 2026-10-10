"""SSE event contracts.

These Pydantic models define the exact shape of Server-Sent Events
emitted by ``GET /api/v1/bundles/{id}/stream``.

Frontend ``lib/sse.ts`` and ``lib/types.ts`` are generated from the
OpenAPI schema, so these types are the authoritative source.
"""

from typing import Literal

from pydantic import BaseModel, Field


class StatusEvent(BaseModel):
    """Emitted at each stage transition of the assessment pipeline.

    Frontend uses this to drive the progress strip and live region announcements.
    """

    kind: Literal["status"] = "status"
    bundle_id: str
    run_id: str
    state: Literal["QUEUED", "RUNNING", "COMPLETE", "ERROR"]
    stage: str | None = None
    progress: float = Field(ge=0.0, le=1.0, default=0.0, description="Pipeline progress 0.0–1.0")
    message: str | None = None


class IterationEvent(BaseModel):
    """Emitted when a new AssessmentIteration is written to Firestore.

    Frontend uses this to update the assessment panel without a full page reload.
    confidence and reasoning_delta are optional because early iterations may
    not yet have these computed.
    """

    kind: Literal["iteration"] = "iteration"
    bundle_id: str
    iteration: int
    status: str  # One of the 4 Status values
    confidence: dict | None = None
    checks: list[dict] = Field(default_factory=list)
    missing_evidence: list[dict] = Field(default_factory=list)
    reasoning_delta: dict | None = None


class ErrorEvent(BaseModel):
    """Emitted when the pipeline encounters an unrecoverable error."""

    kind: Literal["error"] = "error"
    bundle_id: str
    run_id: str
    code: str
    message: str
