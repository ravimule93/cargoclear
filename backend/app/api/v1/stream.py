"""SSE stream router — GET /bundles/{bundle_id}/stream.

Real-time Server-Sent Events push notification pipeline:
  - status: Emitted on every pipeline stage transition (stage, progress, state).
  - iteration: Emitted as soon as a new AssessmentIteration is finalized.
  - error: Emitted on unrecoverable failure.

Configured with ping=15 keep-alive and handles client disconnects gracefully.
"""

import asyncio
import json

from fastapi import APIRouter, Path
from sse_starlette.sse import EventSourceResponse

from app.repo import firestore

router = APIRouter(tags=["stream"])

_POLL_INTERVAL_S = 1.0


@router.get(
    "/bundles/{bundle_id}/stream",
    summary="SSE stream for pipeline status and iteration events",
    response_class=EventSourceResponse,
)
async def stream(bundle_id: str = Path(..., description="Target bundle ID")) -> EventSourceResponse:
    """Subscribe to real-time pipeline status and assessment iteration events."""

    async def event_generator():
        last_iter_num = -1
        last_stage = None
        consecutive_complete_polls = 0

        try:
            while True:
                # 1. Fetch current run progress
                run_state = await firestore.get_run_state(bundle_id)
                current_stage = run_state.get("stage")
                state = run_state.get("state", "RUNNING")

                # Emit status event if stage changed or state is terminal
                if current_stage != last_stage or state in ("COMPLETE", "ERROR"):
                    last_stage = current_stage
                    yield {
                        "event": "status",
                        "data": json.dumps(run_state),
                    }

                # 2. Check for new AssessmentIteration
                latest = await firestore.latest_iteration(bundle_id)
                if latest is not None and latest.get("iteration") != last_iter_num:
                    last_iter_num = latest["iteration"]
                    yield {
                        "event": "iteration",
                        "data": json.dumps(latest),
                    }

                # Terminate stream after COMPLETE or ERROR has been emitted
                if state in ("COMPLETE", "ERROR"):
                    consecutive_complete_polls += 1
                    if consecutive_complete_polls >= 2:
                        break

                await asyncio.sleep(_POLL_INTERVAL_S)

        except asyncio.CancelledError:
            # Client disconnected
            pass
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({
                    "kind": "error",
                    "bundle_id": bundle_id,
                    "code": "STREAM_EXCEPTION",
                    "message": str(exc),
                }),
            }

    return EventSourceResponse(event_generator(), ping=15)
