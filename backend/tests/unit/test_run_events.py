"""The wake-up channel between the orchestrator (which writes run records) and the SSE streams (which poll them).

``subscribe(bundle_id)`` registers a long-lived listener that remembers the version it has seen, so a change that
happens while the listener is busy (between two waits) is not lost; the module-level ``wait`` is the one-shot form.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import run_events


def settle() -> "asyncio.Future[None]":
    return asyncio.sleep(0)


@pytest.mark.asyncio
async def test_notify_wakes_a_waiter_at_once() -> None:
    with run_events.subscribe("bnd-a") as sub:
        waiter = asyncio.create_task(sub.wait(30))
        await settle()
        assert not waiter.done()

        run_events.notify("bnd-a")
        await asyncio.wait_for(waiter, 1)


@pytest.mark.asyncio
async def test_a_wait_without_a_notify_ends_at_the_timeout() -> None:
    loop = asyncio.get_running_loop()
    with run_events.subscribe("bnd-a") as sub:
        started = loop.time()
        await sub.wait(0.05)
        assert 0.04 <= loop.time() - started < 0.5


@pytest.mark.asyncio
async def test_a_notify_between_two_waits_is_not_lost() -> None:
    with run_events.subscribe("bnd-a") as sub:
        await sub.wait(0.01)  # first wait: times out
        run_events.notify("bnd-a")  # the listener is busy (reading state, sending an event)
        await asyncio.wait_for(sub.wait(30), 1)  # returns at once instead of sleeping 30 s


@pytest.mark.asyncio
async def test_a_change_after_subscribing_but_before_the_first_wait_is_not_lost() -> None:
    with run_events.subscribe("bnd-a") as sub:
        run_events.notify("bnd-a")
        await asyncio.wait_for(sub.wait(30), 1)


@pytest.mark.asyncio
async def test_one_notify_is_consumed_by_one_wait_only() -> None:
    loop = asyncio.get_running_loop()
    with run_events.subscribe("bnd-a") as sub:
        run_events.notify("bnd-a")
        await sub.wait(30)
        started = loop.time()
        await sub.wait(0.05)  # no new change: this one really waits
        assert loop.time() - started >= 0.04


@pytest.mark.asyncio
async def test_several_notifies_while_busy_cost_one_wake_up() -> None:
    with run_events.subscribe("bnd-a") as sub:
        for _ in range(5):
            run_events.notify("bnd-a")
        await sub.wait(30)
        loop = asyncio.get_running_loop()
        started = loop.time()
        await sub.wait(0.05)
        assert loop.time() - started >= 0.04


@pytest.mark.asyncio
async def test_every_subscriber_of_a_bundle_is_woken() -> None:
    with run_events.subscribe("bnd-a") as first, run_events.subscribe("bnd-a") as second:
        waiters = [asyncio.create_task(first.wait(30)), asyncio.create_task(second.wait(30))]
        await settle()

        run_events.notify("bnd-a")

        await asyncio.wait_for(asyncio.gather(*waiters), 1)


@pytest.mark.asyncio
async def test_two_bundles_do_not_wake_each_other() -> None:
    with run_events.subscribe("bnd-a") as a, run_events.subscribe("bnd-b") as b:
        waiter_a = asyncio.create_task(a.wait(30))
        waiter_b = asyncio.create_task(b.wait(30))
        await settle()

        run_events.notify("bnd-b")
        await asyncio.wait_for(waiter_b, 1)
        await settle()
        assert not waiter_a.done()

        run_events.notify("bnd-a")
        await asyncio.wait_for(waiter_a, 1)


@pytest.mark.asyncio
async def test_notifying_a_bundle_nobody_listens_to_is_a_no_op_and_creates_no_entry() -> None:
    run_events.notify("bnd-nobody")

    assert run_events._CHANNELS == {}


@pytest.mark.asyncio
async def test_a_subscriber_that_arrives_late_is_not_woken_by_old_changes() -> None:
    loop = asyncio.get_running_loop()
    run_events.notify("bnd-a")
    with run_events.subscribe("bnd-a") as sub:
        started = loop.time()
        await sub.wait(0.05)
        assert loop.time() - started >= 0.04


@pytest.mark.asyncio
async def test_no_entries_remain_after_all_waiters_finish() -> None:
    first, second = run_events.subscribe("bnd-a"), run_events.subscribe("bnd-b")
    waiters = [asyncio.create_task(first.wait(30)), asyncio.create_task(second.wait(30))]
    await settle()
    assert set(run_events._CHANNELS) == {"bnd-a", "bnd-b"}

    run_events.notify("bnd-a")
    run_events.notify("bnd-b")
    await asyncio.gather(*waiters)
    first.close()
    assert set(run_events._CHANNELS) == {"bnd-b"}, "an entry goes with its last subscriber"
    second.close()

    assert run_events._CHANNELS == {}


@pytest.mark.asyncio
async def test_closing_twice_is_harmless_and_a_closed_subscription_cannot_leak_an_entry() -> None:
    sub = run_events.subscribe("bnd-a")
    sub.close()
    sub.close()

    assert run_events._CHANNELS == {}


@pytest.mark.asyncio
async def test_a_cancelled_waiter_leaves_nothing_behind() -> None:
    with run_events.subscribe("bnd-a") as sub:
        waiter = asyncio.create_task(sub.wait(30))
        await settle()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert sub._future is None

    assert run_events._CHANNELS == {}


@pytest.mark.asyncio
async def test_the_module_level_wait_is_one_shot_and_leaves_no_entry() -> None:
    waiter = asyncio.create_task(run_events.wait("bnd-a", 30))
    await settle()
    assert "bnd-a" in run_events._CHANNELS

    run_events.notify("bnd-a")
    await asyncio.wait_for(waiter, 1)

    assert run_events._CHANNELS == {}


@pytest.mark.asyncio
async def test_the_module_level_wait_times_out_and_leaves_no_entry() -> None:
    await run_events.wait("bnd-a", 0.02)

    assert run_events._CHANNELS == {}


@pytest.mark.asyncio
async def test_a_leaked_registry_never_survives_into_the_next_test() -> None:
    # conftest clears the registry; a subscription that nobody closed must not affect this test
    assert run_events._CHANNELS == {}


# ---------------------------------------------------------------------------
# who notifies, and who listens
# ---------------------------------------------------------------------------

FILES = {"commercial_invoice.pdf": b"%PDF-1.4 events invoice"}


def record_writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Log every run-record / iteration write and every notify, in order."""
    from app.repo import firestore

    log: list[str] = []
    for name in ("set_run_stage", "set_run_state", "set_run_error", "write_iteration"):
        real = getattr(firestore, name)

        async def spy(*args, __real=real, __name=name, **kwargs):
            result = await __real(*args, **kwargs)
            log.append(f"write:{__name}")
            return result

        monkeypatch.setattr(firestore, name, spy)
    real_notify = run_events.notify
    monkeypatch.setattr(run_events, "notify", lambda bundle_id: (log.append("notify"), real_notify(bundle_id))[1])
    return log


def assert_every_write_is_announced(log: list[str]) -> None:
    for index, entry in enumerate(log):
        if entry.startswith("write:"):
            assert log[index + 1 : index + 2] == ["notify"], f"{entry} was not followed by a notify: {log}"


@pytest.mark.asyncio
async def test_a_successful_run_notifies_after_every_record_write_and_after_the_iteration(monkeypatch) -> None:
    from app.services import orchestrator
    from tests.helpers import api_client, create_bundle_with_documents, wait_for_run

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        log = record_writes(monkeypatch)

        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"

    assert_every_write_is_announced(log)
    kinds = [entry for entry in log if entry.startswith("write:")]
    # claim + 6 stages + finalize, the iteration, and the terminal state
    assert kinds.count("write:set_run_stage") == 8 and kinds.count("write:write_iteration") == 1
    assert kinds[-1] == "write:set_run_state"


@pytest.mark.asyncio
async def test_a_failed_run_notifies_after_marking_the_error(monkeypatch) -> None:
    from app.services import orchestrator
    from tests.helpers import api_client, create_bundle_with_documents, wait_for_run

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        real_dispatch = orchestrator.dispatch

        async def broken(stage, ctx):
            if stage == "extract":
                raise RuntimeError("boom")
            return await real_dispatch(stage, ctx)

        monkeypatch.setattr(orchestrator, "dispatch", broken)
        log = record_writes(monkeypatch)
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "ERROR"

    assert_every_write_is_announced(log)
    assert "write:set_run_error" in log


@pytest.mark.asyncio
async def test_reaping_a_dead_run_notifies(monkeypatch) -> None:
    from app.services import orchestrator
    from tests.helpers import api_client, create_bundle_with_documents
    from tests.unit.test_run_lifecycle import seed_dead_run

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        await seed_dead_run(bundle_id)
        log = record_writes(monkeypatch)

        assert await orchestrator.reap_stale(bundle_id) is True

    assert_every_write_is_announced(log)
    assert log[:2] == ["write:set_run_error", "notify"]


@pytest.mark.asyncio
async def test_a_stream_unsubscribes_when_it_ends(monkeypatch) -> None:
    from app.api.v1 import stream
    from app.core.config import settings

    monkeypatch.setattr(settings, "stream_poll_idle_seconds", 30)

    async def consume() -> None:
        async for _ in stream.event_stream("bnd-x"):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    assert set(run_events._CHANNELS) == {"bnd-x"}

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert run_events._CHANNELS == {}
