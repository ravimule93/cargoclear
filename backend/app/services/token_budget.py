"""The daily model-token budget: a counter of the tokens the whole service spent today (UTC), and the check that stops a new
analysis once it is spent.

What is counted: the tokens the API reported for every request of a run, when the run ends (completed, failed or cancelled), and for
every relevance check at upload (services/relevance.py). What is checked: the start of an analysis or a reassessment, and a relevance
check before it asks the model. A recompute asks nothing and is never refused. Nothing is refused mid-run: a run that has started
finishes, so one day can overshoot by the runs that were already in flight (at most ``MAX_CONCURRENT_RUNS`` per process, each bounded by
20 documents x the per-document worst case, docs/input-gating-audit.md section 5) plus whatever finished between a check and its count.

The counter lives in Firestore (``token_budget/<YYYYMMDD>``, an atomic increment, so every instance adds to the same number; an
in-memory dict in demo mode). A store that cannot be read or written never blocks the product: the check passes (logged), the count is
lost (logged). ``DAILY_TOKEN_BUDGET=0`` switches the budget off.

This is ONE counter for the whole service: it protects the money, not one user's share of it (that is the per-minute client limits,
gateway/limits.py). A budget alert on the billing account (infra/budget/setup_budget_alert.sh) is the other, independent line: it notifies,
it does not stop anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.core.config import settings
from app.gateway.errors import TokenBudgetExceededError
from app.repo import firestore

logger = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def today(now: datetime | None = None) -> str:
    """The UTC day the counter is kept under, ``YYYYMMDD``."""
    return (now or _now()).strftime("%Y%m%d")


def seconds_until_reset(now: datetime | None = None) -> int:
    """Whole seconds (at least 1) to the next 00:00 UTC, when the counter starts again."""
    moment = now or _now()
    midnight = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - moment).total_seconds()) + 1)


async def spent_today() -> int | None:
    """Tokens spent today, or None when the store cannot say (logged: the budget then cannot be enforced)."""
    try:
        return await firestore.get_daily_tokens(today())
    except Exception as exc:  # noqa: BLE001 - an unreadable counter never stops the product
        logger.warning("token_budget_unavailable", operation="read", error_type=type(exc).__name__)
        return None


async def exhausted() -> bool:
    """True when the daily budget is on and today's spend has reached it."""
    limit = settings.daily_token_budget
    if limit <= 0:
        return False
    spent = await spent_today()
    return spent is not None and spent >= limit


async def check() -> None:
    """Refuse (429 TOKEN_BUDGET_EXCEEDED, with Retry-After) a new analysis when today's budget is spent."""
    limit = settings.daily_token_budget
    spent = await spent_today() if limit > 0 else None
    if spent is None or spent < limit:
        return
    wait = seconds_until_reset()
    logger.warning("token_budget_exceeded", limit=settings.daily_token_budget, spent=spent, retry_after_seconds=wait)
    raise TokenBudgetExceededError(
        "The daily limit for model use has been reached, so no new analysis starts until it resets at 00:00 UTC. "
        "Recompute, which asks the model nothing, still works.",
        detail={"limit_tokens": settings.daily_token_budget, "resets_in_seconds": wait},
        headers={"Retry-After": str(wait)},
    )


async def add_spend(tokens: int) -> None:
    """Add what a run or a relevance check spent to today's count. Best effort: never raises."""
    if tokens <= 0 or settings.daily_token_budget <= 0:
        return
    try:
        await firestore.add_daily_tokens(today(), int(tokens))
    except Exception as exc:  # noqa: BLE001
        logger.warning("token_budget_unavailable", operation="write", error_type=type(exc).__name__, tokens=tokens)


async def status() -> dict[str, Any]:
    """The budget as the API shows it: the day, the limit (0 = off), the spend, what remains, and when it resets."""
    limit, spent = settings.daily_token_budget, await spent_today()
    return {
        "day": today(), "limit_tokens": limit, "enabled": limit > 0, "spent_tokens": spent,
        "remaining_tokens": None if spent is None or limit <= 0 else max(0, limit - spent), "resets_in_seconds": seconds_until_reset(),
    }
