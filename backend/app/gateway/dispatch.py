"""Internal stage dispatcher.

The orchestrator calls ``dispatch(stage, ctx)`` to hand off to the right
handler without knowing which concrete module or agent handles it.
This indirection enables:
  - Easy mocking of any stage in tests
  - Swapping implementations without touching orchestrator logic
  - Running a single stage in isolation for debugging
"""

from typing import Awaitable, Callable

Stage = str
Handler = Callable[[dict], Awaitable[dict]]

# Stage handlers are registered lazily to avoid circular imports at module load time.
# Populated in _get_handlers() below.
_handlers: dict[Stage, Handler] | None = None


def _get_handlers() -> dict[Stage, Handler]:
    """Import handlers on first call (avoids circular imports)."""
    global _handlers
    if _handlers is not None:
        return _handlers

    from app.services import preprocess, calculation, reasoning, confidence, audit
    from app.agents.extraction import run_extraction_agent
    from app.agents.grounding import run_grounding_agent

    _handlers = {
        "preprocess": preprocess.run,
        "extract": run_extraction_agent,
        "discrepancy": calculation.run,
        "ground": run_grounding_agent,
        "confidence": confidence.route,
        "synthesize": reasoning.build,
        "audit": audit.record,
    }
    return _handlers


async def dispatch(stage: Stage, ctx: dict) -> dict:
    """Route a pipeline stage to its handler.

    Args:
        stage: One of the stage names in STAGE_HANDLERS.
        ctx:   Mutable pipeline context dict.

    Returns:
        Updated context dict from the handler.

    Raises:
        ValueError: If the stage name is unknown.
    """
    handlers = _get_handlers()
    handler = handlers.get(stage)
    if handler is None:
        msg = f"Unknown pipeline stage: '{stage}'. Valid stages: {sorted(handlers)}"
        raise ValueError(msg)
    return await handler(ctx)
