"""Runs across API instances: the lease claim, fencing of a stale executor, and the Cloud Tasks (queued) dispatch.

"Another instance" is simulated by writing to the lease store directly, exactly as a second API process would through
Firestore; the lease store itself is tested (against Firestore transactions too) in test_leases.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.config import settings
from app.gateway.errors import ConflictError, UpstreamError
from app.repo import firestore, leases
from app.services import audit, orchestrator, run_queue
from tests.helpers import api_client, create_bundle_with_documents, wait_for_run
from tests.unit.test_run_lifecycle import FILES, events_of, explode, stall, wait_until


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(leases, "_now", c)
    return c


@pytest.fixture
def queued(monkeypatch) -> list[tuple[str, str]]:
    """RUN_DISPATCH=cloudtasks with a queue that just records what was enqueued."""
    monkeypatch.setattr(settings, "run_dispatch", "cloudtasks")
    sent: list[tuple[str, str]] = []

    async def enqueue(bundle_id: str, run_id: str) -> None:
        sent.append((bundle_id, run_id))

    monkeypatch.setattr(run_queue, "enqueue", enqueue)
    return sent


# ---------------------------------------------------------------------------
# local dispatch: the lease is claimed, fenced and released
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_holds_the_lease_while_it_runs_and_releases_it_when_it_completes(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        stall(monkeypatch, "extract", 0.2)
        run_id = await orchestrator.start_run(bundle_id)

        lease = await leases.read(bundle_id)
        assert lease is not None and (lease.run_id, lease.state, lease.fence, lease.iteration, lease.mode) == (run_id, "RUNNING", 1, 1, "full")
        assert lease.owner == leases.INSTANCE_ID

        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"
        assert await leases.read(bundle_id) is None, "the terminal write released the lease in the same step"
        second = await orchestrator.start_run(bundle_id, mode="reassess")  # and the bundle is free again
        assert (await leases.read(bundle_id)).iteration == 2
        await wait_for_run(bundle_id, second)


@pytest.mark.asyncio
async def test_a_failed_run_releases_the_lease(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "extract", RuntimeError("boom"))
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "ERROR"
        assert await leases.read(bundle_id) is None


@pytest.mark.asyncio
async def test_a_run_started_on_another_instance_blocks_this_one_with_a_409_naming_it() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await leases.claim(bundle_id, run_id="run-elsewhere", mode="full", owner="other-instance", iteration=1)

        with pytest.raises(ConflictError) as refused:
            await orchestrator.start_run(bundle_id)
        assert refused.value.detail == {"run_id": "run-elsewhere"}
        assert (await leases.read(bundle_id)).run_id == "run-elsewhere", "the refused start changed nothing"
        assert firestore._IN_MEMORY_RUNS == {}, "and wrote no run record"


@pytest.mark.asyncio
async def test_a_refused_start_never_leaves_a_lease_behind(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        with pytest.raises(ConflictError):  # a recompute with nothing to reuse: refused AFTER the claim, so the claim is released
            await orchestrator.start_run(bundle_id, mode="recompute")
        assert await leases.read(bundle_id) is None


@pytest.mark.asyncio
async def test_a_dead_instances_lease_is_reaped_once_and_the_new_run_proceeds(clock) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await audit.record({"bundle_id": bundle_id, "iteration": 1, "audit_event_type": "ANALYSIS_STARTED",
                            "audit_payload": {"run_id": "run-dead", "mode": "full", "document_ids": []}, "actor": "system"})
        await firestore.set_run_stage(bundle_id, "run-dead", stage="extract", progress=0.4)
        await leases.claim(bundle_id, run_id="run-dead", mode="full", owner="crashed-instance", iteration=1, ttl=90)

        with pytest.raises(ConflictError):
            await orchestrator.start_run(bundle_id)  # alive: it is within its lease
        clock.advance(120)  # no heartbeat for two minutes: the instance is gone

        run_id = await orchestrator.start_run(bundle_id)
        assert run_id != "run-dead" and (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"
        failed = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert [(e["payload"]["run_id"], e["payload"]["reason"], e["payload"]["mode"]) for e in failed] == [("run-dead", "interrupted", "full")]
        assert (await firestore.get_run_state(bundle_id, "run-dead"))["state"] == "ERROR"


@pytest.mark.asyncio
async def test_several_instances_reaping_one_dead_run_write_one_audit_event(clock) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await firestore.set_run_stage(bundle_id, "run-dead", stage="extract", progress=0.4)
        await leases.claim(bundle_id, run_id="run-dead", mode="reassess", owner="gone", iteration=4, ttl=90)
        clock.advance(300)

        # the in-process reap lock is per process: bypass it, as several processes would, to prove the LEASE is what decides
        orchestrator._REAP_LOCKS.clear()

        class NoLock:
            async def __aenter__(self) -> None: ...
            async def __aexit__(self, *exc: Any) -> None: ...

        monkey = pytest.MonkeyPatch()
        monkey.setattr(orchestrator, "_lock", lambda registry, bundle_id: NoLock())
        try:
            results = await asyncio.gather(*[orchestrator.reap_stale(bundle_id) for _ in range(6)])
        finally:
            monkey.undo()
        assert results.count(True) == 1
        [event] = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert (event["iteration"], event["payload"]["mode"]) == (4, "reassess"), "the lease knows what the audit event needs"


# ---------------------------------------------------------------------------
# fencing: an executor that lost the bundle cannot write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_executor_taken_over_mid_run_stops_and_writes_nothing(monkeypatch) -> None:
    """The stale executor must not touch ANYTHING that now belongs to the run's new executor: not the iteration, not the lease,
    and not the run record or the audit trail (the take-over keeps the same run id, so a failure written under it would kill
    the healthy run)."""
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

        real = orchestrator.dispatch
        gate = asyncio.Event()

        async def dispatch(name: str, ctx: dict[str, Any]) -> dict[str, Any]:
            if name == "extract":
                gate.set()
                await asyncio.sleep(0.2)
            return await real(name, ctx)

        monkeypatch.setattr(orchestrator, "dispatch", dispatch)
        run_id = await orchestrator.start_run(bundle_id)
        await gate.wait()
        # another executor takes the same run over: the fence moves on (and it is RUNNING the run: its record says so)
        stored = leases._MEMORY[bundle_id]
        stored["fence"] += 1
        stored["owner"] = "the-new-executor"

        await asyncio.gather(*[t for t in orchestrator._RUNNING_TASKS if not t.done()])  # the stale executor notices and ends

        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "RUNNING", "the new executor's run was not marked failed"
        assert await firestore.list_iterations(bundle_id) == [], "the stale executor wrote no iteration"
        assert (await leases.read(bundle_id)).owner == "the-new-executor", "and its failure handling did not release the new owner's lease"
        assert not await events_of(client, bundle_id, "ANALYSIS_FAILED"), "nor did it write a failure into the shared audit trail"
        assert not await events_of(client, bundle_id, "ASSESSMENT_COMPLETED")


@pytest.mark.asyncio
async def test_an_executor_whose_run_was_reaped_leaves_the_single_failure_the_reaper_wrote(monkeypatch, clock) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        real = orchestrator.dispatch
        gate = asyncio.Event()

        async def dispatch(name: str, ctx: dict[str, Any]) -> dict[str, Any]:
            if name == "extract":
                gate.set()
                await asyncio.sleep(0.2)
            return await real(name, ctx)

        monkeypatch.setattr(orchestrator, "dispatch", dispatch)
        run_id = await orchestrator.start_run(bundle_id)
        await gate.wait()
        clock.advance(settings.run_stale_after_seconds + 1)  # its lease expires while it is paused
        assert await orchestrator.reap_stale(bundle_id) is True

        await asyncio.gather(*[t for t in orchestrator._RUNNING_TASKS if not t.done()])
        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "ERROR"
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1


@pytest.mark.asyncio
async def test_an_executor_that_still_owns_its_lease_records_its_own_failure(monkeypatch) -> None:
    """The control for the two tests above: the failure path still records the failure when the lease is ours."""
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        explode(monkeypatch, "extract", RuntimeError("boom"))
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "ERROR"
        assert len(await events_of(client, bundle_id, "ANALYSIS_FAILED")) == 1
        assert await leases.read(bundle_id) is None


@pytest.mark.asyncio
async def test_the_iteration_write_and_the_terminal_write_are_refused_without_the_fence() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        claim = await leases.claim(bundle_id, run_id="run-1", mode="full", owner="a", iteration=1)
        ctx = {"bundle_id": bundle_id, "run_id": "run-1", "iteration": 1, "fence": claim.lease.fence + 1, "final_status": "X"}
        with pytest.raises(leases.LeaseLost):
            await firestore.write_iteration(ctx)
        assert await firestore.list_iterations(bundle_id) == []
        with pytest.raises(leases.LeaseLost):
            await firestore.set_run_state(bundle_id, "run-1", state="COMPLETE", progress=1.0, only_if_state="RUNNING", fence=claim.lease.fence + 1)

        ctx["fence"] = claim.lease.fence
        written = await firestore.write_iteration(ctx)
        assert written["iteration"] == 1 and len(await firestore.list_iterations(bundle_id)) == 1


@pytest.mark.asyncio
async def test_the_heartbeat_extends_the_lease_and_stops_when_the_lease_is_lost(monkeypatch) -> None:
    monkeypatch.setattr(settings, "run_heartbeat_seconds", 0.02)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        claim = await leases.claim(bundle_id, run_id="run-1", mode="full", owner="a", iteration=1)
        await firestore.set_run_stage(bundle_id, "run-1", stage="extract", progress=0.4)
        before = (await leases.read(bundle_id)).heartbeat_at

        beat = asyncio.create_task(orchestrator._heartbeat(bundle_id, "run-1", claim.lease.fence))
        await wait_until(lambda: _heartbeat_moved(bundle_id, before))
        assert not beat.done()

        leases._MEMORY[bundle_id]["fence"] += 1  # taken over
        await asyncio.wait_for(beat, 1.0)  # the heartbeat gives up by itself: it must not keep a dead claim alive


async def _heartbeat_moved(bundle_id: str, before: str) -> bool:
    return (await leases.read(bundle_id)).heartbeat_at != before


# ---------------------------------------------------------------------------
# cloudtasks dispatch: queued, picked up by a worker, duplicated, taken over
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_dispatched_run_is_queued_with_a_lease_and_one_task(queued) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id, mode="full")

        assert queued == [(bundle_id, run_id)]
        lease = await leases.read(bundle_id)
        assert (lease.state, lease.owner, lease.iteration, lease.mode, lease.fence) == ("QUEUED", None, 1, "full", 0)
        record = await firestore.get_run_state(bundle_id, run_id)
        assert (record["state"], record["stage"]) == ("QUEUED", "queued")
        assert not [t for t in orchestrator._RUNNING_TASKS if not t.done()], "nothing runs in this process: a worker will"
        assert orchestrator._starting_runs == 0

        with pytest.raises(ConflictError):  # a second analyze while queued is refused like one while running
            await orchestrator.start_run(bundle_id)
        assert len(queued) == 1


@pytest.mark.asyncio
async def test_a_worker_executes_the_queued_run_inside_its_request(queued) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)

        assert await orchestrator.execute_queued(bundle_id, run_id) == "done"
        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "COMPLETE", "complete by the time the request returns"
        assert await leases.read(bundle_id) is None
        iteration = await firestore.latest_iteration(bundle_id)
        assert iteration["iteration"] == 1 and iteration["run_mode"] == "full"
        started = await events_of(client, bundle_id, "ANALYSIS_STARTED")
        assert [e["payload"]["attempt"] for e in started] == [1]

        assert await orchestrator.execute_queued(bundle_id, run_id) == "obsolete", "a task delivered again after the run ended does nothing"
        assert len(await firestore.list_iterations(bundle_id)) == 1


@pytest.mark.asyncio
async def test_a_duplicate_delivery_while_the_run_is_executing_is_busy(queued, monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        stall(monkeypatch, "extract", 0.2)

        first = asyncio.create_task(orchestrator.execute_queued(bundle_id, run_id))
        await wait_until(lambda: _is_running(bundle_id))
        assert await orchestrator.execute_queued(bundle_id, run_id) == "busy"
        assert await first == "done"
        assert len(await firestore.list_iterations(bundle_id)) == 1, "one execution, one iteration"


@pytest.mark.asyncio
async def test_a_worker_that_fails_before_any_stage_hands_the_run_to_the_next_delivery(queued, monkeypatch) -> None:
    """A store that hiccups right after the lease was acquired is not the run's fault: the worker answers an error (Cloud Tasks
    delivers again) and its lease counts as expired at once, so the next delivery takes the run over instead of being told "busy"."""
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)

        real = firestore.latest_iteration
        calls = {"n": 0}

        async def flaky(bundle: str) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("the database hiccuped")
            return await real(bundle)

        monkeypatch.setattr(firestore, "latest_iteration", flaky)
        with pytest.raises(RuntimeError, match="hiccuped"):
            await orchestrator.execute_queued(bundle_id, run_id)
        lease = await leases.read(bundle_id)
        assert lease is not None and lease.expired(), "the lease was handed back, not left to run out"
        assert not await events_of(client, bundle_id, "ANALYSIS_FAILED"), "a transient fault is not a failed run"

        assert await orchestrator.execute_queued(bundle_id, run_id) == "done", "the next delivery takes it over at once"
        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "COMPLETE"
        assert len(await firestore.list_iterations(bundle_id)) == 1
        started = await events_of(client, bundle_id, "ANALYSIS_STARTED")
        assert [e["payload"]["attempt"] for e in started] == [2], "fence 2: the second execution of the run"


async def _is_running(bundle_id: str) -> bool:
    lease = await leases.read(bundle_id)
    return lease is not None and lease.state == "RUNNING"


@pytest.mark.asyncio
async def test_a_dead_workers_run_is_taken_over_when_the_task_comes_again(queued, clock) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)

        crashed, _ = await leases.acquire(bundle_id, run_id, owner="worker-that-died")  # it took the run, then the instance was killed
        assert await orchestrator.execute_queued(bundle_id, run_id) == "busy", "while its lease is alive nobody else may run it"
        clock.advance(settings.run_stale_after_seconds + 10)

        assert await orchestrator.execute_queued(bundle_id, run_id) == "done"
        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "COMPLETE"
        started = await events_of(client, bundle_id, "ANALYSIS_STARTED")
        assert [e["payload"]["attempt"] for e in started] == [crashed.fence + 1], "the audit says this is a later attempt"
        assert len(await firestore.list_iterations(bundle_id)) == 1


@pytest.mark.asyncio
async def test_a_run_nobody_picks_up_in_time_is_failed_not_left_queued_forever(queued, clock) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        clock.advance(settings.run_queue_wait_seconds + 5)

        assert await orchestrator.reap_stale(bundle_id) is True
        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "ERROR"
        [event] = await events_of(client, bundle_id, "ANALYSIS_FAILED")
        assert event["payload"]["run_id"] == run_id and event["payload"]["reason"] == "interrupted" and event["iteration"] == 1
        assert await orchestrator.execute_queued(bundle_id, run_id) == "obsolete", "and the late task is ignored"
        assert await orchestrator.reap_stale(bundle_id) is False


@pytest.mark.asyncio
async def test_a_queue_that_refuses_the_task_fails_the_request_and_frees_the_bundle(monkeypatch) -> None:
    monkeypatch.setattr(settings, "run_dispatch", "cloudtasks")

    async def refuse(bundle_id: str, run_id: str) -> None:
        raise UpstreamError("The run could not be queued. Try again shortly.")

    monkeypatch.setattr(run_queue, "enqueue", refuse)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        with pytest.raises(UpstreamError):
            await orchestrator.start_run(bundle_id)
        assert await leases.read(bundle_id) is None
        [record] = list(firestore._IN_MEMORY_RUNS.values())
        assert record["state"] == "ERROR", "no run is left QUEUED for a task that does not exist"
        assert orchestrator._starting_runs == 0


@pytest.mark.asyncio
async def test_shutting_down_stops_a_dispatched_run_without_failing_it(queued, monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        stall(monkeypatch, "extract", 5)

        worker = asyncio.create_task(orchestrator.execute_queued(bundle_id, run_id))
        await wait_until(lambda: _is_running(bundle_id))
        await orchestrator.shutdown(timeout=2)
        with pytest.raises(asyncio.CancelledError):
            await worker

        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "RUNNING", "not failed: Cloud Tasks will deliver it again"
        assert await leases.read(bundle_id) is not None
        assert not await events_of(client, bundle_id, "ANALYSIS_FAILED")


@pytest.mark.asyncio
async def test_a_recompute_that_waited_in_the_queue_is_refused_if_a_document_arrived_meanwhile(queued) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        monkey_dispatch = settings.run_dispatch
        settings.run_dispatch = "local"
        try:
            first = await orchestrator.start_run(bundle_id)
            await wait_for_run(bundle_id, first)
        finally:
            settings.run_dispatch = monkey_dispatch
        run_id = await orchestrator.start_run(bundle_id, mode="recompute")  # accepted: nothing changed yet
        await client.post(f"/api/v1/bundles/{bundle_id}/documents", files={"file": ("extra.pdf", b"%PDF-1.4 extra document", "application/pdf")})

        assert await orchestrator.execute_queued(bundle_id, run_id) == "done"
        record = await firestore.get_run_state(bundle_id, run_id)
        assert record["state"] == "ERROR" and "Reassess" in record["message"]
        assert await leases.read(bundle_id) is None
