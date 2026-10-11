"""What we rely on from google-adk 2.11, pinned with plain ADK code (none of our wrappers).

If an ADK upgrade changes any of this, these tests fail first and say which assumption of agents/workflow.py broke.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

import pytest

from tests.adk.conftest import require_adk

require_adk()

from google.adk import Runner, Workflow  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.adk.workflow import START, NodeTimeoutError, RetryConfig, node  # noqa: E402
from google.genai import types  # noqa: E402


def make_node(stage: str, action: Any, log: list[tuple[str, str]], **node_options: Any):
    @node(name=stage, **node_options)
    async def run_node(node_input: Any) -> str:
        token = node_input.parts[0].text if hasattr(node_input, "parts") else node_input
        log.append(("start", stage, type(node_input).__name__))  # type: ignore[arg-type]
        try:
            await action()
        except asyncio.CancelledError:
            log.append(("cancelled", stage, ""))  # type: ignore[arg-type]
            raise
        return token

    return run_node


async def ok() -> None:
    return None


async def drive(actions: list[Any], log: list, *, cancel_after: float | None = None, name: str = "wf", token: str = "tok"):
    """Run a workflow of function nodes; returns the list of events. Closes the runner."""
    stages = [f"s{index}" for index in range(len(actions))]
    workflow = Workflow(name=name, edges=[(START, *[make_node(s, a, log) for s, a in zip(stages, actions, strict=True)])])
    runner = Runner(node=workflow, app_name="app", session_service=InMemorySessionService(), auto_create_session=True)
    events: list[Any] = []

    async def consume() -> None:
        message = types.Content(role="user", parts=[types.Part(text=token)])
        async for event in runner.run_async(user_id="u", session_id="s", new_message=message):
            events.append(event)

    task = asyncio.ensure_future(consume())
    if cancel_after is not None:
        await asyncio.sleep(cancel_after)
        task.cancel()
    try:
        await task
    finally:
        await runner.close()
    return events


def test_the_import_surface_we_use_exists() -> None:
    parameters = inspect.signature(node).parameters
    assert {"name", "retry_config", "timeout", "parameter_binding"} <= set(parameters)
    assert {"node", "app_name", "session_service", "auto_create_session"} <= set(inspect.signature(Runner.__init__).parameters)
    assert {"name", "edges"} <= set(Workflow.model_fields)
    assert callable(InMemorySessionService)


@pytest.mark.asyncio
async def test_one_event_per_node_in_order_with_the_node_path() -> None:
    events = await drive([ok, ok, ok], [])

    assert [e.node_info.path for e in events] == ["wf@1/s0@1", "wf@1/s1@1", "wf@1/s2@1"]
    assert [e.output for e in events] == ["tok", "tok", "tok"]


@pytest.mark.asyncio
async def test_the_first_node_gets_the_start_message_and_the_next_ones_the_previous_output() -> None:
    log: list = []
    await drive([ok, ok, ok], log)

    assert [(what, stage, kind) for what, stage, kind in log if what == "start"] == [
        ("start", "s0", "Content"), ("start", "s1", "str"), ("start", "s2", "str"),
    ]


@pytest.mark.asyncio
async def test_an_exception_in_a_node_reaches_the_consumer_unchanged() -> None:
    boom = FileNotFoundError(2, "No such file", "/secret/path.pdf")

    async def failing() -> None:
        raise boom

    log: list = []
    with pytest.raises(FileNotFoundError) as raised:
        await drive([ok, failing, ok], log)

    assert raised.value is boom, "the very object the node raised, not a copy and not a wrapper"
    assert raised.value.__cause__ is None
    assert [stage for what, stage, _ in log if what == "start"] == ["s0", "s1"], "nothing after the failing node ran"


@pytest.mark.asyncio
async def test_a_custom_exception_keeps_its_attributes() -> None:
    from app.gateway.errors import ExtractionError

    boom = ExtractionError("Extraction failed for document d1", detail={"document_id": "d1"})

    async def failing() -> None:
        raise boom

    with pytest.raises(ExtractionError) as raised:
        await drive([failing], [])

    assert raised.value is boom and raised.value.code == "EXTRACTION_FAILED" and raised.value.detail == {"document_id": "d1"}


@pytest.mark.asyncio
async def test_cancelling_the_consumer_cancels_the_running_node_and_leaves_no_task() -> None:
    async def slow() -> None:
        await asyncio.sleep(30)

    before = set(asyncio.all_tasks())
    log: list = []
    with pytest.raises(asyncio.CancelledError):
        await drive([ok, slow, ok], log, cancel_after=0.3)
    await asyncio.sleep(0.2)

    assert [what for what, stage, _ in log if stage == "s1"] == ["start", "cancelled"], "the node saw the cancellation"
    assert "s2" not in [stage for _, stage, _ in log]
    assert [t for t in asyncio.all_tasks() - before if not t.done()] == []


@pytest.mark.asyncio
async def test_retry_config_reruns_a_failing_node_which_is_why_we_do_not_use_it() -> None:
    """ADK would re-run the extraction node on top of extraction's own retries (3 x 3 Gemini calls)."""
    attempts = {"n": 0}

    @node(name="flaky", retry_config=RetryConfig(max_attempts=3, initial_delay=0.01, max_delay=0.01, jitter=0))
    async def flaky(node_input: Any) -> str:
        attempts["n"] += 1
        raise ConnectionError("down")

    workflow = Workflow(name="retrying", edges=[(START, flaky)])
    runner = Runner(node=workflow, app_name="app", session_service=InMemorySessionService(), auto_create_session=True)
    message = types.Content(role="user", parts=[types.Part(text="tok")])
    with pytest.raises(ConnectionError):
        async for _ in runner.run_async(user_id="u", session_id="s", new_message=message):
            pass
    await runner.close()

    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_a_node_timeout_raises_node_timeout_error_which_is_why_the_run_deadline_is_the_only_bound() -> None:
    @node(name="slow", timeout=0.1)
    async def slow(node_input: Any) -> str:
        await asyncio.sleep(5)
        return "tok"

    workflow = Workflow(name="timing", edges=[(START, slow)])
    runner = Runner(node=workflow, app_name="app", session_service=InMemorySessionService(), auto_create_session=True)
    message = types.Content(role="user", parts=[types.Part(text="tok")])
    with pytest.raises(NodeTimeoutError):
        async for _ in runner.run_async(user_id="u", session_id="s", new_message=message):
            pass
    await runner.close()


@pytest.mark.asyncio
async def test_a_node_failure_is_logged_by_adk_with_the_exception_text(monkeypatch) -> None:
    """The reason agents/workflow.py installs a filter: ADK itself logs the raw exception text at ERROR.

    (The filter is process-wide once the engine has built a workflow, so it is detached here to see ADK's own behaviour.)
    """
    for name in ("google_adk.google.adk.workflow._node_runner", "google_adk.google.adk.runners"):
        adk_logger = logging.getLogger(name)
        monkeypatch.setattr(adk_logger, "filters", [f for f in adk_logger.filters if type(f).__name__ != "_DropFailureRecords"])
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Capture()
    root = logging.getLogger()
    root.addHandler(handler)

    async def failing() -> None:
        raise FileNotFoundError("/secret/path.pdf")

    try:
        with pytest.raises(FileNotFoundError):
            await drive([failing], [], name="logging_probe")
    finally:
        root.removeHandler(handler)

    loud = [r for r in records if r.name.startswith("google_adk") and r.levelno >= logging.ERROR and r.exc_info]
    assert {r.name for r in loud} == {"google_adk.google.adk.workflow._node_runner", "google_adk.google.adk.runners"}
    assert any("/secret/path.pdf" in "".join(__import__("traceback").format_exception(*r.exc_info)) for r in loud)


@pytest.mark.asyncio
async def test_a_workflow_object_can_be_shared_by_concurrent_runs() -> None:
    workflow = Workflow(name="shared", edges=[(START, make_node("a", ok, []), make_node("b", ok, []))])

    async def one(token: str) -> list[str]:
        runner = Runner(node=workflow, app_name="app", session_service=InMemorySessionService(), auto_create_session=True)
        outputs: list[str] = []
        message = types.Content(role="user", parts=[types.Part(text=token)])
        async for event in runner.run_async(user_id="u", session_id=token, new_message=message):
            outputs.append(event.output)
        await runner.close()
        return outputs

    results = await asyncio.gather(*[one(f"run-{i}") for i in range(6)])

    assert results == [[f"run-{i}", f"run-{i}"] for i in range(6)]
