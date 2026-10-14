"""The transactional code against a REAL Firestore (the emulator): leases, fenced writes and the shared rate limiter.

The unit tests run the same code on a fake client whose transactions are optimistic like Firestore's; this file is what
proves the fake is faithful (the real ``async_transactional``, real contention, real ``Aborted`` retries). It is skipped
unless an emulator is running:

    gcloud emulators firestore start --host-port=localhost:8686         # (or: firebase emulators:start --only firestore)
    FIRESTORE_EMULATOR_HOST=localhost:8686 python -m pytest tests/emulator -q -p no:cacheprovider --no-cov

Nothing here talks to a real project: the client is created for a throwaway project id, and the emulator forgets everything
when it stops.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="needs FIRESTORE_EMULATOR_HOST (a Firestore emulator)")

from app.gateway.limits import SharedRateLimiter  # noqa: E402
from app.repo import firestore, leases  # noqa: E402
from app.repo.leases import LeaseHeld, LeaseLost  # noqa: E402


@pytest.fixture
async def emulator(monkeypatch):
    from google.cloud.firestore_v1.async_client import AsyncClient

    client = AsyncClient(project="demo-cargoclear")
    monkeypatch.setattr(firestore, "_firestore_client", client)
    yield client


def bundle() -> str:
    return f"bnd-{uuid.uuid4().hex[:12]}"


@pytest.mark.asyncio
async def test_many_instances_claiming_one_bundle_yield_one_winner(emulator) -> None:
    bundle_id = bundle()
    results = await asyncio.gather(
        *[leases.claim(bundle_id, run_id=f"run-{n}", mode="full", owner=f"i{n}") for n in range(15)], return_exceptions=True
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert sum(isinstance(r, LeaseHeld) for r in results) == 14, [type(r).__name__ for r in results if isinstance(r, BaseException)]


@pytest.mark.asyncio
async def test_a_queued_run_is_acquired_by_one_worker_and_a_stale_executor_is_fenced_out(emulator) -> None:
    bundle_id = bundle()
    await leases.claim(bundle_id, run_id="run-1", mode="reassess", state="QUEUED", iteration=2)
    results = await asyncio.gather(*[leases.acquire(bundle_id, "run-1", owner=f"w{n}") for n in range(6)], return_exceptions=True)
    [(lease, _)] = [r for r in results if not isinstance(r, BaseException)]
    assert lease.fence == 1 and lease.iteration == 2

    doc = emulator.collection("bundles").document(bundle_id).collection("iterations").document("2")

    async def write(transaction) -> None:
        transaction.create(doc, {"by": "executor"})

    assert await leases.fenced_transaction(bundle_id, "run-1", lease.fence, write, release_after=True) is None
    assert (await doc.get()).exists and await leases.read(bundle_id) is None
    with pytest.raises(LeaseLost):  # the lease is gone: the same executor can no longer write
        await leases.fenced_transaction(bundle_id, "run-1", lease.fence, write)


@pytest.mark.asyncio
async def test_expiry_and_take_over_on_the_real_clock(emulator) -> None:
    bundle_id = bundle()
    await leases.claim(bundle_id, run_id="run-1", mode="full", state="QUEUED", ttl=30)
    first, _ = await leases.acquire(bundle_id, "run-1", owner="old", ttl=0.3)
    with pytest.raises(LeaseHeld):
        await leases.acquire(bundle_id, "run-1", owner="new", ttl=30)
    await asyncio.sleep(0.5)
    second, taken_over = await leases.acquire(bundle_id, "run-1", owner="new", ttl=30)
    assert taken_over and second.fence == first.fence + 1
    with pytest.raises(LeaseLost):
        await leases.heartbeat(bundle_id, "run-1", first.fence)


@pytest.mark.asyncio
async def test_a_burst_from_one_client_is_counted_exactly(emulator) -> None:
    limiter = SharedRateLimiter()
    client = f"203.0.113.{uuid.uuid4().int % 250}"
    results = await asyncio.gather(*[limiter.hit("writes", client, 5) for _ in range(12)])
    assert results.count(None) == 5 and len([r for r in results if r is not None]) == 7
