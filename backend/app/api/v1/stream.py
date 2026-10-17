"""SSE stream router — GET /bundles/{bundle_id}/stream.

Real-time Server-Sent Events push notification pipeline:
  - status: Emitted on status state changes or stage transitions.
  - iteration: Emitted as soon as a new AssessmentIteration is finalized.
  - error: Emitted on unrecoverable failure of the stream itself (fixed message, never exception text).

An unknown bundle is a 404 with the standard error envelope BEFORE the stream opens.
Configured with ping=15 keep-alive and handles client disconnects gracefully.
Keeps stream open across multiple runs.

Polling is adaptive: STREAM_POLL_ACTIVE_SECONDS while the run is RUNNING/QUEUED, STREAM_POLL_IDLE_SECONDS otherwise.
Each cycle that finds a run RUNNING or QUEUED also asks the orchestrator to reap a run whose lease expired or whose heartbeat
stopped, so nobody watches an abandoned run forever.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Path
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.gateway.authorization import require_authorized_bundle
from app.gateway.errors import NotFoundError
from app.repo import firestore
from app.services import orchestrator, run_events

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["stream"], dependencies=[Depends(require_authorized_bundle)])

# Seam for the poll sleep: tests replace it to observe the chosen interval and to end the stream. In production the
# sleep is the fallback timer that races a wake-up from the orchestrator (see ``_pause``).
_sleep = asyncio.sleep

_ACTIVE_STATES = frozenset({"RUNNING", "QUEUED"})
STREAM_FAILED_MESSAGE = "The event stream failed unexpectedly"


def poll_interval(run_state: dict[str, Any]) -> float:
    """How long to wait before the next poll: short while a run is active, long otherwise."""
    if run_state.get("state") in _ACTIVE_STATES:
        return settings.stream_poll_active_seconds
    return settings.stream_poll_idle_seconds


def _event(name: str, payload: dict[str, Any]) -> dict[str, str]:
    return {"event": name, "data": json.dumps(payload, sort_keys=True)}


async def _reap_quietly(bundle_id: str) -> bool:
    """Reap a dead run; a failure here (a store hiccup) must not end the stream."""
    try:
        return await orchestrator.reap_stale(bundle_id)
    except Exception:  # noqa: BLE001
        logger.warning("sse_reap_failed", bundle_id=bundle_id, exc_info=True)
        return False


async def _pause(subscription: run_events.Subscription, seconds: float) -> None:
    """Wait for the next poll: ``seconds`` at most, and less as soon as the orchestrator announces a change.

    The fixed sleep stays (it is the fallback when no notify arrives, and the test seam); the wake-up races it.
    """
    sleeper = asyncio.ensure_future(_sleep(seconds))
    waker = asyncio.ensure_future(subscription.wait(seconds))
    try:
        done, _ = await asyncio.wait({sleeper, waker}, return_when=asyncio.FIRST_COMPLETED)
        if sleeper in done:
            sleeper.result()  # re-raises what the sleep ended with (a test's seam ends the stream with CancelledError)
    finally:
        for task in (sleeper, waker):
            if not task.done():
                task.cancel()
        await asyncio.gather(sleeper, waker, return_exceptions=True)


async def event_stream(bundle_id: str) -> AsyncIterator[dict[str, str]]:
    """The event generator behind the endpoint (module level so that it can be driven directly)."""
    last_iter_num: int = -1
    last_status_json: str | None = None
    # Subscribe BEFORE the first read: a change between that read and the first wait is then not lost
    subscription = run_events.subscribe(bundle_id)

    try:
        # 1. Send current status immediately on connect if present
        run_state = await firestore.get_run_state(bundle_id)
        if run_state:
            last_status_json = json.dumps(run_state, sort_keys=True)
            yield {"event": "status", "data": last_status_json}
        else:
            # Send initial status immediately so CDNs (Firebase Hosting) and proxies receive first byte in 0ms
            initial_status = {
                "kind": "status",
                "bundle_id": bundle_id,
                "state": "QUEUED",
                "stage": None,
                "progress": 0.0,
                "message": "Connected to stream. Ready for analysis.",
            }
            last_status_json = json.dumps(initial_status, sort_keys=True)
            yield {"event": "status", "data": last_status_json}

        # 2. Send current latest iteration immediately on connect if present
        latest = await firestore.latest_iteration(bundle_id)
        if latest is not None:
            last_iter_num = latest["iteration"]
            yield _event("iteration", latest)

        # 3. Stream changes continuously without closing after COMPLETE
        while True:
            await _pause(subscription, poll_interval(run_state or {}))

            # Poll run state; a RUNNING run whose heartbeat stopped is reaped (marked ERROR) first
            run_state = await firestore.get_run_state(bundle_id)
            if run_state.get("state") in _ACTIVE_STATES and await _reap_quietly(bundle_id):
                run_state = await firestore.get_run_state(bundle_id)
            current_status_json = json.dumps(run_state, sort_keys=True)
            if current_status_json != last_status_json:
                last_status_json = current_status_json
                yield {"event": "status", "data": current_status_json}

            # Poll assessment iteration
            latest = await firestore.latest_iteration(bundle_id)
            if latest is not None and latest.get("iteration") != last_iter_num:
                last_iter_num = latest["iteration"]
                yield _event("iteration", latest)

    except asyncio.CancelledError:
        # Client disconnected (or the server is shutting down): not an error, but never swallow the cancellation
        logger.info("sse_client_disconnected", bundle_id=bundle_id)
        raise
    except Exception:
        # The exception text can carry paths or content: it goes to the log, the client gets a fixed message
        logger.exception("sse_stream_failed", bundle_id=bundle_id)
        yield _event("error", {
            "kind": "error",
            "bundle_id": bundle_id,
            "code": "STREAM_EXCEPTION",
            "message": STREAM_FAILED_MESSAGE,
        })
    finally:
        subscription.close()


@router.get(
    "/bundles/{bundle_id}/stream",
    summary="SSE stream for pipeline status and iteration events",
    response_class=EventSourceResponse,
)
async def stream(bundle_id: str = Path(..., description="Target bundle ID")) -> EventSourceResponse:
    """Subscribe to real-time pipeline status and assessment iteration events."""
    if await firestore.get_bundle(bundle_id) is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    return EventSourceResponse(event_stream(bundle_id), ping=15)
