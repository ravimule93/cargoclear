"""Pipeline engines: the thing that drives the stage loop.

The ENGINE replaces nothing but the loop over ``PIPELINE_STAGES``. Everything around it stays in the orchestrator and is
identical for every engine: the claim, the heartbeat, the deadline, fencing, wake-up notifications, progress writes,
ANALYSIS_STARTED / finalize / ASSESSMENT_COMPLETED, cancellation, ``public_error``, the stage names and the progress
fractions. An engine receives ``run_stage(stage, ctx) -> ctx`` (the orchestrator's ``_stage``, which does the claim check,
the progress write, the log lines and the dispatch) and calls it once per stage, in order. It never dispatches itself, and
an exception raised by a stage must reach the orchestrator UNCHANGED, so the run state, the audit payload and
``public_error`` are the same whichever engine ran.

``native`` is the plain loop. ``adk`` runs the same stages as the nodes of a google-adk Workflow (``agents/workflow.py``);
google-adk is not in the default dependency lock, so it is imported lazily and only when selected.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

RunStage = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
Engine = Callable[[dict[str, Any], Sequence[str], RunStage], Awaitable[dict[str, Any]]]

ENGINE_NAMES = ("native", "adk")
ADK_MISSING_MESSAGE = "PIPELINE_ENGINE=adk but google-adk is not installed: use the ADK lock (requirements-adk.txt)"


async def run_native(ctx: dict[str, Any], stages: Sequence[str], run_stage: RunStage) -> dict[str, Any]:
    """The plain loop."""
    for stage in stages:
        ctx = await run_stage(stage, ctx)
    return ctx


async def run_adk(ctx: dict[str, Any], stages: Sequence[str], run_stage: RunStage) -> dict[str, Any]:
    """The same stages as nodes of a google-adk Workflow. The import is lazy: the default install does not have it."""
    from app.agents.workflow import run_adk as run_workflow

    return await run_workflow(ctx, stages, run_stage)


def get_engine(name: str) -> Engine:
    """The engine called ``name`` (``native`` or ``adk``); anything else is a programming error."""
    if name == "native":
        return run_native
    if name == "adk":
        return run_adk
    raise ValueError(f"unknown pipeline engine '{name}' (expected one of {', '.join(ENGINE_NAMES)})")


def require_engine(name: str) -> None:
    """Fail fast at startup: ``adk`` needs google-adk, and a server that cannot run its engine must not start."""
    if name == "adk":
        try:
            importlib.import_module("google.adk")
        except ImportError as exc:
            raise RuntimeError(ADK_MISSING_MESSAGE) from exc
