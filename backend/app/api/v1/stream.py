"""SSE stream router — GET /bundles/{bundle_id}/stream.

Implements the Server-Sent Events endpoint that pushes real-time pipeline
progress and iteration results to the frontend.

Implementation notes (v4.0 §2.5):
  - Uses ``sse-starlette`` EventSourceResponse (not StreamingResponse).
  - Cloud Run timeout MUST be set to 300s (via --timeout flag).
  - Cloud Run MUST have --no-cpu-throttling (SSE generators stall otherwise).
  - ping=15 keeps the connection alive through proxies.
  - This router MUST NOT go through ErrorEnvelopeMiddleware — streaming
    responses cannot be re-wrapped after the generator starts.
    Errors inside the generator are emitted as SSE error events.
"""

import asyncio
import json

from fastapi import APIRouter, Path
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["stream"])

_POLL_INTERVAL_S = 2
_MAX_IDLE_POLLS = 150  # 300 s / 2 s — hard timeout guard inside the generator


@router.get(
    "/bundles/{bundle_id}/stream",
    summary="SSE stream for pipeline status and iteration events",
    response_class=EventSourceResponse,
)
async def stream(bundle_id: str = Path(...)) -> EventSourceResponse:
    """Subscribe to real-time pipeline updates for a bundle.

    Events emitted:
      - ``status``    → StatusEvent  (on every stage transition)
      - ``iteration`` → IterationEvent (when a new iteration is written)
      - ``error``     → ErrorEvent   (on pipeline failure)

    The stream terminates when the pipeline reaches state COMPLETE or ERROR.

    Phase 1: Reads run state from Firestore.
    Skeleton: Emits a single synthetic COMPLETE event immediately.
    """

    async def generator():
        # TODO(Phase 1): replace with Firestore polling
        # Skeleton: emit a single synthetic "COMPLETE" status and close.
        idle_count = 0
        last_iter = -1

        try:
            # Emit an initial QUEUED status so the frontend knows it connected
            yield {
                "event": "status",
                "data": json.dumps({
                    "kind": "status",
                    "bundle_id": bundle_id,
                    "run_id": "skeleton-run",
                    "state": "COMPLETE",
                    "stage": None,
                    "progress": 1.0,
                    "message": "Skeleton mode: no real pipeline running.",
                }),
            }
            # Stream terminates after COMPLETE
        except asyncio.CancelledError:
            # Client disconnected — clean up gracefully
            pass
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({
                    "kind": "error",
                    "bundle_id": bundle_id,
                    "run_id": "skeleton-run",
                    "code": "STREAM_ERROR",
                    "message": str(exc),
                }),
            }

    return EventSourceResponse(generator(), ping=15)
