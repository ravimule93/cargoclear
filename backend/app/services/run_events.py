"""Wake-up channel between the orchestrator and the SSE streams.

The orchestrator writes run records; a stream that is asleep in its poll interval would show a new run up to
STREAM_POLL_IDLE_SECONDS late. The orchestrator therefore calls ``notify(bundle_id)`` after every run-record write and
after ``write_iteration``, and a stream waits on ``Subscription.wait(timeout)``: it wakes at once on a change and still
wakes at the timeout, which keeps the poll as the fallback (nothing depends on a notify arriving).

Each bundle has a channel with a version counter, and each subscriber remembers the version it has seen. A change that
happens while the subscriber is busy (between two waits, or between subscribing and the first wait) bumps the
version, so the next ``wait`` returns at once instead of sleeping through it. A bare ``wait(bundle_id, timeout)`` has no
way to know what its caller has already seen, so the module-level ``wait`` is the one-shot form; a long-lived listener
(the SSE stream) uses ``subscribe``.

The API runs as ONE instance, so this is in-process. A channel exists only while it has subscribers (no unbounded
growth), and notifying a bundle nobody listens to creates nothing.
"""

from __future__ import annotations

import asyncio
from types import TracebackType


class _Channel:
    __slots__ = ("version", "subscribers")

    def __init__(self) -> None:
        self.version = 0
        self.subscribers: set[Subscription] = set()


_CHANNELS: dict[str, _Channel] = {}


class Subscription:
    """One listener on one bundle. Use as a context manager, or call ``close()``."""

    def __init__(self, bundle_id: str) -> None:
        self._bundle_id = bundle_id
        self._channel = _CHANNELS.setdefault(bundle_id, _Channel())
        self._channel.subscribers.add(self)
        self._seen = self._channel.version
        self._future: asyncio.Future[None] | None = None

    def _wake(self) -> None:
        if self._future is not None and not self._future.done():
            self._future.set_result(None)

    async def wait(self, timeout: float) -> None:
        """Return when the bundle changed since the last wait, or after ``timeout`` seconds, whichever is first."""
        channel = self._channel
        if channel.version != self._seen:
            self._seen = channel.version
            return
        self._future = asyncio.get_running_loop().create_future()
        try:
            await asyncio.wait_for(self._future, timeout)
        except TimeoutError:
            pass
        finally:
            self._future = None
            self._seen = channel.version

    def close(self) -> None:
        channel = self._channel
        channel.subscribers.discard(self)
        if not channel.subscribers and _CHANNELS.get(self._bundle_id) is channel:
            del _CHANNELS[self._bundle_id]

    def __enter__(self) -> Subscription:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


def subscribe(bundle_id: str) -> Subscription:
    """Start listening to ``bundle_id``: changes from now on are remembered until the next ``wait``."""
    return Subscription(bundle_id)


def notify(bundle_id: str) -> None:
    """Announce that the run record or the iterations of ``bundle_id`` changed."""
    channel = _CHANNELS.get(bundle_id)
    if channel is None:
        return  # nobody listens: a later subscriber starts from the stored state anyway
    channel.version += 1
    for subscriber in tuple(channel.subscribers):
        subscriber._wake()


async def wait(bundle_id: str, timeout: float) -> None:
    """One-shot: return on the next change of ``bundle_id`` or after ``timeout`` seconds."""
    with subscribe(bundle_id) as subscription:
        await subscription.wait(timeout)
