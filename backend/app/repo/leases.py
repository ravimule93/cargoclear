"""Run leases: who may run an assessment for a bundle, across API instances.

One document per bundle, ``bundles/{id}/control/lease``, is the claim. It exists exactly while a run is queued or running:

    run_id      the run that holds it
    state       QUEUED (waiting for a worker) | RUNNING (a worker is executing it)
    mode        full | reassess | recompute
    iteration   the assessment number the run will write
    owner       the instance executing it (None while QUEUED)
    fence       counts the executions of this run: every acquisition (and every take-over of a dead executor) adds one
    expires_at  the lease is dead once this passes: a live executor extends it by heartbeat

Every change is one atomic read-modify-write (a Firestore transaction; in demo mode a dict update that never yields), and
the decision of each operation is a small PURE function below, shared by both stores, so the rules are tested once.

Fencing: a run proves it still owns the bundle with its ``(run_id, fence)`` pair. ``fenced_transaction`` verifies the pair
and does the caller's writes in the SAME transaction, so an executor that was paused past its lease and then wakes up cannot
write an iteration or a terminal state: its pair no longer matches and the write is refused (``LeaseLost``).

Time is wall-clock UTC read through ``_now()`` so that tests can move it. Instances are assumed to have clocks within a few
seconds of each other (Cloud Run does); the lease TTL (90 s by default) is long against that.
"""

from __future__ import annotations

import copy
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from google.cloud.firestore_v1 import async_transactional

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Demo mode: the leases of this process
_MEMORY: dict[str, dict[str, Any]] = {}

INSTANCE_ID = f"{os.environ.get('K_REVISION') or socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"

QUEUED, RUNNING = "QUEUED", "RUNNING"
_DELETE = object()


class LeaseHeld(Exception):
    """Somebody else holds a live lease on the bundle."""

    def __init__(self, lease: "Lease") -> None:
        super().__init__("the bundle is leased")
        self.lease = lease


class LeaseLost(Exception):
    """The run no longer owns the bundle (its lease expired, was taken over, or released)."""


@dataclass(frozen=True)
class Lease:
    run_id: str
    state: str
    mode: str
    iteration: int
    owner: str | None
    fence: int
    claimed_at: str
    heartbeat_at: str
    expires_at: str

    def expired(self, now: datetime | None = None) -> bool:
        return _parse(self.expires_at) <= (now or _now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Lease":
        return Lease(
            run_id=str(data["run_id"]),
            state=str(data.get("state", RUNNING)),
            mode=str(data.get("mode", "full")),
            iteration=int(data.get("iteration", 0)),
            owner=data.get("owner"),
            fence=int(data.get("fence", 0)),
            claimed_at=str(data.get("claimed_at", "")),
            heartbeat_at=str(data.get("heartbeat_at", "")),
            expires_at=str(data.get("expires_at", "")),
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(stamp: str) -> datetime:
    """A stored timestamp; one that cannot be read counts as long expired (it cannot prove anybody is alive)."""
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _later(seconds: float, now: datetime) -> str:
    return _iso(now + timedelta(seconds=seconds))


# ---------------------------------------------------------------------------
# The decisions (pure): current lease dict (or None) -> (new lease dict | _DELETE | None for "no change", result)
# ---------------------------------------------------------------------------

Decision = tuple[Any, Any]


def decide_claim(
    current: dict[str, Any] | None, *, run_id: str, mode: str, state: str, owner: str | None, iteration: int, ttl: float
) -> Decision:
    """Take the bundle if nobody holds a live lease. An EXPIRED lease is replaced and handed back as ``superseded``."""
    now = _now()
    old = Lease.from_dict(current) if current else None
    if old is not None and not old.expired(now):
        raise LeaseHeld(old)
    fence = (old.fence if old else 0) + (1 if state == RUNNING else 0)
    lease = Lease(
        run_id=run_id, state=state, mode=mode, iteration=iteration, owner=owner, fence=fence,
        claimed_at=_iso(now), heartbeat_at=_iso(now), expires_at=_later(ttl, now),
    )
    return lease.to_dict(), (lease, old)


def decide_acquire(current: dict[str, Any] | None, *, run_id: str, owner: str, ttl: float) -> Decision:
    """A worker starts (or restarts) executing ``run_id``.

    QUEUED -> RUNNING. A RUNNING lease of the same run that has EXPIRED is taken over (its executor died: Cloud Tasks
    delivered the task again). A live RUNNING lease belongs to another executor: ``LeaseHeld`` (a duplicate delivery).
    Anything else (no lease, another run's lease) means the task is obsolete: ``LeaseLost``.
    """
    now = _now()
    if current is None:
        raise LeaseLost()
    old = Lease.from_dict(current)
    if old.run_id != run_id:
        raise LeaseLost()
    taken_over = old.state == RUNNING
    if taken_over and not old.expired(now):
        raise LeaseHeld(old)
    lease = Lease(
        run_id=run_id, state=RUNNING, mode=old.mode, iteration=old.iteration, owner=owner, fence=old.fence + 1,
        claimed_at=old.claimed_at, heartbeat_at=_iso(now), expires_at=_later(ttl, now),
    )
    return lease.to_dict(), (lease, taken_over)


def _owned(current: dict[str, Any] | None, run_id: str, fence: int) -> Lease:
    if current is None:
        raise LeaseLost()
    lease = Lease.from_dict(current)
    if lease.run_id != run_id or lease.fence != fence:
        raise LeaseLost()
    return lease


def decide_heartbeat(current: dict[str, Any] | None, *, run_id: str, fence: int, ttl: float) -> Decision:
    lease = _owned(current, run_id, fence)
    now = _now()
    extended = Lease(**{**lease.to_dict(), "heartbeat_at": _iso(now), "expires_at": _later(ttl, now)})
    return extended.to_dict(), extended


def decide_update(current: dict[str, Any] | None, *, run_id: str, fence: int, **fields: Any) -> Decision:
    lease = _owned(current, run_id, fence)
    updated = Lease(**{**lease.to_dict(), **fields})
    return updated.to_dict(), updated


def decide_release(current: dict[str, Any] | None, *, run_id: str, fence: int | None) -> Decision:
    """Delete the lease if it is this run's (and, with a fence, this execution's). Releasing what is not yours is a no-op."""
    if current is None:
        return None, False
    lease = Lease.from_dict(current)
    if lease.run_id != run_id or (fence is not None and lease.fence != fence):
        return None, False
    return _DELETE, True


def decide_reap(current: dict[str, Any] | None) -> Decision:
    """Delete an EXPIRED lease and hand it back: the caller that gets it is the one reaper of that dead run."""
    if current is None:
        return None, None
    lease = Lease.from_dict(current)
    if not lease.expired():
        return None, None
    return _DELETE, lease


# ---------------------------------------------------------------------------
# The stores
# ---------------------------------------------------------------------------


def _get_client() -> Any:
    """The async Firestore client of the repository (one client for every collection), or None in demo mode."""
    from app.repo import firestore  # call-time import: repo/firestore.py imports this module

    return firestore._get_firestore_client()


def _ref(client: Any, bundle_id: str) -> Any:
    return client.collection("bundles").document(bundle_id).collection("control").document("lease")


async def transact(client: Any, work: Callable[[Any], Awaitable[Any]], *, max_attempts: int | None = None) -> Any:
    """Run ``work(transaction)`` in a Firestore transaction; the library retries contention (Aborted), 5 attempts by default
    (``max_attempts`` for a document many requests touch at once)."""

    @async_transactional
    async def run(transaction: Any) -> Any:
        return await work(transaction)

    return await run(client.transaction(**({"max_attempts": max_attempts} if max_attempts else {})))


async def _modify(bundle_id: str, decide: Callable[[dict[str, Any] | None], Decision]) -> Any:
    """Atomic read-modify-write of the lease document with ``decide``; its result is returned, its exceptions propagate."""
    client = _get_client()
    if client is None:
        current = copy.deepcopy(_MEMORY.get(bundle_id))
        new, result = decide(current)  # no await between the read and the write: atomic in one event loop
        if new is _DELETE:
            _MEMORY.pop(bundle_id, None)
        elif new is not None:
            _MEMORY[bundle_id] = new
        return result

    ref = _ref(client, bundle_id)

    async def work(transaction: Any) -> Any:
        snapshot = await ref.get(transaction=transaction)
        new, result = decide(snapshot.to_dict() if snapshot.exists else None)
        if new is _DELETE:
            transaction.delete(ref)
        elif new is not None:
            transaction.set(ref, new)
        return result

    return await transact(client, work)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    lease: Lease
    superseded: Lease | None  # the EXPIRED lease this one replaced: the dead run to be marked failed (and audited once)


async def claim(
    bundle_id: str, *, run_id: str, mode: str, state: str = RUNNING, owner: str | None = None, iteration: int = 0,
    ttl: float | None = None,
) -> Claim:
    """Claim the bundle for a run. ``LeaseHeld`` when a live run has it. Atomic across instances."""
    if ttl is None:
        ttl = settings.run_queue_wait_seconds if state == QUEUED else settings.run_stale_after_seconds
    lease, old = await _modify(
        bundle_id,
        lambda current: decide_claim(current, run_id=run_id, mode=mode, state=state, owner=owner, iteration=iteration, ttl=ttl),
    )
    return Claim(lease, old)


async def acquire(bundle_id: str, run_id: str, *, owner: str | None = None, ttl: float | None = None) -> tuple[Lease, bool]:
    """A worker takes a queued run (or a dead executor's). Returns the lease and whether it was a take-over."""
    lease, taken_over = await _modify(
        bundle_id,
        lambda current: decide_acquire(current, run_id=run_id, owner=owner or INSTANCE_ID, ttl=ttl or settings.run_stale_after_seconds),
    )
    return lease, taken_over


async def heartbeat(bundle_id: str, run_id: str, fence: int, *, ttl: float | None = None) -> Lease:
    """Extend a lease this execution still owns; ``LeaseLost`` otherwise."""
    result: Lease = await _modify(
        bundle_id, lambda current: decide_heartbeat(current, run_id=run_id, fence=fence, ttl=ttl or settings.run_stale_after_seconds)
    )
    return result


async def update(bundle_id: str, run_id: str, fence: int, **fields: Any) -> Lease:
    """Change fields (``iteration``) of a lease this execution owns."""
    result: Lease = await _modify(bundle_id, lambda current: decide_update(current, run_id=run_id, fence=fence, **fields))
    return result


async def expire(bundle_id: str, run_id: str, fence: int) -> Lease:
    """Count a lease this execution owns as expired NOW: a worker that cannot run its run hands it to the next delivery of the
    task instead of making it wait out the lease. ``LeaseLost`` when it no longer owns it."""
    return await update(bundle_id, run_id, fence, expires_at=_iso(_now()))


async def release(bundle_id: str, run_id: str, fence: int | None = None) -> bool:
    """Give the bundle back. True when this call deleted the lease."""
    return bool(await _modify(bundle_id, lambda current: decide_release(current, run_id=run_id, fence=fence)))


async def reap_expired(bundle_id: str) -> Lease | None:
    """Delete the bundle's lease if it has expired; the expired lease, for exactly ONE caller, else None."""
    result: Lease | None = await _modify(bundle_id, decide_reap)
    return result


async def read(bundle_id: str) -> Lease | None:
    """The bundle's lease (live or expired), or None. A plain read: it decides nothing."""
    client = _get_client()
    if client is None:
        current = _MEMORY.get(bundle_id)
        return Lease.from_dict(copy.deepcopy(current)) if current else None
    snapshot = await _ref(client, bundle_id).get()
    return Lease.from_dict(snapshot.to_dict()) if snapshot.exists else None


async def verify(bundle_id: str, run_id: str, fence: int) -> None:
    """``LeaseLost`` unless this execution still owns the bundle. A read, so a cheap check between stages; the writes that
    must never be stale go through ``fenced_transaction`` instead."""
    lease = await read(bundle_id)
    if lease is None or lease.run_id != run_id or lease.fence != fence:
        raise LeaseLost()


async def fenced_transaction(
    bundle_id: str, run_id: str, fence: int, work: Callable[[Any], Awaitable[Any]], *, release_after: bool = False
) -> Any:
    """Verify the lease and do ``work`` in the same atomic step.

    ``work(transaction)`` buffers the writes on a Firestore transaction (its reads must go through ``get(transaction=...)``);
    in demo mode it is called with ``None`` and does its writes directly. With ``release_after`` the lease is deleted in the
    same step (the terminal write of a run). ``LeaseLost`` when this execution no longer owns the bundle.
    """
    client = _get_client()
    if client is None:
        _owned(_MEMORY.get(bundle_id), run_id, fence)
        result = await work(None)  # demo mode: single process, the writes below it never interleave with a take-over
        if release_after:
            _MEMORY.pop(bundle_id, None)
        return result

    ref = _ref(client, bundle_id)

    async def in_transaction(transaction: Any) -> Any:
        snapshot = await ref.get(transaction=transaction)
        _owned(snapshot.to_dict() if snapshot.exists else None, run_id, fence)
        result = await work(transaction)
        if release_after:
            transaction.delete(ref)
        return result

    return await transact(client, in_transaction)


def reset_for_tests() -> None:
    """Forget every in-memory lease (the test fixture calls this)."""
    _MEMORY.clear()
