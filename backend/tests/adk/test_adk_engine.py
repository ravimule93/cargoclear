"""app/agents/workflow.py: the ADK engine (C1-C4), driven with fake stage callables (no orchestrator)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from structlog.testing import capture_logs

from tests.adk.conftest import require_adk

require_adk()

from app.agents import workflow  # noqa: E402
from app.gateway.errors import ExtractionError  # noqa: E402
from app.services import engines  # noqa: E402

STAGES = ["preprocess", "extract", "discrepancy", "ground", "confidence", "synthesize"]


def live_tasks(before: set[asyncio.Task]) -> list[asyncio.Task]:
    return [t for t in asyncio.all_tasks() - before if not t.done()]


class Recorder:
    """A run_stage that records the order and threads a counter through the ctx."""

    def __init__(self, fail_at: str | None = None, error: BaseException | None = None, stall_at: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_at, self.error, self.stall_at = fail_at, error, stall_at
        self.cancelled_in: str | None = None

    async def __call__(self, stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(stage)
        if stage == self.stall_at:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                self.cancelled_in = stage
                raise
        if stage == self.fail_at:
            raise self.error  # type: ignore[misc]
        return {**ctx, "trail": [*ctx.get("trail", []), stage]}  # a NEW dict each time: the next node must get this one


# ---------------------------------------------------------------------------
# C1: build_workflow
# ---------------------------------------------------------------------------


def test_the_workflow_is_named_and_has_one_function_node_per_stage_in_order() -> None:
    flow = workflow.build_workflow(STAGES)

    assert flow.name == "cargoclear_pipeline"
    names = [n.name for n in flow.graph.nodes if n.name != "__START__"]
    assert names == STAGES


def test_the_workflow_is_a_chain_from_start_in_stage_order() -> None:
    flow = workflow.build_workflow(STAGES)
    edges = {(e.from_node.name, e.to_node.name) for e in flow.graph.edges}

    assert edges == {("__START__", "preprocess"), *zip(STAGES, STAGES[1:], strict=False)}


def test_the_workflow_is_built_once_per_process() -> None:
    assert workflow.build_workflow(STAGES) is workflow.build_workflow(list(STAGES))
    assert workflow.build_workflow(STAGES[:2]) is not workflow.build_workflow(STAGES)


def test_no_node_has_a_retry_config_or_a_timeout() -> None:
    """Extraction has its own retry policy and the run deadline is the bound (module docstring)."""
    flow = workflow.build_workflow(STAGES)

    for stage_node in flow.graph.nodes:
        assert getattr(stage_node, "retry_config", None) is None, stage_node.name
        assert getattr(stage_node, "timeout", None) is None, stage_node.name
    assert getattr(flow, "retry_config", None) is None and getattr(flow, "timeout", None) is None


# ---------------------------------------------------------------------------
# C2: run_adk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stages_run_once_each_in_order_and_the_returned_ctx_is_threaded_through() -> None:
    recorder = Recorder()

    result = await workflow.run_adk({"run_id": "run-1"}, STAGES, recorder)

    assert recorder.calls == STAGES
    assert result["trail"] == STAGES, "each node got the ctx the previous stage returned, and the final one is returned"
    assert result["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_the_heavy_ctx_never_travels_through_adk() -> None:
    """Only the token is an ADK event output / log value; the bytes and objects stay in the registry."""
    secret = b"%PDF-SECRET-CONTENT"
    ctx = {"run_id": "run-heavy", "processed_pages": [{"payload": secret}], "blob": object()}
    with capture_logs() as logs:
        await workflow.run_adk(ctx, STAGES, Recorder())

    events = [e for e in logs if e["event"] == "adk_event"]
    assert [e["path"] for e in events] == [f"cargoclear_pipeline@1/{stage}@1" for stage in STAGES]
    assert all(set(e) == {"event", "log_level", "run_id", "path"} for e in events), "a run id and a path, never content"
    assert "SECRET" not in str(logs)


@pytest.mark.asyncio
async def test_an_exception_reaches_the_caller_unchanged_and_stops_the_run() -> None:
    boom = ExtractionError("Extraction failed for document d1 after 3 attempts", detail={"document_id": "d1"})
    recorder = Recorder(fail_at="ground", error=boom)

    with pytest.raises(ExtractionError) as raised:
        await workflow.run_adk({"run_id": "run-fail"}, STAGES, recorder)

    assert raised.value is boom and raised.value.code == "EXTRACTION_FAILED" and raised.value.detail == {"document_id": "d1"}
    assert recorder.calls == ["preprocess", "extract", "discrepancy", "ground"]


@pytest.mark.asyncio
async def test_a_failure_is_not_logged_a_second_time_by_adk() -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Capture()
    logging.getLogger().addHandler(handler)
    try:
        with pytest.raises(FileNotFoundError):
            await workflow.run_adk(
                {"run_id": "run-quiet"}, STAGES, Recorder(fail_at="extract", error=FileNotFoundError("/secret/path.pdf"))
            )
    finally:
        logging.getLogger().removeHandler(handler)

    leaked = [r for r in records if r.name.startswith("google_adk") and r.levelno >= logging.ERROR and r.exc_info]
    assert leaked == [], "the exception text is logged once, by the orchestrator, not again by ADK"
    assert not any("/secret/path.pdf" in r.getMessage() for r in records if r.name.startswith("google_adk"))


@pytest.mark.asyncio
async def test_other_adk_log_records_are_left_alone() -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.INFO)
    try:
        await workflow.run_adk({"run_id": "run-info"}, STAGES, Recorder())
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)

    assert any(r.name.startswith("google_adk") and r.levelno == logging.INFO for r in records), "ADK's info records pass"


@pytest.mark.asyncio
async def test_cancellation_reaches_the_running_node() -> None:
    recorder = Recorder(stall_at="extract")
    before = set(asyncio.all_tasks())
    task = asyncio.ensure_future(workflow.run_adk({"run_id": "run-cancel"}, STAGES, recorder))
    await asyncio.sleep(0.3)
    assert recorder.calls == ["preprocess", "extract"]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.2)

    assert recorder.cancelled_in == "extract"
    assert recorder.calls == ["preprocess", "extract"], "nothing after the cancelled stage ran"
    assert live_tasks(before) == []


@pytest.mark.asyncio
async def test_a_deadline_around_run_adk_cancels_the_node_and_raises_timeout() -> None:
    recorder = Recorder(stall_at="discrepancy")

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.4):
            await workflow.run_adk({"run_id": "run-deadline"}, STAGES, recorder)

    assert recorder.cancelled_in == "discrepancy"


# ---------------------------------------------------------------------------
# C4: nothing is left behind
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_registry_and_the_task_list_are_empty_after_success() -> None:
    before = set(asyncio.all_tasks())

    await workflow.run_adk({"run_id": "run-clean-1"}, STAGES, Recorder())
    await asyncio.sleep(0.1)

    assert workflow._RUNS == {} and live_tasks(before) == []


@pytest.mark.asyncio
async def test_the_registry_and_the_task_list_are_empty_after_failure() -> None:
    before = set(asyncio.all_tasks())

    with pytest.raises(RuntimeError):
        await workflow.run_adk({"run_id": "run-clean-2"}, STAGES, Recorder(fail_at="synthesize", error=RuntimeError("x")))
    await asyncio.sleep(0.1)

    assert workflow._RUNS == {} and live_tasks(before) == []


@pytest.mark.asyncio
async def test_the_registry_and_the_task_list_are_empty_after_cancellation() -> None:
    before = set(asyncio.all_tasks())
    task = asyncio.ensure_future(workflow.run_adk({"run_id": "run-clean-3"}, STAGES, Recorder(stall_at="ground")))
    await asyncio.sleep(0.3)
    assert "run-clean-3" in workflow._RUNS, "registered while running"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.2)

    assert workflow._RUNS == {} and live_tasks(before) == []


@pytest.mark.asyncio
async def test_the_registry_entry_is_removed_even_if_the_workflow_cannot_be_built(monkeypatch) -> None:
    def broken(_stages):
        raise RuntimeError("cannot build")

    monkeypatch.setattr(workflow, "build_workflow", broken)

    with pytest.raises(RuntimeError, match="cannot build"):
        await workflow.run_adk({"run_id": "run-clean-4"}, STAGES, Recorder())

    assert workflow._RUNS == {}


@pytest.mark.asyncio
async def test_a_runner_that_cannot_close_does_not_replace_the_exception_that_is_propagating(monkeypatch) -> None:
    from google.adk import Runner

    async def broken_close(self) -> None:
        raise OSError("close failed")

    monkeypatch.setattr(Runner, "close", broken_close)
    boom = ValueError("the real failure")

    with capture_logs() as logs:
        with pytest.raises(ValueError) as raised:
            await workflow.run_adk({"run_id": "run-close"}, STAGES, Recorder(fail_at="extract", error=boom))

    assert raised.value is boom and workflow._RUNS == {}
    assert [e["error_type"] for e in logs if e["event"] == "adk_runner_close_failed"] == ["OSError"]


@pytest.mark.asyncio
async def test_concurrent_runs_keep_their_own_ctx() -> None:
    async def one(index: int) -> dict[str, Any]:
        return await workflow.run_adk({"run_id": f"run-par-{index}", "mine": index}, STAGES, Recorder())

    results = await asyncio.gather(*[one(i) for i in range(5)])

    assert [r["mine"] for r in results] == list(range(5)) and all(r["trail"] == STAGES for r in results)
    assert workflow._RUNS == {}


# ---------------------------------------------------------------------------
# the seam
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_engine_seam_reaches_the_adk_engine() -> None:
    engine = engines.get_engine("adk")
    result = await engine({"run_id": "run-seam"}, STAGES, Recorder())

    assert result["trail"] == STAGES


def test_the_node_reads_the_token_from_the_start_message_or_the_previous_output() -> None:
    from google.genai import types

    assert workflow._token_of("run-1") == "run-1"
    assert workflow._token_of(types.Content(role="user", parts=[types.Part(text="run-2")])) == "run-2"
    with pytest.raises(LookupError):
        workflow._token_of(None)
    with pytest.raises(LookupError):
        workflow._token_of(types.Content(role="user", parts=[]))


@pytest.mark.asyncio
async def test_engines_require_engine_accepts_adk_when_it_imports() -> None:
    engines.require_engine("adk")
