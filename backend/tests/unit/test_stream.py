"""SSE stream (api/v1/stream.py).

The generator is driven directly with patched Firestore functions: httpx's ASGITransport buffers the whole response
body, and an SSE stream never ends, so streaming over it would hang. Only the 404 (a plain JSON response) goes
through HTTP.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.api.v1 import stream
from app.core.config import settings
from app.repo import firestore
from app.services import orchestrator
from tests.helpers import api_client, create_bundle_with_documents

FILES = {"commercial_invoice.pdf": b"%PDF-1.4 stream invoice"}
SECRET = "/Users/someone/secret/path.pdf"


def status(state: str = "RUNNING", **extra: Any) -> dict[str, Any]:
    return {"kind": "status", "bundle_id": "bnd-x", "run_id": "run-1", "state": state, "stage": "extract",
            "progress": 0.4, "updated_at": "2026-10-10T00:00:00+00:00", **extra}


def iteration(number: int = 1) -> dict[str, Any]:
    return {"iteration": number, "bundle_id": "bnd-x", "status": "COMPLIANT_FOR_SUBMISSION", "checks": []}


class Script:
    """Scripted store reads + a recording `_sleep` that ends the stream (CancelledError) after ``cycles`` sleeps."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, states: list[Any], iterations: list[Any] | None = None,
                 cycles: int = 3, reaps: list[bool] | None = None) -> None:
        self.states = list(states)
        self.iterations = list(iterations if iterations is not None else [None])
        self.sleeps: list[float] = []
        self.reap_calls = 0
        self.cycles = cycles
        self.reaps = list(reaps or [])

        async def get_run_state(bundle_id: str, run_id: str | None = None):
            value = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            if isinstance(value, BaseException):
                raise value
            return value

        async def latest_iteration(bundle_id: str):
            return self.iterations.pop(0) if len(self.iterations) > 1 else self.iterations[0]

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)
            if len(self.sleeps) >= self.cycles:
                raise asyncio.CancelledError

        async def reap_stale(bundle_id: str) -> bool:
            self.reap_calls += 1
            return self.reaps.pop(0) if self.reaps else False

        monkeypatch.setattr(firestore, "get_run_state", get_run_state)
        monkeypatch.setattr(firestore, "latest_iteration", latest_iteration)
        monkeypatch.setattr(stream, "_sleep", sleep)
        monkeypatch.setattr(orchestrator, "reap_stale", reap_stale)


async def drain(generator) -> tuple[list[dict[str, Any]], BaseException | None]:
    """Everything the generator yields, and the exception that ended it (None if it ended by itself)."""
    events: list[dict[str, Any]] = []
    try:
        async for event in generator:
            events.append(event)
    except BaseException as exc:  # noqa: BLE001 - the test wants to see CancelledError too
        return events, exc
    return events, None


# ---------------------------------------------------------------------------
# C1: unknown bundle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stream_of_an_unknown_bundle_is_a_404_with_the_standard_envelope() -> None:
    async with api_client() as client:
        # a stream that opens never ends over ASGITransport, so bound the wait: the old behaviour (200, stays open) fails here
        response = await asyncio.wait_for(client.get("/api/v1/bundles/bnd-nope/stream"), timeout=3)
        reference = await client.get("/api/v1/bundles/bnd-nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["message"] == reference.json()["message"] == "Bundle 'bnd-nope' not found."
    assert response.json()["detail"] == {"bundle_id": "bnd-nope"}
    assert set(response.json()) == set(reference.json()) == {"code", "message", "detail", "request_id"}


@pytest.mark.asyncio
async def test_an_unknown_bundle_never_opens_the_stream(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(stream, "event_stream", lambda bundle_id: opened.append(bundle_id))
    async with api_client() as client:
        await asyncio.wait_for(client.get("/api/v1/bundles/bnd-nope/stream"), timeout=3)

    assert opened == []


@pytest.mark.asyncio
async def test_an_existing_bundle_gets_an_event_source_response_with_the_ping(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

    response = await stream.stream(bundle_id)

    assert response.media_type == "text/event-stream"
    assert response.ping_interval == 15


# ---------------------------------------------------------------------------
# existing behaviour: status then iteration on connect, changes streamed, open across runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_connect_the_status_comes_first_then_the_latest_iteration(monkeypatch) -> None:
    Script(monkeypatch, [status("COMPLETE")], [iteration(3)], cycles=1)

    events, ended = await drain(stream.event_stream("bnd-x"))

    assert [e["event"] for e in events] == ["status", "iteration"]
    assert json.loads(events[0]["data"])["state"] == "COMPLETE"
    assert json.loads(events[1]["data"])["iteration"] == 3
    assert isinstance(ended, asyncio.CancelledError)


@pytest.mark.asyncio
async def test_no_iteration_event_when_there_is_no_iteration_yet(monkeypatch) -> None:
    Script(monkeypatch, [status("RUNNING")], [None], cycles=1)

    events, _ = await drain(stream.event_stream("bnd-x"))

    assert [e["event"] for e in events] == ["status"]


@pytest.mark.asyncio
async def test_changes_are_streamed_and_unchanged_polls_are_silent(monkeypatch) -> None:
    states = [status("RUNNING"), status("RUNNING"), status("RUNNING", stage="ground"), status("COMPLETE"), status("COMPLETE")]
    iterations = [None, None, None, iteration(1), iteration(1)]
    Script(monkeypatch, states, iterations, cycles=5)

    events, _ = await drain(stream.event_stream("bnd-x"))

    assert [e["event"] for e in events] == ["status", "status", "status", "iteration"]
    assert [json.loads(e["data"]).get("stage") for e in events[:3]] == ["extract", "ground", "extract"]
    assert json.loads(events[3]["data"])["iteration"] == 1


@pytest.mark.asyncio
async def test_the_stream_stays_open_across_runs(monkeypatch) -> None:
    states = [status("COMPLETE"), status("COMPLETE"), status("RUNNING", run_id="run-2"), status("COMPLETE", run_id="run-2")]
    iterations = [iteration(1), iteration(1), iteration(1), iteration(2)]
    script = Script(monkeypatch, states, iterations, cycles=4)

    events, ended = await drain(stream.event_stream("bnd-x"))

    assert [e["event"] for e in events] == ["status", "iteration", "status", "status", "iteration"]
    assert len(script.sleeps) == 4 and isinstance(ended, asyncio.CancelledError)


@pytest.mark.asyncio
async def test_event_data_is_sorted_json_of_the_stored_record(monkeypatch) -> None:
    record = status("ERROR", message="boom")
    Script(monkeypatch, [record], [None], cycles=1)

    events, _ = await drain(stream.event_stream("bnd-x"))

    assert events[0]["data"] == json.dumps(record, sort_keys=True)


# ---------------------------------------------------------------------------
# C2: adaptive polling and reaping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("state", "active"), [("RUNNING", True), ("QUEUED", True), ("COMPLETE", False), ("ERROR", False)])
def test_the_poll_interval_follows_the_run_state(monkeypatch, state, active) -> None:
    monkeypatch.setattr(settings, "stream_poll_active_seconds", 0.7)
    monkeypatch.setattr(settings, "stream_poll_idle_seconds", 2.2)

    assert stream.poll_interval(status(state)) == (0.7 if active else 2.2)
    assert stream.poll_interval({}) == 2.2  # no state at all is idle


@pytest.mark.asyncio
async def test_the_stream_sleeps_the_active_interval_while_running_and_the_idle_one_otherwise(monkeypatch) -> None:
    monkeypatch.setattr(settings, "stream_poll_active_seconds", 0.7)
    monkeypatch.setattr(settings, "stream_poll_idle_seconds", 2.2)
    script = Script(monkeypatch, [status("RUNNING"), status("RUNNING"), status("COMPLETE"), status("COMPLETE")], cycles=4)

    await drain(stream.event_stream("bnd-x"))

    # connect read RUNNING -> sleep 0.7; read RUNNING -> 0.7; read COMPLETE -> 2.2; read COMPLETE -> 2.2
    assert script.sleeps == [0.7, 0.7, 2.2, 2.2]


@pytest.mark.asyncio
async def test_defaults_are_one_second_active_and_three_idle() -> None:
    assert stream.poll_interval(status("RUNNING")) == 1.0
    assert stream.poll_interval(status("COMPLETE")) == 3.0


def test_the_sleep_seam_defaults_to_asyncio_sleep() -> None:
    assert stream._sleep is asyncio.sleep


@pytest.mark.asyncio
async def test_a_running_state_is_checked_for_a_dead_run_every_cycle_and_a_finished_one_is_not(monkeypatch) -> None:
    script = Script(monkeypatch, [status("RUNNING"), status("RUNNING"), status("COMPLETE"), status("COMPLETE")], cycles=4)

    await drain(stream.event_stream("bnd-x"))

    # reads inside the loop: RUNNING, COMPLETE, COMPLETE -> only the RUNNING one is reaped
    assert script.reap_calls == 1


@pytest.mark.asyncio
async def test_a_reaped_run_is_announced_as_the_new_state(monkeypatch) -> None:
    dead = status("RUNNING")
    reaped = status("ERROR", message="The analysis was interrupted (no heartbeat)")
    Script(monkeypatch, [dead, dead, reaped], cycles=2, reaps=[True])

    events, _ = await drain(stream.event_stream("bnd-x"))

    assert [json.loads(e["data"])["state"] for e in events] == ["RUNNING", "ERROR"]
    assert json.loads(events[1]["data"])["message"] == "The analysis was interrupted (no heartbeat)"


@pytest.mark.asyncio
async def test_a_failing_reap_does_not_end_the_stream(monkeypatch) -> None:
    script = Script(monkeypatch, [status("RUNNING")], cycles=3)

    async def broken(bundle_id: str) -> bool:
        raise OSError("store hiccup")

    monkeypatch.setattr(orchestrator, "reap_stale", broken)
    events, ended = await drain(stream.event_stream("bnd-x"))

    assert [e["event"] for e in events] == ["status"]
    assert isinstance(ended, asyncio.CancelledError) and len(script.sleeps) == 3


@pytest.mark.asyncio
async def test_a_dead_run_is_reaped_for_real_while_somebody_watches(monkeypatch) -> None:
    """End to end with the real store: nobody sees RUNNING forever."""
    from datetime import datetime, timedelta, timezone

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await firestore.set_run_stage(bundle_id, "run-dead", stage="extract", progress=0.4)
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
        firestore._IN_MEMORY_RUNS[f"{bundle_id}:run-dead"]["updated_at"] = stamp

        sleeps: list[float] = []

        async def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) >= 2:
                raise asyncio.CancelledError

        monkeypatch.setattr(stream, "_sleep", sleep)
        events, _ = await drain(stream.event_stream(bundle_id))

    states = [json.loads(e["data"])["state"] for e in events if e["event"] == "status"]
    assert states == ["RUNNING", "ERROR"]


# ---------------------------------------------------------------------------
# C3: no leaks, clean cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_exception_inside_the_stream_becomes_a_fixed_error_event_and_is_logged(monkeypatch) -> None:
    Script(monkeypatch, [status("COMPLETE"), FileNotFoundError(SECRET)], cycles=5)

    with capture_logs() as logs:
        events, ended = await drain(stream.event_stream("bnd-x"))

    assert ended is None  # the stream ends after the error event
    assert events[-1]["event"] == "error"
    assert json.loads(events[-1]["data"]) == {
        "kind": "error", "bundle_id": "bnd-x", "code": "STREAM_EXCEPTION", "message": "The event stream failed unexpectedly",
    }
    assert "secret" not in json.dumps(events)
    logged = [entry for entry in logs if entry["event"] == "sse_stream_failed"]
    assert len(logged) == 1 and logged[0]["log_level"] == "error" and logged[0]["exc_info"]


@pytest.mark.asyncio
async def test_an_exception_before_the_first_event_is_handled_the_same_way(monkeypatch) -> None:
    Script(monkeypatch, [RuntimeError(SECRET)], cycles=5)

    events, ended = await drain(stream.event_stream("bnd-x"))

    assert ended is None
    assert [e["event"] for e in events] == ["error"]
    assert "secret" not in events[0]["data"]


@pytest.mark.asyncio
async def test_a_client_disconnect_is_logged_at_info_and_the_cancellation_is_reraised(monkeypatch) -> None:
    Script(monkeypatch, [status("COMPLETE")], cycles=1)

    with capture_logs() as logs:
        events, ended = await drain(stream.event_stream("bnd-x"))

    assert isinstance(ended, asyncio.CancelledError)
    assert [e["event"] for e in events] == ["status"]
    disconnect = [entry for entry in logs if entry["event"] == "sse_client_disconnected"]
    assert len(disconnect) == 1 and disconnect[0]["log_level"] == "info" and disconnect[0]["bundle_id"] == "bnd-x"
    assert not [entry for entry in logs if entry["event"] == "sse_stream_failed"]


@pytest.mark.asyncio
async def test_cancelling_a_consumer_task_cancels_it_for_real(monkeypatch) -> None:
    monkeypatch.setattr(stream, "_sleep", asyncio.sleep)
    monkeypatch.setattr(settings, "stream_poll_idle_seconds", 30)

    async def get_run_state(bundle_id: str, run_id: str | None = None):
        return status("COMPLETE")

    async def latest_iteration(bundle_id: str):
        return None

    monkeypatch.setattr(firestore, "get_run_state", get_run_state)
    monkeypatch.setattr(firestore, "latest_iteration", latest_iteration)

    async def consume() -> None:
        async for _ in stream.event_stream("bnd-x"):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled() is True


def test_the_module_never_puts_exception_text_into_an_event() -> None:
    import inspect

    source = inspect.getsource(stream)
    assert "str(exc)" not in source and "{exc}" not in source


# ---------------------------------------------------------------------------
# A1: the stream wakes at once when the orchestrator writes the run record
# ---------------------------------------------------------------------------


async def _first(events: list, predicate, timeout: float = 3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for stamp, event in events:
            if predicate(event):
                return stamp, event
        await asyncio.sleep(0.005)
    raise AssertionError(f"no matching event within {timeout}s; got {[e for _, e in events]}")


@pytest.mark.asyncio
async def test_an_idle_open_stream_shows_a_new_run_within_200ms_even_with_a_30_second_poll(monkeypatch) -> None:
    monkeypatch.setattr(settings, "stream_poll_idle_seconds", 30)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        real_dispatch = orchestrator.dispatch

        async def slow_extract(name: str, ctx: dict[str, Any]) -> dict[str, Any]:
            if name == "extract":
                await asyncio.sleep(5)  # the run stays RUNNING while the stream is looked at
            return await real_dispatch(name, ctx)

        monkeypatch.setattr(orchestrator, "dispatch", slow_extract)
        loop = asyncio.get_running_loop()
        seen: list[tuple[float, dict[str, str]]] = []

        async def consume() -> None:
            async for event in stream.event_stream(bundle_id):
                seen.append((loop.time(), event))

        consumer = asyncio.create_task(consume())
        try:
            await _first(seen, lambda e: e["event"] == "status")  # the connect snapshot: no run yet, so idle (30 s)
            await asyncio.sleep(0.05)  # the stream is now asleep in its poll wait

            started = loop.time()
            run_id = await orchestrator.start_run(bundle_id)
            stamp, event = await _first(seen, lambda e: e["event"] == "status" and json.loads(e["data"])["state"] == "RUNNING")

            assert json.loads(event["data"])["run_id"] == run_id
            assert stamp - started < 0.2, f"the stream saw the run {stamp - started:.2f}s after start_run"
        finally:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
            await orchestrator.shutdown(timeout=5)
