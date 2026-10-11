"""The optional google-adk pipeline engine (PIPELINE_ENGINE=adk): the stages as the nodes of an ADK Workflow.

This replaces the old stub. It is a SPIKE: the default engine is the plain loop in ``services/engines.py``, and nothing
imports this module's ADK dependency unless the ADK engine is selected (every ``google.adk`` name is imported inside a
function, so the module imports in the default install, which does not have google-adk: it lives in the separate lock
``requirements-adk.txt``).

What an engine may do (see ``services/engines.py``): drive the loop over the stage names and nothing else. Every node here
is a THIN function node that awaits the orchestrator's ``run_stage(stage, ctx)``; the claim check, progress writes, logging
and dispatch all happen in ``orchestrator._stage``, so a run behaves identically under both engines. There are no LLM Agent
objects: the pipeline stays deterministic.

Design decisions (and why):

* No ``retry_config`` and no ``timeout`` on any node. The extraction stage already has its own retry policy
  (``GEMINI_MAX_ATTEMPTS`` with backoff); an ADK retry on top would multiply Gemini calls (3 x 3) and bill them. A node
  timeout would add a second, uncoordinated deadline next to ``RUN_TIMEOUT_SECONDS``, which already bounds the whole run
  and produces the user-facing "the analysis exceeded the time limit".
* Only a small token (the ``run_id``) travels through ADK. The pipeline ctx holds bytes and pydantic objects: it must not be
  serialised into ADK events or session state, so it lives in the Python-side registry ``_RUNS`` for the duration of the run
  and the nodes look it up by token.
* ``run_adk`` wraps nothing: an exception in a stage reaches the caller unchanged (ADK propagates it as it was raised), and
  cancelling the caller cancels the running node. The registry entry is removed in a ``finally``, so ``_RUNS`` cannot grow.
* ADK logs a failing node's exception text and traceback itself (two ERROR records). the orchestrator already logs the same
  exception with ``logger.exception``, so the duplicates are dropped by a narrow logging filter (see
  ``_silence_adk_failure_logs``); nothing else of ADK's logging is touched.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from app.services.engines import RunStage

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "cargoclear_pipeline"
APP_NAME = "cargoclear"
USER_ID = "pipeline"

# ADK logs a failing node's exception (text + traceback) from these two loggers.
_ADK_FAILURE_LOGGERS = ("google_adk.google.adk.workflow._node_runner", "google_adk.google.adk.runners")


@dataclass
class _RunState:
    """What the nodes of one run share: the pipeline ctx (replaced by whatever a stage returns) and the stage callable."""

    ctx: dict[str, Any]
    run_stage: RunStage


# run_id -> state. An entry exists only while that run is executing.
_RUNS: dict[str, _RunState] = {}

# One Workflow per process (per stage tuple): it is a stateless graph of nodes, shared by every run.
_WORKFLOWS: dict[tuple[str, ...], Any] = {}


class _DropFailureRecords(logging.Filter):
    """Drop ERROR-level records that carry an exception: ADK's own copy of what the orchestrator already logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.levelno >= logging.ERROR and record.exc_info)


_failure_filter = _DropFailureRecords()


def _silence_adk_failure_logs() -> None:
    for name in _ADK_FAILURE_LOGGERS:
        adk_logger = logging.getLogger(name)
        if _failure_filter not in adk_logger.filters:
            adk_logger.addFilter(_failure_filter)


def _token_of(node_input: Any) -> str:
    """The run token: the first node receives the user message (``types.Content``), the others the previous node's output."""
    if isinstance(node_input, str):
        return node_input
    parts = getattr(node_input, "parts", None)
    if parts and getattr(parts[0], "text", None):
        return str(parts[0].text)
    raise LookupError("the ADK workflow node received neither the run token nor the start message")


def _make_node(stage: str, node: Any) -> Any:
    @node(name=stage)
    async def run_node(node_input: Any) -> str:
        token = _token_of(node_input)
        state = _RUNS[token]
        state.ctx = await state.run_stage(stage, state.ctx)
        return token

    return run_node


def build_workflow(stages: Sequence[str]) -> Any:
    """The ADK Workflow ``cargoclear_pipeline``: one function node per stage (node name = stage name), chained from START.

    Built once per process and cached. Needs google-adk (ImportError otherwise).
    """
    key = tuple(stages)
    cached = _WORKFLOWS.get(key)
    if cached is not None:
        return cached

    from google.adk import Workflow
    from google.adk.workflow import START, node

    _silence_adk_failure_logs()
    nodes = [_make_node(stage, node) for stage in stages]
    workflow = Workflow(name=WORKFLOW_NAME, edges=[(START, *nodes)])
    _WORKFLOWS[key] = workflow
    return workflow


async def run_adk(ctx: dict[str, Any], stages: Sequence[str], run_stage: RunStage) -> dict[str, Any]:
    """Run ``stages`` as the nodes of the ADK workflow and return the final ctx.

    Exceptions (and cancellation) propagate unchanged; the registry entry and the runner are always cleaned up.
    """
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    token = ctx["run_id"]
    state = _RunState(ctx=ctx, run_stage=run_stage)
    _RUNS[token] = state
    runner = None
    try:
        workflow = build_workflow(stages)
        runner = Runner(
            node=workflow, app_name=APP_NAME, session_service=InMemorySessionService(), auto_create_session=True
        )
        message = types.Content(role="user", parts=[types.Part(text=token)])
        async for event in runner.run_async(user_id=USER_ID, session_id=token, new_message=message):
            node_info = getattr(event, "node_info", None)
            logger.debug("adk_event", run_id=token, path=getattr(node_info, "path", None))  # a path, never content
        return state.ctx
    finally:
        try:
            if runner is not None:
                await runner.close()
        except Exception as exc:  # noqa: BLE001 - must never replace the exception that is propagating
            logger.warning("adk_runner_close_failed", run_id=token, error_type=type(exc).__name__)
        finally:
            _RUNS.pop(token, None)
