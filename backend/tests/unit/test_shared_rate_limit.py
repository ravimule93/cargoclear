"""The Firestore-backed rate limiter: every instance counts the same requests, and an outage of the counter is not an outage."""

from __future__ import annotations

import asyncio
from datetime import timezone

import pytest

from app.core.config import settings
from app.gateway import limits
from app.gateway.limits import SharedRateLimiter, count_request
from app.repo import firestore, leases
from tests.unit.firestore_fakes import FakeFirestore, fake_async_transactional


class Clock:
    def __init__(self, now: float = 1_800_000_030.0) -> None:  # 30 s into a minute window
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def store(monkeypatch) -> FakeFirestore:
    fake = FakeFirestore()
    monkeypatch.setattr(firestore, "_firestore_client", fake)
    monkeypatch.setattr(leases, "async_transactional", fake_async_transactional)
    return fake


@pytest.mark.asyncio
async def test_two_instances_share_one_limit(store) -> None:
    """Five requests allowed a minute: ten arrive at once, spread over two 'instances' (two limiter objects, one store)."""
    clock = Clock()
    instance_a, instance_b = SharedRateLimiter(clock), SharedRateLimiter(clock)
    results = await asyncio.gather(
        *[(instance_a if n % 2 else instance_b).hit("writes", "203.0.113.7", 5) for n in range(10)]
    )
    assert results.count(None) == 5, "exactly the limit gets through, however many instances count"
    assert all(isinstance(r, int) and r >= 1 for r in results if r is not None)


@pytest.mark.asyncio
async def test_a_refusal_says_how_long_until_the_window_ends(store) -> None:
    clock = Clock(1_800_000_030.0)  # 30 s left in the minute
    limiter = SharedRateLimiter(clock)
    assert [await limiter.hit("runs", "ip", 2) for _ in range(2)] == [None, None]
    assert await limiter.hit("runs", "ip", 2) == 30
    clock.now = 1_800_000_050.5
    assert await limiter.hit("runs", "ip", 2) == 10, "rounded up to whole seconds"
    clock.now += 10  # the next minute: a fresh window
    assert await limiter.hit("runs", "ip", 2) is None


@pytest.mark.asyncio
async def test_classes_and_clients_are_counted_apart(store) -> None:
    limiter = SharedRateLimiter(Clock())
    assert await limiter.hit("writes", "a", 1) is None and await limiter.hit("writes", "a", 1) is not None
    assert await limiter.hit("runs", "a", 1) is None, "another class"
    assert await limiter.hit("writes", "b", 1) is None, "another client"


@pytest.mark.asyncio
async def test_a_limit_of_zero_is_off_and_touches_nothing(store) -> None:
    limiter = SharedRateLimiter(Clock())
    assert [await limiter.hit("writes", "a", 0) for _ in range(5)] == [None] * 5
    assert store.docs == {}


@pytest.mark.asyncio
async def test_the_stored_counter_holds_no_ip_address_and_expires(store) -> None:
    limiter = SharedRateLimiter(Clock(1_800_000_030.0))
    await limiter.hit("writes", "203.0.113.7", 5)
    [(path, doc)] = store.docs.items()
    assert path[0] == "ratelimits" and "203.0.113.7" not in "/".join(path) and "203.0.113.7" not in str(doc)
    assert doc["count"] == 1 and doc["class"] == "writes"
    expires = doc["expires_at"]
    assert expires.tzinfo is timezone.utc and expires.timestamp() == (1_800_000_030 // 60 + 1) * 60 + 2 * 3600, "a Firestore TTL policy deletes it"


@pytest.mark.asyncio
async def test_a_missing_client_is_an_error_the_caller_must_handle(monkeypatch) -> None:
    monkeypatch.setattr(firestore, "_firestore_client", None)
    with pytest.raises(RuntimeError):
        await SharedRateLimiter(Clock()).hit("writes", "a", 5)


# ---------------------------------------------------------------------------
# the backend choice and its fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_memory_backend_is_the_default_and_counts_in_process(store, monkeypatch) -> None:
    assert settings.rate_limit_backend == "memory"
    monkeypatch.setattr(limits, "rate_limiter", limits.RateLimiter(clock=lambda: 100.0))
    assert [await count_request("writes", "a", 2) for _ in range(3)] == [None, None, 60]
    assert store.docs == {}, "nothing is written to Firestore"


@pytest.mark.asyncio
async def test_the_firestore_backend_counts_in_firestore(store, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_backend", "firestore")
    results = [await count_request("writes", "a", 2) for _ in range(3)]
    assert results[:2] == [None, None] and results[2] is not None
    assert len(store.docs) == 1


@pytest.mark.asyncio
async def test_if_firestore_fails_the_request_is_still_counted_by_this_process(store, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_backend", "firestore")

    async def broken(*args, **kwargs):
        raise ConnectionError("firestore is down")

    monkeypatch.setattr(limits.shared_rate_limiter, "hit", broken)
    local = limits.RateLimiter(clock=lambda: 100.0)
    monkeypatch.setattr(limits, "rate_limiter", local)

    assert [await count_request("writes", "a", 2) for _ in range(3)] == [None, None, 60], "bounded, not open"


@pytest.mark.asyncio
async def test_a_slow_firestore_does_not_stall_the_request(store, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_backend", "firestore")
    monkeypatch.setattr(limits, "_SHARED_TIMEOUT_SECONDS", 0.05)

    async def slow(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(limits.shared_rate_limiter, "hit", slow)
    monkeypatch.setattr(limits, "rate_limiter", limits.RateLimiter(clock=lambda: 100.0))
    assert await asyncio.wait_for(count_request("writes", "a", 1), 1.0) is None


@pytest.mark.asyncio
async def test_without_a_firestore_client_the_firestore_backend_falls_back_to_memory(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_backend", "firestore")
    monkeypatch.setattr(limits, "rate_limiter", limits.RateLimiter(clock=lambda: 100.0))
    assert [await count_request("writes", "a", 1) for _ in range(2)] == [None, 60], "demo mode has no Firestore: the local limiter"
