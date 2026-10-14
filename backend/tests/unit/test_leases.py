"""Run leases (repo/leases.py): the claim on a bundle, its fencing, and what happens when contenders collide.

Every behaviour is checked against BOTH stores: the in-memory one (demo mode) and the Firestore one, run on a fake client with
real optimistic-transaction semantics (an interleaved commit is refused with Aborted and retried), so the transaction code
paths are exercised, not just the decisions.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.repo import firestore, leases
from app.repo.leases import LeaseHeld, LeaseLost
from tests.unit.firestore_fakes import FakeFirestore, fake_async_transactional

T0 = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture(params=["memory", "firestore"])
def store(request, monkeypatch):
    """The store under test; ``store.docs`` is the Firestore fake (None for the in-memory store)."""
    clock = Clock()
    monkeypatch.setattr(leases, "_now", clock)
    fake = None
    if request.param == "firestore":
        fake = FakeFirestore()
        monkeypatch.setattr(firestore, "_firestore_client", fake)
        monkeypatch.setattr(leases, "async_transactional", fake_async_transactional)

    class Handle:
        kind = request.param
        firestore = fake

        def advance(self, seconds: float) -> None:
            clock.advance(seconds)

    return Handle()


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_bundle_is_claimed_once_while_the_lease_is_alive(store) -> None:
    first = await leases.claim("b1", run_id="run-1", mode="full", owner="inst-a", iteration=1)
    assert first.superseded is None
    assert (first.lease.run_id, first.lease.state, first.lease.fence, first.lease.owner) == ("run-1", "RUNNING", 1, "inst-a")

    with pytest.raises(LeaseHeld) as held:
        await leases.claim("b1", run_id="run-2", mode="reassess", owner="inst-b")
    assert held.value.lease.run_id == "run-1"

    assert (await leases.read("b1")).run_id == "run-1"
    assert await leases.read("other-bundle") is None, "leases are per bundle"
    other = await leases.claim("b2", run_id="run-3", mode="full", owner="inst-b")
    assert other.lease.run_id == "run-3"


@pytest.mark.asyncio
async def test_an_expired_lease_is_replaced_and_handed_back_as_superseded(store) -> None:
    await leases.claim("b1", run_id="run-1", mode="full", owner="inst-a", ttl=90)
    store.advance(89)
    with pytest.raises(LeaseHeld):
        await leases.claim("b1", run_id="run-2", mode="full", owner="inst-b")
    store.advance(2)

    taken = await leases.claim("b1", run_id="run-2", mode="full", owner="inst-b", ttl=90)
    assert taken.lease.run_id == "run-2" and taken.superseded is not None and taken.superseded.run_id == "run-1"
    assert taken.lease.fence == taken.superseded.fence + 1, "the fence keeps counting across runs of one bundle"


@pytest.mark.asyncio
async def test_simultaneous_claims_yield_exactly_one_winner_across_instances(store) -> None:
    """Twelve contenders at once. On Firestore each reads 'no lease' and all but one commit are refused (Aborted) and retried."""
    results = await asyncio.gather(
        *[leases.claim("b1", run_id=f"run-{n}", mode="full", owner=f"inst-{n}") for n in range(12)], return_exceptions=True
    )
    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, LeaseHeld)]
    assert len(winners) == 1 and len(losers) == 11, [type(r).__name__ for r in results]
    assert (await leases.read("b1")).run_id == winners[0].lease.run_id
    assert all(r.lease.run_id == winners[0].lease.run_id for r in losers), "everybody is told who holds it"


# ---------------------------------------------------------------------------
# queued -> running (a worker picks the run up)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_queued_run_is_acquired_by_exactly_one_worker(store) -> None:
    queued = await leases.claim("b1", run_id="run-1", mode="reassess", state="QUEUED", iteration=3)
    assert (queued.lease.state, queued.lease.owner, queued.lease.fence) == ("QUEUED", None, 0)
    assert queued.lease.iteration == 3 and queued.lease.mode == "reassess", "the lease carries what the worker needs"

    results = await asyncio.gather(
        *[leases.acquire("b1", "run-1", owner=f"worker-{n}") for n in range(5)], return_exceptions=True
    )
    won = [r for r in results if not isinstance(r, BaseException)]
    assert len(won) == 1 and sum(isinstance(r, LeaseHeld) for r in results) == 4
    lease, taken_over = won[0]
    assert (lease.state, lease.fence, taken_over) == ("RUNNING", 1, False) and lease.owner.startswith("worker-")
    assert lease.iteration == 3 and lease.mode == "reassess"


@pytest.mark.asyncio
async def test_a_queued_run_that_nobody_picks_up_in_time_can_be_reaped(store) -> None:
    await leases.claim("b1", run_id="run-1", mode="full", state="QUEUED", ttl=900)
    store.advance(899)
    assert await leases.reap_expired("b1") is None
    store.advance(2)
    reaped = await leases.reap_expired("b1")
    assert reaped is not None and reaped.run_id == "run-1" and reaped.state == "QUEUED"
    assert await leases.read("b1") is None


@pytest.mark.asyncio
async def test_a_dead_executor_is_taken_over_when_the_task_is_delivered_again(store) -> None:
    await leases.claim("b1", run_id="run-1", mode="full", state="QUEUED", iteration=2)
    first, _ = await leases.acquire("b1", "run-1", owner="worker-a", ttl=90)

    with pytest.raises(LeaseHeld):  # the first worker is alive: a duplicate delivery must not start a second execution
        await leases.acquire("b1", "run-1", owner="worker-b", ttl=90)

    store.advance(91)  # worker-a died: no heartbeat
    second, taken_over = await leases.acquire("b1", "run-1", owner="worker-b", ttl=90)
    assert taken_over is True and second.fence == first.fence + 1 and second.owner == "worker-b" and second.iteration == 2

    with pytest.raises(LeaseLost):  # the old executor wakes up: its fence is out of date
        await leases.heartbeat("b1", "run-1", first.fence)
    with pytest.raises(LeaseLost):
        await leases.verify("b1", "run-1", first.fence)
    await leases.verify("b1", "run-1", second.fence)


@pytest.mark.asyncio
async def test_a_task_for_a_run_that_no_longer_owns_the_bundle_is_obsolete(store) -> None:
    with pytest.raises(LeaseLost):  # no lease at all (the run was reaped)
        await leases.acquire("b1", "run-1", owner="w")
    await leases.claim("b1", run_id="run-2", mode="full", owner="x")
    with pytest.raises(LeaseLost):  # another run holds it
        await leases.acquire("b1", "run-1", owner="w")


# ---------------------------------------------------------------------------
# heartbeat, update, release
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_execution_can_expire_its_own_lease_so_the_next_delivery_takes_over(store) -> None:
    await leases.claim("b1", run_id="run-1", mode="full", state=leases.QUEUED, ttl=90)
    lease, _ = await leases.acquire("b1", "run-1", owner="a", ttl=90)

    with pytest.raises(LeaseLost):
        await leases.expire("b1", "run-1", lease.fence + 1)  # not the owner: refused
    assert not (await leases.read("b1")).expired()

    await leases.expire("b1", "run-1", lease.fence)
    assert (await leases.read("b1")).expired(), "expired now, not in 90 seconds"
    taken, taken_over = await leases.acquire("b1", "run-1", owner="b", ttl=90)
    assert taken_over and taken.fence == lease.fence + 1 and taken.owner == "b"


@pytest.mark.asyncio
async def test_a_heartbeat_extends_the_lease_only_for_the_owning_execution(store) -> None:
    claim = await leases.claim("b1", run_id="run-1", mode="full", owner="a", ttl=90)
    fence = claim.lease.fence
    store.advance(80)
    extended = await leases.heartbeat("b1", "run-1", fence, ttl=90)
    store.advance(80)  # 160 s after the claim: alive only because of the heartbeat
    assert extended.heartbeat_at > claim.lease.heartbeat_at
    assert await leases.reap_expired("b1") is None

    for wrong in (dict(run_id="run-2", fence=fence), dict(run_id="run-1", fence=fence + 1)):
        with pytest.raises(LeaseLost):
            await leases.heartbeat("b1", **wrong)
    store.advance(100)
    assert (await leases.reap_expired("b1")).run_id == "run-1"
    with pytest.raises(LeaseLost):
        await leases.heartbeat("b1", "run-1", fence)


@pytest.mark.asyncio
async def test_update_changes_fields_of_an_owned_lease_and_nothing_else(store) -> None:
    claim = await leases.claim("b1", run_id="run-1", mode="full", owner="a")
    updated = await leases.update("b1", "run-1", claim.lease.fence, iteration=5)
    assert updated.iteration == 5 and updated.run_id == "run-1" and updated.owner == "a"
    assert (await leases.read("b1")).iteration == 5
    with pytest.raises(LeaseLost):
        await leases.update("b1", "run-1", claim.lease.fence + 1, iteration=9)


@pytest.mark.asyncio
async def test_release_deletes_only_the_callers_lease(store) -> None:
    claim = await leases.claim("b1", run_id="run-1", mode="full", owner="a")
    assert await leases.release("b1", "run-2") is False and await leases.release("b1", "run-1", claim.lease.fence + 1) is False
    assert await leases.read("b1") is not None, "a stranger's release changes nothing"
    assert await leases.release("b1", "run-1", claim.lease.fence) is True
    assert await leases.read("b1") is None
    assert await leases.release("b1", "run-1") is False, "releasing twice is harmless"
    assert (await leases.claim("b1", run_id="run-2", mode="full", owner="b")).lease.run_id == "run-2", "the bundle is free again"


@pytest.mark.asyncio
async def test_exactly_one_reaper_gets_the_dead_run(store) -> None:
    await leases.claim("b1", run_id="run-1", mode="full", owner="a", ttl=90)
    store.advance(120)
    results = await asyncio.gather(*[leases.reap_expired("b1") for _ in range(8)])
    assert [r.run_id for r in results if r is not None] == ["run-1"], "one of eight reapers audits the failure, the rest see nothing"


# ---------------------------------------------------------------------------
# fenced writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fenced_write_happens_only_while_the_lease_is_owned(store) -> None:
    claim = await leases.claim("b1", run_id="run-1", mode="full", owner="a")
    fence = claim.lease.fence
    done: list[str] = []

    async def work(transaction) -> str:
        done.append("kind=" + ("memory" if transaction is None else "transaction"))
        return "written"

    assert await leases.fenced_transaction("b1", "run-1", fence, work) == "written"
    assert done == [f"kind={'memory' if store.kind == 'memory' else 'transaction'}"]

    with pytest.raises(LeaseLost):
        await leases.fenced_transaction("b1", "run-1", fence + 1, work)
    with pytest.raises(LeaseLost):
        await leases.fenced_transaction("b1", "run-9", fence, work)
    assert len(done) == 1, "a refused write never reaches its work"

    assert await leases.fenced_transaction("b1", "run-1", fence, work, release_after=True) == "written"
    assert await leases.read("b1") is None, "the terminal write releases the lease in the same step"


@pytest.mark.asyncio
async def test_a_take_over_between_the_check_and_the_commit_refuses_the_stale_write() -> None:
    """The firestore-only race that fencing exists for: the executor passed the check, then lost the lease before it committed."""
    clock = Clock()
    fake = FakeFirestore()
    import app.repo.leases as module

    original = (module._now, firestore._firestore_client, module.async_transactional)
    module._now, firestore._firestore_client, module.async_transactional = clock, fake, fake_async_transactional
    try:
        claim = await module.claim("b1", run_id="run-1", mode="full", state="QUEUED")
        first, _ = await module.acquire("b1", "run-1", owner="old", ttl=90)
        writes: list[str] = []

        async def slow_work(transaction) -> None:
            writes.append("buffered")
            clock.advance(100)  # the executor stalls past its lease...
            await module.acquire("b1", "run-1", owner="new", ttl=90)  # ...and a worker takes the run over meanwhile
            transaction.set(fake.collection("bundles").document("b1").collection("iterations").document("1"), {"by": "old"})

        with pytest.raises(LeaseLost):
            await module.fenced_transaction("b1", "run-1", first.fence, slow_work)
        assert ("bundles", "b1", "iterations", "1") not in fake.docs, "the stale executor's write never landed"
        assert writes == ["buffered"], "the commit was refused (Aborted); the retry stopped at the fence check, before any work"
        assert claim.lease.state == "QUEUED"
    finally:
        module._now, firestore._firestore_client, module.async_transactional = original


# ---------------------------------------------------------------------------
# the pure decisions, and robustness
# ---------------------------------------------------------------------------


def test_an_unreadable_expiry_cannot_prove_anybody_is_alive() -> None:
    lease = leases.Lease.from_dict({"run_id": "r", "expires_at": "not a time"})
    assert lease.expired() is True
    assert leases.Lease.from_dict({"run_id": "r", "expires_at": "2999-01-01T00:00:00"}).expired() is False, "a naive time is read as UTC"


def test_a_lease_round_trips_through_its_dict() -> None:
    lease = leases.Lease("r", "RUNNING", "recompute", 4, "w", 2, "a", "b", "c")
    assert leases.Lease.from_dict(lease.to_dict()) == lease
    assert leases.Lease.from_dict({"run_id": "r"}).state == "RUNNING", "a minimal record still loads"


def test_the_instance_identity_is_stable_and_names_the_process() -> None:
    assert leases.INSTANCE_ID == leases.INSTANCE_ID and str(__import__("os").getpid()) in leases.INSTANCE_ID


# ---------------------------------------------------------------------------
# the fenced run-state write on Firestore: a retried transaction reports only what the committed attempt did
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_retried_terminal_write_does_not_report_what_an_aborted_attempt_buffered(monkeypatch) -> None:
    fake = FakeFirestore()
    monkeypatch.setattr(firestore, "_firestore_client", fake)
    monkeypatch.setattr(leases, "async_transactional", fake_async_transactional)
    claim = await leases.claim("b1", run_id="run-1", mode="full", owner="a", iteration=1)
    await firestore.set_run_stage("b1", "run-1", "extract", 0.4)  # the record says RUNNING

    from tests.unit import firestore_fakes

    real_commit = firestore_fakes.FakeTransaction.commit
    attempts = {"n": 0}

    async def commit_after_the_reaper_wrote_ERROR(self) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:  # between this attempt's read and its commit another writer finished the run
            await firestore.set_run_error("b1", "run-1", error="interrupted")
        await real_commit(self)

    monkeypatch.setattr(firestore_fakes.FakeTransaction, "commit", commit_after_the_reaper_wrote_ERROR)
    applied = await firestore.set_run_state(
        "b1", "run-1", state="COMPLETE", progress=1.0, only_if_state="RUNNING", fence=claim.lease.fence
    )

    assert attempts["n"] >= 2, "the first commit was refused (Aborted) and the transaction ran again"
    assert applied is False, "the retry saw ERROR and wrote nothing: it must not say COMPLETE was applied"
    assert (await firestore.get_run_state("b1", "run-1"))["state"] == "ERROR"


@pytest.mark.asyncio
async def test_an_uncontended_terminal_write_on_firestore_is_applied_and_releases_the_lease(monkeypatch) -> None:
    fake = FakeFirestore()
    monkeypatch.setattr(firestore, "_firestore_client", fake)
    monkeypatch.setattr(leases, "async_transactional", fake_async_transactional)
    claim = await leases.claim("b1", run_id="run-1", mode="full", owner="a", iteration=1)
    await firestore.set_run_stage("b1", "run-1", "extract", 0.4)

    assert await firestore.set_run_state("b1", "run-1", state="COMPLETE", progress=1.0, only_if_state="RUNNING", fence=claim.lease.fence)
    assert (await firestore.get_run_state("b1", "run-1"))["state"] == "COMPLETE"
    assert await leases.read("b1") is None
