"""D1: the in-process fixed-window limiter, with an injected clock (no sleeping)."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.gateway import limits
from app.gateway.limits import RateLimiter, classify_request, client_key
from tests.helpers import asgi_call, asgi_scope


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_requests_up_to_the_limit_pass_and_the_next_is_refused_with_the_seconds_to_wait() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)

    assert [limiter.hit("writes", "a", limit=3) for _ in range(3)] == [None, None, None]
    assert limiter.hit("writes", "a", limit=3) == 60


def test_retry_after_counts_down_with_the_window() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)
    for _ in range(2):
        limiter.hit("writes", "a", limit=1)

    clock.now += 10
    assert limiter.hit("writes", "a", limit=1) == 50
    clock.now += 49.5
    assert limiter.hit("writes", "a", limit=1) == 1, "never below one second"


def test_the_budget_comes_back_when_the_window_ends() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)
    limiter.hit("writes", "a", limit=1)
    assert limiter.hit("writes", "a", limit=1) is not None

    clock.now += 60

    assert limiter.hit("writes", "a", limit=1) is None
    assert limiter.hit("writes", "a", limit=1) is not None


def test_the_window_starts_at_the_first_request() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)
    clock.now += 30
    limiter.hit("writes", "a", limit=1)  # window: 1030..1090
    clock.now += 40  # 1070

    assert limiter.hit("writes", "a", limit=1) == 20


def test_classes_and_clients_have_separate_buckets() -> None:
    limiter = RateLimiter(Clock())
    limiter.hit("writes", "a", limit=1)

    assert limiter.hit("writes", "a", limit=1) is not None
    assert limiter.hit("runs", "a", limit=1) is None, "another class"
    assert limiter.hit("writes", "b", limit=1) is None, "another client"


def test_a_limit_of_zero_never_refuses_and_records_nothing() -> None:
    limiter = RateLimiter(Clock())

    assert [limiter.hit("writes", "a", limit=0) for _ in range(500)] == [None] * 500
    assert limiter._buckets == {}


def test_idle_buckets_are_dropped() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)
    for index in range(1000):
        limiter.hit("writes", f"10.0.{index // 250}.{index % 250}", limit=5)
    assert len(limiter._buckets) == 1000

    clock.now += 61
    limiter.hit("writes", "fresh", limit=5)  # any later request sweeps

    assert set(limiter._buckets) == {("writes", "fresh")}


def test_a_bucket_still_inside_its_window_survives_the_sweep() -> None:
    clock = Clock()
    limiter = RateLimiter(clock)
    limiter.hit("writes", "old", limit=5)
    clock.now += 40
    limiter.hit("writes", "newer", limit=5)
    clock.now += 25  # "old" is 65 s old, "newer" 25 s

    limiter.hit("writes", "fresh", limit=5)

    assert set(limiter._buckets) == {("writes", "newer"), ("writes", "fresh")}


def test_reset_forgets_everything() -> None:
    limiter = RateLimiter(Clock())
    limiter.hit("writes", "a", limit=1)

    limiter.reset()

    assert limiter._buckets == {} and limiter.hit("writes", "a", limit=1) is None


# ---------------------------------------------------------------------------
# which requests are limited, and under which key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/api/v1/bundles", "writes"),
        ("POST", "/api/v1/bundles/", "writes"),
        ("POST", "/api/v1/bundles/bnd-1/documents", "writes"),
        ("POST", "/api/v1/demo/case-c", "writes"),
        ("POST", "/api/v1/demo/case-d", "writes"),
        ("POST", "/api/v1/demo/case-e", None),
        ("POST", "/api/v1/bundles/bnd-1/analyze", "runs"),
        ("POST", "/api/v1/bundles/bnd-1/reassess", "runs"),
        ("POST", "/api/v1/bundles/bnd-1/recompute", "runs"),
        ("POST", "/api/v1/bundles/bnd-1/corrections", "writes"),
        ("POST", "/api/v1/bundles/bnd-1/corrections/cor-12/revert", "writes"),
        ("GET", "/api/v1/bundles/bnd-1/corrections", None),
        ("GET", "/api/v1/bundles/bnd-1/prefill", None),
        ("GET", "/api/v1/bundles/bnd-1/prefill.pdf", None),
        ("POST", "/api/v1/bundles/bnd-1/corrections/cor-12", None),
        ("GET", "/api/v1/bundles", None),
        ("GET", "/api/v1/bundles/bnd-1", None),
        ("GET", "/api/v1/bundles/bnd-1/stream", None),
        ("GET", "/api/v1/bundles/bnd-1/documents/doc-1/file", None),
        ("GET", "/api/v1/demo/case-c/mtc", None),
        ("GET", "/api/v1/bundles/bnd-1/analyze", None),
        ("POST", "/api/v1/bundles/bnd-1/audit", None),
        ("POST", "/api/v1/bundles/bnd-1/documents/extra", None),
        ("OPTIONS", "/api/v1/bundles", None),
        ("POST", "/healthz", None),
    ],
)
def test_classify_request(method, path, expected) -> None:
    assert classify_request(method, path) == expected


def scope_with(peer, forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return asgi_scope("POST", "/api/v1/bundles", headers=headers, client=peer)


def test_the_key_is_the_peer_address_by_default() -> None:
    assert client_key(scope_with(("10.0.0.1", 5), "9.9.9.9")) == "10.0.0.1"
    assert client_key(scope_with(None)) == "unknown"


def test_the_key_is_the_first_valid_forwarded_address_when_trusted(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trust_forwarded_for", True)

    assert client_key(scope_with(("10.0.0.1", 5), "9.9.9.9, 10.0.0.1")) == "9.9.9.9"
    assert client_key(scope_with(("10.0.0.1", 5), "unknown, 9.9.9.9")) == "9.9.9.9"
    assert client_key(scope_with(("10.0.0.1", 5), " 2001:DB8:0:0:0:0:0:1 ")) == "2001:db8::1"
    assert client_key(scope_with(("10.0.0.1", 5), "garbage, 999.1.1.1")) == "10.0.0.1"
    assert client_key(scope_with(("10.0.0.1", 5), None)) == "10.0.0.1"
    assert client_key(scope_with(None, "garbage")) == "unknown"


# ---------------------------------------------------------------------------
# through the app with the injected clock: limit hit, reset, Retry-After
# ---------------------------------------------------------------------------


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(limits, "rate_limiter", RateLimiter(fake))
    return fake


@pytest.mark.asyncio
async def test_the_limit_is_hit_and_resets_when_the_clock_moves(clock, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 2)
    send = lambda: asgi_call("POST", "/api/v1/bundles", body=b"{}", headers={"content-type": "application/json"})  # noqa: E731

    assert [(await send()).status for _ in range(2)] == [201, 201]
    refused = await send()
    assert refused.status == 429 and refused.headers["retry-after"] == "60"
    assert refused.json()["message"] == "Too many requests. Try again in 60 seconds."

    clock.now += 25
    assert (await send()).headers["retry-after"] == "35"

    clock.now += 35
    assert (await send()).status == 201


@pytest.mark.asyncio
async def test_the_default_limiter_uses_the_real_monotonic_clock() -> None:
    import time

    assert limits.RateLimiter()._clock is time.monotonic
