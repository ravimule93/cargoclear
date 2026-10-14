"""Small asyncio helpers shared by the pipeline stages.

``gather_in_order`` is the one way the pipeline fans out: results come back in input order, a failure cancels (and
awaits) the siblings and is re-raised as itself (never an ExceptionGroup), so callers keep catching the domain error
they always caught.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def gather_in_order(coroutines: list[Any]) -> list[Any]:
    """Run the coroutines concurrently; results come back in input order.

    If one raises, the others are cancelled and awaited (nothing is left running) and the failure itself is
    re-raised (the first in input order if several failed), not an ExceptionGroup.
    """
    if not coroutines:  # asyncio.wait refuses an empty set
        return []
    tasks = [asyncio.ensure_future(c) for c in coroutines]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in tasks:
            if task.done() and not task.cancelled() and task.exception() is not None:
                raise task.exception()
        return [task.result() for task in tasks]
    finally:
        pending = [task for task in tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in tasks:  # mark every failure as retrieved
            if task.done() and not task.cancelled():
                task.exception()


async def bounded(semaphore: asyncio.Semaphore, work: Callable[[], Awaitable[T]]) -> T:
    """Run ``work()`` while holding ``semaphore`` (a cap on how many run at once)."""
    async with semaphore:
        return await work()
