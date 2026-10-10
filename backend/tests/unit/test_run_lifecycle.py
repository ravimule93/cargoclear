"""Run lifecycle: who may start a run, how a run proves it is alive, how it ends, and what everybody is told.

The in-memory stores of the app never yield to the event loop, which hides every race; the tests that matter patch
the store's reads to ``await asyncio.sleep`` the way Firestore really does.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.config import Settings, settings
from app.gateway.errors import CargoClearError, ExtractionError, PipelineError, RunTimeoutError
from app.repo import firestore
from app.services import audit, orchestrator
from tests.helpers import api_client, audit_event_types, create_bundle_with_documents, wait_for_run
from tests.unit.firestore_fakes import FakeFirestore

FILES = {
    "commercial_invoice.pdf": b"%PDF-1.4 lifecycle invoice",
    "bill_of_lading.pdf": b"%PDF-1.4 lifecycle bol",
    "packing_list.pdf": b"%PDF-1.4 lifecycle packing",
}
SECRET = "/Users/someone/secret/path.pdf"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def yielding(real, delay: float = 0.01):
    """Wrap a store function so that it yields to the event loop first, like a network round trip."""
    async def wrapper(*args: Any, **kwargs: Any):
        await asyncio.sleep(delay)
        return await real(*args, **kwargs)

    return wrapper


def stall(monkeypatch: pytest.MonkeyPatch, stage: str, seconds: float) -> None:
    """Make one pipeline stage take ``seconds`` (cancellable), then carry on normally."""
    real = orchestrator.dispatch

    async def dispatch(name: str, ctx: dict[str, Any]) -> dict[str, Any]:
        if name == stage:
            await asyncio.sleep(seconds)
        return await real(name, ctx)

    monkeypatch.setattr(orchestrator, "dispatch", dispatch)


def explode(monkeypatch: pytest.MonkeyPatch, stage: str, error: BaseException) -> None:
    real = orchestrator.dispatch

    async def dispatch(name: str, ctx: dict[str, Any]) -> dict[str, Any]:
        if name == stage:
            raise error
        return await real(name, ctx)

    monkeypatch.setattr(orchestrator, "dispatch", dispatch)


async def wait_until(predicate, timeout: float = 5.0, interval: float = 0.005) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not reached in time")


async def in_stage(bundle_id: str, run_id: str, stage: str) -> bool:
    return (await firestore.get_run_state(bundle_id, run_id)).get("stage") == stage


def new_task(before: set[asyncio.Task]) -> asyncio.Task:
    [task] = set(orchestrator._RUNNING_TASKS) - before
    return task


async def events_of(client, bundle_id: str, event_type: str) -> list[dict[str, Any]]:
    audit_log = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
    return [e for e in audit_log["events"] if e["event_type"] == event_type]


async def seed_dead_run(bundle_id: str, run_id: str = "run-dead", *, age: float = 300.0, iteration: int = 1,
                        mode: str = "full", stage: str = "extract", started_event: bool = True) -> None:
    """A RUNNING record that nobody has touched for ``age`` seconds: what a crashed process leaves behind."""
    if started_event:
        await audit.record({
            "bundle_id": bundle_id, "iteration": iteration, "audit_event_type": "ANALYSIS_STARTED",
            "audit_payload": {"run_id": run_id, "mode": mode, "document_ids": []}, "actor": "system",
        })
    await firestore.set_run_stage(bundle_id, run_id, stage=stage, progress=0.4)
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    firestore._IN_MEMORY_RUNS[f"{bundle_id}:{run_id}"]["updated_at"] = stamp


def heartbeat_tasks() -> list[asyncio.Task]:
    return [t for t in asyncio.all_tasks() if (t.get_name() or "").startswith("heartbeat-") and not t.done()]


@pytest.fixture
def fast_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "run_heartbeat_seconds", 0.05)
    monkeypatch.setattr(settings, "run_stale_after_seconds", 0.5)


# ---------------------------------------------------------------------------
# B1: atomic claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_simultaneous_analyze_calls_yield_one_202_and_one_409_even_when_the_store_yields(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        monkeypatch.setattr(firestore, "get_run_state", yielding(firestore.get_run_state))
        monkeypatch.setattr(firestore, "latest_iteration", yielding(firestore.latest_iteration))
        stall(monkeypatch, "extract", 0.3)  # the winner is still running when the loser's turn comes

        first, second = await asyncio.gather(
            client.post(f"/api/v1/bundles/{bundle_id}/analyze"), client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        )

        assert sorted([first.status_code, second.status_code]) == [202, 409]
        winner, loser = (first, second) if first.status_code == 202 else (second, first)
        assert loser.json()["code"] == "CONFLICT"
        assert loser.json()["detail"]["run_id"] == winner.json()["run_id"]

        state = await wait_for_run(bundle_id, winner.json()["run_id"])
        assert state["state"] == "COMPLETE", state
        assert [i["iteration"] for i in await firestore.list_iterations(bundle_id)] == [1]
        types = await audit_event_types(client, bundle_id)
        assert types.count("ANALYSIS_STARTED") == 1 and types.count("ASSESSMENT_COMPLETED") == 1


@pytest.mark.asyncio
async def test_many_simultaneous_starts_of_both_kinds_still_yield_exactly_one_run(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        monkeypatch.setattr(firestore, "get_run_state", yielding(firestore.get_run_state))
        monkeypatch.setattr(firestore, "latest_iteration", yielding(firestore.latest_iteration))
        stall(monkeypatch, "extract", 0.3)

        responses = await asyncio.gather(*[
            client.post(f"/api/v1/bundles/{bundle_id}/{'analyze' if i % 2 else 'reassess'}") for i in range(6)
        ])

        assert sorted(r.status_code for r in responses) == [202] + [409] * 5
        winner = next(r for r in responses if r.status_code == 202)
        assert (await wait_for_run(bundle_id, winner.json()["run_id"]))["state"] == "COMPLETE"
        assert [i["iteration"] for i in await firestore.list_iterations(bundle_id)] == [1]


@pytest.mark.asyncio
async def test_starts_for_different_bundles_do_not_block_each_other(monkeypatch) -> None:
    async with api_client() as client:
        first_bundle = await create_bundle_with_documents(client, FILES, reference="A")
        second_bundle = await create_bundle_with_documents(client, FILES, reference="B")
        monkeypatch.setattr(firestore, "get_run_state", yielding(firestore.get_run_state))

        a, b = await asyncio.gather(
            client.post(f"/api/v1/bundles/{first_bundle}/analyze"), client.post(f"/api/v1/bundles/{second_bundle}/analyze")
        )

        assert (a.status_code, b.status_code) == (202, 202)
        for bundle_id, response in ((first_bundle, a), (second_bundle, b)):
            assert (await wait_for_run(bundle_id, response.json()["run_id"]))["state"] == "COMPLETE"


@pytest.mark.asyncio
async def test_consecutive_runs_get_consecutive_iteration_numbers(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        monkeypatch.setattr(firestore, "latest_iteration", yielding(firestore.latest_iteration))
        for _ in range(3):
            run_id = await orchestrator.start_run(bundle_id)
            assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"

        assert [i["iteration"] for i in await firestore.list_iterations(bundle_id)] == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_failed_run_does_not_burn_its_iteration_number(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "discrepancy", RuntimeError("boom"))
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "ERROR"
        monkeypatch.undo()

        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"
        assert [i["iteration"] for i in await firestore.list_iterations(bundle_id)] == [1]


@pytest.mark.asyncio
async def test_an_empty_bundle_is_still_a_422_before_anything_is_claimed() -> None:
    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={"reference": "EMPTY"})).json()["id"]

        response = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")

        assert response.status_code == 422
        assert (await firestore.get_run_state(bundle_id))["message"] == "Ready"  # no run record was written


@pytest.mark.asyncio
async def test_the_start_lock_alone_keeps_six_simultaneous_analyzes_to_one_run_when_the_claim_write_is_slow(monkeypatch) -> None:
    """The window between 'no live run' and 'the run record is written' is the claim write itself.

    With a 50 ms write and no start lock all six requests pass the check inside that window and all answer 202.
    """
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        real_stage = firestore.set_run_stage

        async def slow_claim(bundle_id, run_id, stage, progress):
            if stage == "initializing":
                await asyncio.sleep(0.05)  # BEFORE writing: the record does not exist yet while the others check
            return await real_stage(bundle_id, run_id, stage=stage, progress=progress)

        monkeypatch.setattr(firestore, "set_run_stage", slow_claim)
        stall(monkeypatch, "extract", 0.5)  # the winner is still RUNNING when the queued requests get their turn

        responses = await asyncio.gather(*[client.post(f"/api/v1/bundles/{bundle_id}/analyze") for _ in range(6)])

        assert sorted(r.status_code for r in responses) == [202] + [409] * 5
        winner = next(r for r in responses if r.status_code == 202).json()["run_id"]
        assert {r.json()["detail"]["run_id"] for r in responses if r.status_code == 409} == {winner}
        assert (await wait_for_run(bundle_id, winner))["state"] == "COMPLETE"
        assert [i["iteration"] for i in await firestore.list_iterations(bundle_id)] == [1]


@pytest.mark.asyncio
async def test_the_reap_lock_alone_keeps_four_concurrent_reapers_to_one_audit_event(monkeypatch) -> None:
    """The window is between reading 'RUNNING and stale' and writing ERROR: the audit read inside it yields.

    Without the reap lock all four reapers read RUNNING before any of them writes, and four ANALYSIS_FAILED
    events land in the (immutable) audit log.
    """
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=300)
        monkeypatch.setattr(firestore, "get_run_state", yielding(firestore.get_run_state))
        monkeypatch.setattr(audit, "list_audit_events", yielding(audit.list_audit_events))

        results = await asyncio.gather(*[orchestrator.reap_stale(bundle_id) for _ in range(4)])
        monkeypatch.undo()

        assert results.count(True) == 1 and results.count(False) == 3
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["verified"] is True


def _ctx(iteration: int = 1, **extra: Any) -> dict[str, Any]:
    return {"bundle_id": "bnd-x", "iteration": iteration, "documents": [], "final_status": "COMPLIANT_FOR_SUBMISSION", **extra}


@pytest.mark.asyncio
async def test_write_iteration_is_create_only_in_memory() -> None:
    await firestore.write_iteration(_ctx())

    with pytest.raises(PipelineError, match="iteration 1 already exists for bundle bnd-x"):
        await firestore.write_iteration(_ctx(final_status="MATERIAL_CONTRADICTION"))

    stored = await firestore.list_iterations("bnd-x")
    assert [(i["iteration"], i["status"]) for i in stored] == [(1, "COMPLIANT_FOR_SUBMISSION")]


@pytest.mark.asyncio
async def test_write_iteration_is_create_only_on_firestore(monkeypatch) -> None:
    fake = FakeFirestore()
    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: fake)
    await fake.collection("bundles").document("bnd-x").set({"id": "bnd-x", "current_iteration": 0, "status": "PENDING"})

    await firestore.write_iteration(_ctx())
    assert fake.docs[("bundles", "bnd-x", "iterations", "1")]["status"] == "COMPLIANT_FOR_SUBMISSION"
    assert fake.docs[("bundles", "bnd-x")]["current_iteration"] == 1

    with pytest.raises(PipelineError, match="iteration 1 already exists for bundle bnd-x"):
        await firestore.write_iteration(_ctx(final_status="MATERIAL_CONTRADICTION"))

    assert fake.docs[("bundles", "bnd-x", "iterations", "1")]["status"] == "COMPLIANT_FOR_SUBMISSION"  # untouched
    assert fake.docs[("bundles", "bnd-x")]["status"] == "COMPLIANT_FOR_SUBMISSION"  # the pointer was not rewritten
    assert ("create", ("bundles", "bnd-x", "iterations", "1")) in fake.calls
    assert ("set", ("bundles", "bnd-x", "iterations", "1")) not in fake.calls


@pytest.mark.asyncio
async def test_a_losing_second_run_fails_with_the_create_only_error_not_a_second_iteration_1(monkeypatch) -> None:
    """The durable backstop: even if two runs got past the claim, only one iteration 1 can exist."""
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"
        iteration = await firestore.latest_iteration(bundle_id)

        with pytest.raises(PipelineError):
            await firestore.write_iteration({**_ctx(), "bundle_id": bundle_id, "iteration": iteration["iteration"]})


# ---------------------------------------------------------------------------
# B2: heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_updated_at_advances_while_a_slow_stage_runs(monkeypatch, fast_heartbeat) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 0.4)
        run_id = await orchestrator.start_run(bundle_id)
        await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))

        seen = set()
        for _ in range(60):
            record = await firestore.get_run_state(bundle_id, run_id)
            if record["state"] != "RUNNING" or record["stage"] != "extract":
                break
            seen.add(record["updated_at"])
            await asyncio.sleep(0.01)

        assert len(seen) >= 4, f"updated_at took {len(seen)} distinct value(s) during a 0.4 s stage: {sorted(seen)}"
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"


@pytest.mark.asyncio
async def test_a_heartbeat_touches_nothing_but_updated_at() -> None:
    await firestore.set_run_stage("bnd-x", "run-1", stage="extract", progress=0.4)
    before = dict(firestore._IN_MEMORY_RUNS["bnd-x:run-1"])

    await asyncio.sleep(0.01)
    await firestore.touch_run("bnd-x", "run-1")

    after = firestore._IN_MEMORY_RUNS["bnd-x:run-1"]
    assert after["updated_at"] > before["updated_at"]
    assert {k: v for k, v in after.items() if k != "updated_at"} == {k: v for k, v in before.items() if k != "updated_at"}


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["complete", "error"])
async def test_a_heartbeat_never_revives_a_finished_run(finish) -> None:
    await firestore.set_run_stage("bnd-x", "run-1", stage="finalize", progress=0.98)
    if finish == "complete":
        await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0)
    else:
        await firestore.set_run_error("bnd-x", "run-1", error="it broke")
    before = dict(firestore._IN_MEMORY_RUNS["bnd-x:run-1"])

    await asyncio.sleep(0.01)
    await firestore.touch_run("bnd-x", "run-1")

    assert firestore._IN_MEMORY_RUNS["bnd-x:run-1"] == before


@pytest.mark.asyncio
async def test_touching_a_run_that_does_not_exist_creates_nothing() -> None:
    await firestore.touch_run("bnd-x", "run-ghost")
    assert "bnd-x:run-ghost" not in firestore._IN_MEMORY_RUNS


@pytest.mark.asyncio
async def test_touch_run_on_firestore_writes_only_updated_at_and_only_while_running(monkeypatch) -> None:
    fake = FakeFirestore()
    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: fake)
    path = ("bundles", "bnd-x", "runs", "run-1")

    await firestore.touch_run("bnd-x", "run-1")
    assert path not in fake.docs, "nothing is created for a missing run"

    await firestore.set_run_stage("bnd-x", "run-1", stage="extract", progress=0.4)
    before = dict(fake.docs[path])
    await asyncio.sleep(0.01)
    await firestore.touch_run("bnd-x", "run-1")
    assert fake.docs[path]["updated_at"] > before["updated_at"]
    assert {k: v for k, v in fake.docs[path].items() if k != "updated_at"} == {k: v for k, v in before.items() if k != "updated_at"}

    await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0)
    finished = dict(fake.docs[path])
    await firestore.touch_run("bnd-x", "run-1")
    assert fake.docs[path] == finished


@pytest.mark.asyncio
async def test_the_heartbeat_is_stopped_before_the_terminal_state_is_written(monkeypatch, fast_heartbeat) -> None:
    order: list[str] = []
    real_touch, real_state = firestore.touch_run, firestore.set_run_state

    async def touch(*a, **k):
        order.append("touch")
        return await real_touch(*a, **k)

    async def state(bundle_id, run_id, state, progress, only_if_state=None):
        order.append(f"state:{state}")
        await asyncio.sleep(0.15)  # long enough for several heartbeats if one were still running
        return await real_state(bundle_id, run_id, state=state, progress=progress, only_if_state=only_if_state)

    monkeypatch.setattr(firestore, "touch_run", touch)
    monkeypatch.setattr(firestore, "set_run_state", state)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 0.2)
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"

    assert "touch" in order, "the heartbeat should have fired during the 0.2 s stage"
    assert order.index("state:COMPLETE") == len(order) - 1, f"a heartbeat ran after the terminal write: {order}"


@pytest.mark.asyncio
async def test_the_heartbeat_task_is_gone_after_success(fast_heartbeat) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        await wait_for_run(bundle_id, run_id)
        await asyncio.sleep(0.01)

    assert heartbeat_tasks() == []


@pytest.mark.asyncio
async def test_the_heartbeat_task_is_gone_after_failure(monkeypatch, fast_heartbeat) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "discrepancy", RuntimeError("boom"))
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "ERROR"
        await asyncio.sleep(0.01)

    assert heartbeat_tasks() == []


@pytest.mark.asyncio
async def test_the_heartbeat_task_is_gone_after_cancellation(monkeypatch, fast_heartbeat) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)
        before = set(orchestrator._RUNNING_TASKS)
        run_id = await orchestrator.start_run(bundle_id)
        task = new_task(before)
        await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))
        assert len(heartbeat_tasks()) == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert heartbeat_tasks() == []


@pytest.mark.asyncio
async def test_a_failing_heartbeat_write_does_not_kill_the_run(monkeypatch, fast_heartbeat) -> None:
    async def broken(*_a, **_k):
        raise OSError("store hiccup")

    monkeypatch.setattr(firestore, "touch_run", broken)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 0.2)
        run_id = await orchestrator.start_run(bundle_id)

        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"


def test_the_stale_window_must_cover_three_heartbeats() -> None:
    assert Settings(_env_file=None, RUN_HEARTBEAT_SECONDS=10, RUN_STALE_AFTER_SECONDS=30).run_stale_after_seconds == 30
    with pytest.raises(ValueError, match="at least 3 x"):
        Settings(_env_file=None, RUN_HEARTBEAT_SECONDS=10, RUN_STALE_AFTER_SECONDS=29.9)
    with pytest.raises(ValueError, match="at least 3 x"):
        Settings(_env_file=None, RUN_HEARTBEAT_SECONDS=60)  # the default 90 s window is now too small


def test_lifecycle_defaults() -> None:
    fresh = Settings(_env_file=None)
    assert (fresh.run_heartbeat_seconds, fresh.run_stale_after_seconds, fresh.run_timeout_seconds) == (10, 90, 1200)
    assert (fresh.stream_poll_active_seconds, fresh.stream_poll_idle_seconds) == (1.0, 3.0)


# ---------------------------------------------------------------------------
# B3: cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_the_pipeline_task_ends_the_run_in_error_and_audits_it_once(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)
        before = set(orchestrator._RUNNING_TASKS)
        run_id = await orchestrator.start_run(bundle_id)
        task = new_task(before)
        await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled() is True
        record = await firestore.get_run_state(bundle_id, run_id)
        assert record["state"] == "ERROR"
        assert record["message"] == "cancelled: the server is shutting down"
        failed = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert len(failed) == 1
        assert failed[0]["payload"] == {
            "run_id": run_id, "mode": "full", "stage": "extract", "error_type": "CancelledError",
            "code": "RUN_CANCELLED", "message": "cancelled: the server is shutting down", "reason": "cancelled",
        }
        assert "ASSESSMENT_COMPLETED" not in await audit_event_types(client, bundle_id)
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["verified"] is True


@pytest.mark.asyncio
async def test_after_a_cancelled_run_the_bundle_accepts_a_new_analysis_at_once(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)
        before = set(orchestrator._RUNNING_TASKS)
        run_id = await orchestrator.start_run(bundle_id)
        task = new_task(before)
        await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        monkeypatch.undo()

        response = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")

        assert response.status_code == 202
        assert (await wait_for_run(bundle_id, response.json()["run_id"]))["state"] == "COMPLETE"


@pytest.mark.asyncio
async def test_an_audit_failure_during_cancellation_does_not_mask_the_cancellation(monkeypatch) -> None:
    real_record = audit.record

    async def failing(ctx):
        if ctx.get("audit_event_type") == "ANALYSIS_FAILED":
            raise OSError("audit store is down")
        return await real_record(ctx)

    monkeypatch.setattr(audit, "record", failing)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)
        before = set(orchestrator._RUNNING_TASKS)
        run_id = await orchestrator.start_run(bundle_id)
        task = new_task(before)
        await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled() is True
        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "ERROR"


@pytest.mark.asyncio
async def test_cancellation_cleanup_is_bounded_and_still_cancels(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator, "_CLEANUP_TIMEOUT_SECONDS", 0.2)
    real_record = audit.record

    async def hanging(ctx):
        if ctx.get("audit_event_type") == "ANALYSIS_FAILED":
            await asyncio.sleep(30)
        return await real_record(ctx)

    monkeypatch.setattr(audit, "record", hanging)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)
        before = set(orchestrator._RUNNING_TASKS)
        run_id = await orchestrator.start_run(bundle_id)
        task = new_task(before)
        await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))

        started = asyncio.get_running_loop().time()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert asyncio.get_running_loop().time() - started < 2.0
        assert task.cancelled() is True
        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "ERROR"


@pytest.mark.asyncio
async def test_shutdown_cancels_running_runs_and_waits_for_their_cleanup(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)
        run_id = await orchestrator.start_run(bundle_id)
        await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))

        await orchestrator.shutdown(timeout=5)

        assert not [t for t in orchestrator._RUNNING_TASKS if not t.done()]
        assert (await firestore.get_run_state(bundle_id, run_id))["message"] == "cancelled: the server is shutting down"
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1


@pytest.mark.asyncio
async def test_shutdown_with_nothing_running_is_a_no_op() -> None:
    await orchestrator.shutdown(timeout=1)


@pytest.mark.asyncio
async def test_the_app_lifespan_shuts_the_orchestrator_down(monkeypatch) -> None:
    from app.main import app

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)
        async with app.router.lifespan_context(app):
            run_id = await orchestrator.start_run(bundle_id)
            await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))
        # leaving the lifespan = server shutdown

        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "ERROR"
        assert not [t for t in orchestrator._RUNNING_TASKS if not t.done()]


# ---------------------------------------------------------------------------
# B4: deadline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_that_exceeds_its_deadline_ends_in_error_with_the_timeout_text(monkeypatch, fast_heartbeat) -> None:
    monkeypatch.setattr(settings, "run_timeout_seconds", 0.3)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)

        started = asyncio.get_running_loop().time()
        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)

        assert asyncio.get_running_loop().time() - started < 3.0
        assert state["state"] == "ERROR"
        assert state["message"] == "the analysis exceeded the time limit"
        [failed] = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert failed["payload"] == {
            "run_id": run_id, "mode": "full", "stage": "extract", "error_type": "RunTimeoutError",
            "code": "RUN_TIMEOUT", "message": "the analysis exceeded the time limit", "reason": "timeout",
        }
        assert "ASSESSMENT_COMPLETED" not in await audit_event_types(client, bundle_id)
        await asyncio.sleep(0.01)
        assert heartbeat_tasks() == []


@pytest.mark.asyncio
async def test_a_generous_deadline_does_not_disturb_a_normal_run(monkeypatch) -> None:
    monkeypatch.setattr(settings, "run_timeout_seconds", 600)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)

        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"


@pytest.mark.asyncio
async def test_a_timeout_raised_inside_a_stage_is_not_reported_as_the_run_deadline(monkeypatch) -> None:
    """E.g. a socket or client timeout: the deadline (1200 s) has not expired, so this is an ordinary failure."""
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "extract", TimeoutError("read timed out talking to 10.1.2.3"))

        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)
        [failed] = await events_of(client, bundle_id, "ANALYSIS_FAILED")

    assert state["state"] == "ERROR"
    assert state["message"] == f"The analysis failed unexpectedly (reference: {run_id})."
    assert failed["payload"] == {
        "run_id": run_id, "mode": "full", "stage": "extract", "error_type": "TimeoutError",
        "code": "INTERNAL_ERROR", "message": f"The analysis failed unexpectedly (reference: {run_id}).",
    }, "no 'reason': this was not the deadline"
    assert "10.1.2.3" not in json.dumps([state, failed])


@pytest.mark.asyncio
async def test_a_stage_timeout_that_races_the_deadline_is_still_only_the_deadline_when_it_expired(monkeypatch) -> None:
    monkeypatch.setattr(settings, "run_timeout_seconds", 0.2)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)

        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)

    assert state["message"] == "the analysis exceeded the time limit"


# ---------------------------------------------------------------------------
# B5: public errors
# ---------------------------------------------------------------------------


def test_public_error_for_a_domain_error_is_its_own_code_and_message() -> None:
    error = ExtractionError("Extraction failed for document d1 after 3 attempts: empty response.", detail={"x": 1})
    assert orchestrator.public_error(error, "run-1") == {
        "code": "EXTRACTION_FAILED", "message": "Extraction failed for document d1 after 3 attempts: empty response.",
    }
    assert orchestrator.public_error(PipelineError("iteration 1 already exists for bundle b"), "run-1")["code"] == "PIPELINE_ERROR"


def test_public_error_for_cancellation_is_a_fixed_text() -> None:
    assert orchestrator.public_error(asyncio.CancelledError(), "run-1") == {
        "code": "RUN_CANCELLED", "message": "cancelled: the server is shutting down",
    }


def test_public_error_for_the_run_deadline_is_a_fixed_text() -> None:
    deadline = RunTimeoutError("the analysis exceeded the time limit")

    assert orchestrator.public_error(deadline, "run-1") == {
        "code": "RUN_TIMEOUT", "message": "the analysis exceeded the time limit",
    }
    assert isinstance(deadline, CargoClearError) and deadline.code == "RUN_TIMEOUT"


@pytest.mark.parametrize("error", [TimeoutError("socket timed out talking to 10.1.2.3"), asyncio.TimeoutError()])
def test_any_other_timeout_is_an_internal_error_not_the_run_deadline(error) -> None:
    result = orchestrator.public_error(error, "run-1")

    assert result == {"code": "INTERNAL_ERROR", "message": "The analysis failed unexpectedly (reference: run-1)."}
    assert "10.1.2.3" not in json.dumps(result)


@pytest.mark.parametrize("error", [FileNotFoundError(SECRET), KeyError(SECRET), ValueError(SECRET), OSError(13, SECRET)])
def test_public_error_for_anything_else_hides_the_text_and_gives_a_reference(error) -> None:
    result = orchestrator.public_error(error, "run-abc123")

    assert result == {"code": "INTERNAL_ERROR", "message": "The analysis failed unexpectedly (reference: run-abc123)."}
    assert "secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_a_failing_run_leaks_its_exception_text_nowhere(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "extract", FileNotFoundError(SECRET))

        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)

        assert state["state"] == "ERROR"
        assert state["message"] == f"The analysis failed unexpectedly (reference: {run_id})."
        [failed] = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert failed["payload"] == {
            "run_id": run_id, "mode": "full", "stage": "extract", "error_type": "FileNotFoundError",
            "code": "INTERNAL_ERROR", "message": f"The analysis failed unexpectedly (reference: {run_id}).",
        }
        everything = json.dumps([
            await firestore.get_run_state(bundle_id, run_id),
            (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json(),
            (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json(),
            (await client.get(f"/api/v1/bundles/{bundle_id}")).json(),
            (await client.get(f"/api/v1/bundles/{bundle_id}/iterations")).json(),
        ])
        assert "secret" not in everything and "path.pdf" not in everything and "/Users/" not in everything


@pytest.mark.asyncio
async def test_an_extraction_error_keeps_its_message_intact(monkeypatch) -> None:
    message = "Extraction failed for document doc-1 after 3 attempts: empty response."
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "extract", ExtractionError(message, detail={"document_id": "doc-1", "attempts": 3}))

        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)
        [failed] = await events_of(client, bundle_id, "ANALYSIS_FAILED")

    assert state["message"] == message
    assert failed["payload"]["message"] == message and failed["payload"]["code"] == "EXTRACTION_FAILED"
    assert failed["payload"]["error_type"] == "ExtractionError"


@pytest.mark.asyncio
async def test_a_preprocess_failure_in_live_mode_names_the_class_not_the_text(monkeypatch) -> None:
    from app.agents.tools import bq_tariff
    from app.services import storage

    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: None)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        monkeypatch.setattr(settings, "app_mode", "live")

        async def broken_download(_bundle_id: str, document_id: str) -> bytes:
            raise FileNotFoundError(f"{SECRET} for {document_id}")

        monkeypatch.setattr(storage, "download_raw", broken_download)
        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)

    assert state["state"] == "ERROR"
    assert state["message"].startswith("Preprocessing failed for document ")
    assert state["message"].endswith(": FileNotFoundError")
    assert "secret" not in state["message"]


@pytest.mark.asyncio
async def test_the_audit_log_stays_valid_after_a_failed_run(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "extract", FileNotFoundError(SECRET))
        run_id = await orchestrator.start_run(bundle_id)
        await wait_for_run(bundle_id, run_id)

        assert (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["verified"] is True


# ---------------------------------------------------------------------------
# B6: stale runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_left_by_a_dead_process_no_longer_blocks_analyze() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=300)  # 5 minutes without a heartbeat

        response = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")

        assert response.status_code == 202, response.text
        assert (await wait_for_run(bundle_id, response.json()["run_id"]))["state"] == "COMPLETE"
        dead = await firestore.get_run_state(bundle_id, "run-dead")
        assert (dead["state"], dead["message"]) == ("ERROR", "The analysis was interrupted (no heartbeat)")


@pytest.mark.asyncio
async def test_a_dead_run_is_reaped_exactly_once_with_the_right_audit() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=300, iteration=4, mode="reassess", stage="ground")

        assert await orchestrator.reap_stale(bundle_id) is True
        assert await orchestrator.reap_stale(bundle_id) is False  # idempotent: it only acts on RUNNING
        assert await orchestrator.reap_stale(bundle_id) is False

        [failed] = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert failed["iteration"] == 4
        assert failed["payload"] == {
            "run_id": "run-dead", "mode": "reassess", "stage": "ground", "error_type": "RunInterruptedError",
            "code": "RUN_INTERRUPTED", "message": "The analysis was interrupted (no heartbeat)", "reason": "interrupted",
        }
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["verified"] is True


@pytest.mark.asyncio
async def test_concurrent_reapers_write_one_audit_event(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=300)
        monkeypatch.setattr(firestore, "get_run_state", yielding(firestore.get_run_state))

        results = await asyncio.gather(*[orchestrator.reap_stale(bundle_id) for _ in range(6)])

        assert results.count(True) == 1
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1


@pytest.mark.asyncio
async def test_a_dead_run_without_a_started_event_is_still_reaped() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=300, started_event=False)

        assert await orchestrator.reap_stale(bundle_id) is True
        [failed] = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert failed["payload"]["run_id"] == "run-dead" and failed["payload"]["reason"] == "interrupted"


@pytest.mark.asyncio
async def test_a_fresh_run_is_never_reaped_and_still_blocks_analyze() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=5)  # 5 s old, inside the 90 s window

        assert await orchestrator.reap_stale(bundle_id) is False
        response = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")

        assert response.status_code == 409
        assert response.json()["detail"]["run_id"] == "run-dead"
        assert (await firestore.get_run_state(bundle_id, "run-dead"))["state"] == "RUNNING"
        assert await events_of(client, bundle_id, "ANALYSIS_FAILED") == []


@pytest.mark.asyncio
async def test_the_stale_threshold_is_the_setting(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=100)
        monkeypatch.setattr(settings, "run_stale_after_seconds", 120)
        assert await orchestrator.reap_stale(bundle_id) is False

        monkeypatch.setattr(settings, "run_stale_after_seconds", 99)
        assert await orchestrator.reap_stale(bundle_id) is True


@pytest.mark.asyncio
async def test_a_bundle_with_no_runs_is_unaffected_by_reaping() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

        assert await orchestrator.reap_stale(bundle_id) is False
        assert await events_of(client, bundle_id, "ANALYSIS_FAILED") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["COMPLETE", "ERROR"])
async def test_finished_runs_are_never_reaped(state) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=300)
        if state == "COMPLETE":
            await firestore.set_run_state(bundle_id, "run-dead", state="COMPLETE", progress=1.0)
        else:
            await firestore.set_run_error(bundle_id, "run-dead", error="it broke")
        firestore._IN_MEMORY_RUNS[f"{bundle_id}:run-dead"]["updated_at"] = "2000-01-01T00:00:00+00:00"

        assert await orchestrator.reap_stale(bundle_id) is False
        assert await events_of(client, bundle_id, "ANALYSIS_FAILED") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stamp", [None, "", "not a timestamp"])
async def test_a_running_record_without_a_usable_timestamp_cannot_prove_it_is_alive(stamp) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=0)
        firestore._IN_MEMORY_RUNS[f"{bundle_id}:run-dead"]["updated_at"] = stamp

        assert await orchestrator.reap_stale(bundle_id) is True


@pytest.mark.asyncio
async def test_a_naive_timestamp_is_read_as_utc() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=0)
        naive = (datetime.now(timezone.utc) - timedelta(seconds=300)).replace(tzinfo=None).isoformat()
        firestore._IN_MEMORY_RUNS[f"{bundle_id}:run-dead"]["updated_at"] = naive

        assert await orchestrator.reap_stale(bundle_id) is True


def test_run_interrupted_error_is_a_domain_error_with_its_own_code() -> None:
    error = orchestrator.RunInterruptedError("The analysis was interrupted (no heartbeat)")
    assert isinstance(error, CargoClearError) and error.code == "RUN_INTERRUPTED"


# ---------------------------------------------------------------------------
# the remaining failure branches of the lifecycle bookkeeping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaping_does_not_depend_on_the_audit_read_working(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=300, iteration=3, mode="reassess")

        async def broken(_bundle_id: str):
            raise OSError("audit read failed")

        monkeypatch.setattr(audit, "list_audit_events", broken)
        assert await orchestrator.reap_stale(bundle_id) is True
        monkeypatch.undo()

        [failed] = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert (failed["iteration"], failed["payload"]["mode"]) == (0, "unknown")  # the started event could not be read
        assert (await firestore.get_run_state(bundle_id, "run-dead"))["state"] == "ERROR"


@pytest.mark.asyncio
async def test_a_failed_state_write_still_audits_the_failure(monkeypatch) -> None:
    async def broken(*_a, **_k):
        raise OSError("state store down")

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "extract", RuntimeError("boom"))
        monkeypatch.setattr(firestore, "set_run_error", broken)

        before = set(orchestrator._RUNNING_TASKS)
        await orchestrator.start_run(bundle_id)
        task = new_task(before)
        await asyncio.wait({task}, timeout=5)

        [failed] = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert failed["payload"]["code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_shutdown_reports_a_run_that_does_not_finish_its_cleanup_in_time(monkeypatch) -> None:
    from structlog.testing import capture_logs

    monkeypatch.setattr(orchestrator, "_CLEANUP_TIMEOUT_SECONDS", 0.4)
    real_record = audit.record

    async def slow(ctx):
        if ctx.get("audit_event_type") == "ANALYSIS_FAILED":
            await asyncio.sleep(30)
        return await real_record(ctx)

    monkeypatch.setattr(audit, "record", slow)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 30)
        before = set(orchestrator._RUNNING_TASKS)
        run_id = await orchestrator.start_run(bundle_id)
        task = new_task(before)
        await wait_until(lambda: in_stage(bundle_id, run_id, "extract"))

        with capture_logs() as logs:
            await orchestrator.shutdown(timeout=0.05)

        assert [e for e in logs if e["event"] == "shutdown_runs_still_running"][0]["count"] == 1
        await asyncio.wait({task}, timeout=5)  # the bounded cleanup finishes by itself
        assert task.cancelled() is True


@pytest.mark.asyncio
async def test_a_listed_document_without_an_id_is_skipped_by_preprocessing() -> None:
    ctx = {"bundle_id": "bnd-x", "documents": [{"filename": "no-id.pdf"}, {"document_id": None}]}

    await orchestrator._preprocess_documents(ctx)

    assert ctx["processed_pages"] == [] and ctx["transform_meta"] == []


# ---------------------------------------------------------------------------
# A3: fencing. A run that lost its claim (reaped, superseded) must not write anything more
# ---------------------------------------------------------------------------


def age_run(bundle_id: str, run_id: str, seconds: float = 300.0) -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    firestore._IN_MEMORY_RUNS[f"{bundle_id}:{run_id}"]["updated_at"] = stamp


async def start_held_run(monkeypatch, bundle_id: str, stage: str = "extract"):
    """Start a run that waits inside ``stage`` until the returned gate is opened. Returns (run_id, task, gate)."""
    gate = asyncio.Event()
    real = orchestrator.dispatch

    async def hold(name: str, ctx: dict[str, Any]) -> dict[str, Any]:
        if name == stage:
            await gate.wait()
        return await real(name, ctx)

    monkeypatch.setattr(orchestrator, "dispatch", hold)
    before = set(orchestrator._RUNNING_TASKS)
    run_id = await orchestrator.start_run(bundle_id)
    task = new_task(before)
    await wait_until(lambda: in_stage(bundle_id, run_id, stage))
    return run_id, task, gate


@pytest.mark.asyncio
async def test_a_run_reaped_while_merely_slow_cannot_finish_afterwards(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id, task, gate = await start_held_run(monkeypatch, bundle_id)
        age_run(bundle_id, run_id)
        assert await orchestrator.reap_stale(bundle_id) is True

        gate.set()  # the slow run wakes up and carries on
        await asyncio.wait({task}, timeout=5)

        record = await firestore.get_run_state(bundle_id, run_id)
        assert (record["state"], record["message"]) == ("ERROR", "The analysis was interrupted (no heartbeat)")
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1
        assert "ASSESSMENT_COMPLETED" not in await audit_event_types(client, bundle_id)
        assert await firestore.list_iterations(bundle_id) == []
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["verified"] is True


@pytest.mark.asyncio
async def test_a_reaped_run_that_wakes_up_after_a_newer_run_owns_the_bundle_leaves_the_newer_run_alone(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        old_id, old_task, gate = await start_held_run(monkeypatch, bundle_id)
        age_run(bundle_id, old_id)
        monkeypatch.undo()  # the newer run is not held

        new_id = await orchestrator.start_run(bundle_id)  # reaps the old run, claims the bundle
        assert (await wait_for_run(bundle_id, new_id))["state"] == "COMPLETE"
        newer = await firestore.list_iterations(bundle_id)
        assert [i["iteration"] for i in newer] == [1]

        gate.set()
        await asyncio.wait({old_task}, timeout=5)

        assert [i["iteration"] for i in await firestore.list_iterations(bundle_id)] == [1]
        assert (await firestore.list_iterations(bundle_id))[0] == newer[0]  # untouched
        assert (await firestore.get_run_state(bundle_id, new_id))["state"] == "COMPLETE"
        assert (await firestore.get_run_state(bundle_id, old_id))["state"] == "ERROR"
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1
        assert len(await events_of(client, bundle_id, "ASSESSMENT_COMPLETED")) == 1


@pytest.mark.asyncio
async def test_a_run_that_lost_its_claim_ends_with_the_interrupted_error_and_writes_no_stage(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id, task, gate = await start_held_run(monkeypatch, bundle_id)
        age_run(bundle_id, run_id)
        await orchestrator.reap_stale(bundle_id)

        writes: list[str] = []
        real_stage = firestore.set_run_stage

        async def spy(bundle_id, run_id, stage, progress):
            writes.append(stage)
            return await real_stage(bundle_id, run_id, stage=stage, progress=progress)

        monkeypatch.setattr(firestore, "set_run_stage", spy)
        gate.set()
        await asyncio.wait({task}, timeout=5)

        assert writes == [], "a fenced run must not resurrect its ERROR record with a stage write"
        assert task.done() and not task.cancelled()


@pytest.mark.asyncio
async def test_the_claim_is_verified_with_one_read_of_its_own_run_right_before_the_iteration(monkeypatch) -> None:
    calls: list[tuple[str, Any]] = []
    real_get, real_write = firestore.get_run_state, firestore.write_iteration

    def in_pipeline() -> bool:  # the test's own polling reads must not count
        return (asyncio.current_task().get_name() or "").startswith("run-run-")

    async def spy_get(bundle_id, run_id=None):
        if in_pipeline():
            calls.append(("get_run_state", run_id))
        return await real_get(bundle_id, run_id)

    async def spy_write(ctx):
        calls.append(("write_iteration", ctx["run_id"]))
        return await real_write(ctx)

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        monkeypatch.setattr(firestore, "get_run_state", spy_get)
        monkeypatch.setattr(firestore, "write_iteration", spy_write)
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"

    write_at = calls.index(("write_iteration", run_id))
    assert calls[write_at - 1] == ("get_run_state", run_id), calls


@pytest.mark.asyncio
async def test_a_normal_run_is_unaffected_by_the_fence() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)

        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"
        assert [i["iteration"] for i in await firestore.list_iterations(bundle_id)] == [1]
        types = await audit_event_types(client, bundle_id)
        assert types.count("ANALYSIS_STARTED") == types.count("ASSESSMENT_COMPLETED") == 1 and "ANALYSIS_FAILED" not in types


@pytest.mark.asyncio
async def test_fail_run_does_nothing_when_the_run_is_already_in_error() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id)
        await orchestrator.reap_stale(bundle_id)
        before = dict(firestore._IN_MEMORY_RUNS[f"{bundle_id}:run-dead"])

        await orchestrator._fail_run(
            bundle_id=bundle_id, run_id="run-dead", iteration=1, mode="full", stage="extract", exc=RuntimeError("late"),
        )

        assert firestore._IN_MEMORY_RUNS[f"{bundle_id}:run-dead"] == before, "no overwrite"
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1, "no second ANALYSIS_FAILED"


@pytest.mark.asyncio
async def test_fail_run_still_records_a_run_that_is_running() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=1)

        await orchestrator._fail_run(
            bundle_id=bundle_id, run_id="run-dead", iteration=1, mode="full", stage="extract", exc=RuntimeError("real"),
        )

        assert (await firestore.get_run_state(bundle_id, "run-dead"))["state"] == "ERROR"
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1


@pytest.mark.asyncio
async def test_the_complete_write_is_conditional_and_a_refused_one_is_logged(monkeypatch) -> None:
    """The run is reaped in the tiny window between its last check and the COMPLETE write: ERROR must survive."""
    from structlog.testing import capture_logs

    real_record = audit.record

    async def reap_during_the_completed_audit(ctx):
        result = await real_record(ctx)
        if ctx.get("audit_event_type") == "ASSESSMENT_COMPLETED":
            age_run(ctx["bundle_id"], run_id_box[0])
            await orchestrator.reap_stale(ctx["bundle_id"])
        return result

    run_id_box: list[str] = []
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        monkeypatch.setattr(audit, "record", reap_during_the_completed_audit)
        with capture_logs() as logs:
            run_id = await orchestrator.start_run(bundle_id)
            run_id_box.append(run_id)
            await wait_until(lambda: _is_error(bundle_id, run_id))
            await asyncio.sleep(0.05)

    record = await firestore.get_run_state(bundle_id, run_id)
    assert record["state"] == "ERROR", "COMPLETE must not overwrite ERROR"
    refused = [entry for entry in logs if entry["event"] == "run_complete_not_applied"]
    assert len(refused) == 1 and refused[0]["log_level"] == "warning" and refused[0]["run_id"] == run_id


async def _is_error(bundle_id: str, run_id: str) -> bool:
    return (await firestore.get_run_state(bundle_id, run_id)).get("state") == "ERROR"


@pytest.mark.asyncio
async def test_set_run_state_only_if_state_in_memory() -> None:
    await firestore.set_run_stage("bnd-x", "run-1", stage="finalize", progress=0.98)

    assert await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0, only_if_state="ERROR") is False
    assert firestore._IN_MEMORY_RUNS["bnd-x:run-1"]["state"] == "RUNNING"

    assert await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0, only_if_state="RUNNING") is True
    assert firestore._IN_MEMORY_RUNS["bnd-x:run-1"]["state"] == "COMPLETE"

    await firestore.set_run_error("bnd-x", "run-1", error="it broke")
    assert await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0, only_if_state="RUNNING") is False
    assert firestore._IN_MEMORY_RUNS["bnd-x:run-1"]["state"] == "ERROR"


@pytest.mark.asyncio
async def test_set_run_state_without_a_condition_behaves_as_before_and_reports_that_it_applied() -> None:
    assert await firestore.set_run_state("bnd-x", "run-new", state="COMPLETE", progress=1.0) is True
    assert firestore._IN_MEMORY_RUNS["bnd-x:run-new"]["state"] == "COMPLETE"


@pytest.mark.asyncio
async def test_a_conditional_write_to_a_run_that_does_not_exist_is_refused() -> None:
    assert await firestore.set_run_state("bnd-x", "run-ghost", state="COMPLETE", progress=1.0, only_if_state="RUNNING") is False
    assert "bnd-x:run-ghost" not in firestore._IN_MEMORY_RUNS


@pytest.mark.asyncio
async def test_set_run_state_only_if_state_on_firestore(monkeypatch) -> None:
    fake = FakeFirestore()
    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: fake)
    path = ("bundles", "bnd-x", "runs", "run-1")

    assert await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0, only_if_state="RUNNING") is False
    assert path not in fake.docs

    await firestore.set_run_stage("bnd-x", "run-1", stage="finalize", progress=0.98)
    assert await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0, only_if_state="RUNNING") is True
    assert fake.docs[path]["state"] == "COMPLETE" and fake.docs[path]["stage"] == "finalize"  # merged, as before

    await firestore.set_run_error("bnd-x", "run-1", error="it broke")
    assert await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0, only_if_state="RUNNING") is False
    assert fake.docs[path]["state"] == "ERROR"

    assert await firestore.set_run_state("bnd-x", "run-1", state="COMPLETE", progress=1.0) is True  # unconditional


@pytest.mark.asyncio
async def test_fail_run_records_the_error_even_when_the_run_state_cannot_be_read(monkeypatch) -> None:
    from structlog.testing import capture_logs

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id, age=1)

        async def unreadable(_bundle_id: str, _run_id: str | None = None):
            raise OSError("store hiccup")

        monkeypatch.setattr(firestore, "get_run_state", unreadable)
        with capture_logs() as logs:
            await orchestrator._fail_run(
                bundle_id=bundle_id, run_id="run-dead", iteration=1, mode="full", stage="extract", exc=RuntimeError("real"),
            )
        monkeypatch.undo()

        assert (await firestore.get_run_state(bundle_id, "run-dead"))["state"] == "ERROR"
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1
        assert [e["error_type"] for e in logs if e["event"] == "run_state_read_failed"] == ["OSError"]
