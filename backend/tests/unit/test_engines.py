"""The pipeline-engine seam: PIPELINE_ENGINE, services/engines.py and the orchestrator's ``_stage`` (B1-B4).

Everything here runs without google-adk. The ADK engine itself is tested in tests/adk (skipped without the ADK lock).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.core.config import Settings, settings
from app.main import create_app
from app.repo import firestore
from app.services import engines, orchestrator
from tests.helpers import api_client, create_bundle_with_documents, wait_for_run

BACKEND = Path(__file__).resolve().parents[2]
FILES = {"commercial_invoice.pdf": b"%PDF-1.4 engine invoice", "packing_list.pdf": b"%PDF-1.4 engine packing"}
STAGES = ["preprocess", "extract", "discrepancy", "ground", "confidence", "synthesize"]


# ---------------------------------------------------------------------------
# B1: the setting
# ---------------------------------------------------------------------------


def test_the_default_engine_is_native(monkeypatch) -> None:
    monkeypatch.delenv("PIPELINE_ENGINE", raising=False)  # the suite may run with PIPELINE_ENGINE=adk in the environment

    assert Settings(_env_file=None).pipeline_engine == "native"


def test_adk_is_accepted() -> None:
    assert Settings(_env_file=None, PIPELINE_ENGINE="adk").pipeline_engine == "adk"


@pytest.mark.parametrize("bad", ["", "ADK", "langgraph", "native,adk", "none"])
def test_any_other_engine_name_is_a_startup_error(bad) -> None:
    with pytest.raises(ValueError, match="pipeline_engine|PIPELINE_ENGINE"):
        Settings(_env_file=None, PIPELINE_ENGINE=bad)


def test_importing_the_app_with_a_bad_engine_name_fails_at_startup() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"], cwd=BACKEND, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "PIPELINE_ENGINE": "langgraph", "APP_MODE": "demo"},
    )

    assert result.returncode != 0 and "pipeline_engine" in result.stderr.lower()


def test_the_env_example_documents_the_engine() -> None:
    text = (BACKEND / ".env.example").read_text()

    assert "PIPELINE_ENGINE=native" in text and "requirements-adk.txt" in text


@pytest.mark.asyncio
async def test_meta_reports_the_engine(monkeypatch) -> None:
    async with api_client() as client:
        initial = settings.pipeline_engine
        body = (await client.get("/api/v1/meta")).json()
        monkeypatch.setattr(settings, "pipeline_engine", "adk" if settings.pipeline_engine == "native" else "native")
        other = settings.pipeline_engine
        switched = (await client.get("/api/v1/meta")).json()

    assert body["pipeline_engine"] == initial
    assert initial in ("native", "adk")  # whichever the process was started with
    assert set(body) == {"app_mode", "data_source_policy", "pipeline_engine"}
    assert switched["pipeline_engine"] == other


# ---------------------------------------------------------------------------
# B2: services/engines.py
# ---------------------------------------------------------------------------


def test_get_engine_selects_by_name() -> None:
    assert engines.get_engine("native") is engines.run_native
    assert engines.get_engine("adk") is engines.run_adk


@pytest.mark.parametrize("bad", ["", "ADK", "langgraph"])
def test_get_engine_rejects_an_unknown_name(bad) -> None:
    with pytest.raises(ValueError, match="unknown pipeline engine"):
        engines.get_engine(bad)


@pytest.mark.asyncio
async def test_the_native_engine_calls_each_stage_once_in_order_and_threads_the_ctx() -> None:
    calls: list[tuple[str, int]] = []

    async def run_stage(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        calls.append((stage, ctx["n"]))
        return {**ctx, "n": ctx["n"] + 1}  # a stage may hand back a NEW dict: the next stage must get that one

    result = await engines.run_native({"n": 0}, STAGES, run_stage)

    assert calls == [(stage, index) for index, stage in enumerate(STAGES)]
    assert result == {"n": len(STAGES)}


@pytest.mark.asyncio
async def test_the_native_engine_lets_an_exception_through_unchanged_and_stops() -> None:
    boom = FileNotFoundError("/secret/path.pdf")
    seen: list[str] = []

    async def run_stage(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        seen.append(stage)
        if stage == "ground":
            raise boom
        return ctx

    with pytest.raises(FileNotFoundError) as raised:
        await engines.run_native({}, STAGES, run_stage)

    assert raised.value is boom and seen == ["preprocess", "extract", "discrepancy", "ground"]


@pytest.mark.asyncio
async def test_the_native_engine_lets_cancellation_through() -> None:
    async def run_stage(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(30)
        return ctx

    task = asyncio.ensure_future(engines.run_native({}, STAGES, run_stage))
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_the_native_engine_with_no_stages_returns_the_ctx() -> None:
    ctx = {"a": 1}

    assert await engines.run_native(ctx, [], lambda *_: None) is ctx  # type: ignore[arg-type,return-value]


@pytest.mark.asyncio
async def test_run_adk_without_google_adk_says_what_to_install(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "google.adk", None)  # an import of google.adk now raises ImportError

    with pytest.raises(ImportError):
        await engines.run_adk({}, STAGES, lambda *_: None)  # type: ignore[arg-type,return-value]


# ---------------------------------------------------------------------------
# B3: fail fast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_app_refuses_to_start_with_the_adk_engine_when_google_adk_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "pipeline_engine", "adk")
    monkeypatch.setitem(sys.modules, "google.adk", None)  # the importer finds nothing
    application = create_app()

    with pytest.raises(RuntimeError) as raised:
        async with application.router.lifespan_context(application):
            pytest.fail("the server must not start misconfigured")

    assert str(raised.value) == (
        "PIPELINE_ENGINE=adk but google-adk is not installed: use the ADK lock (requirements-adk.txt)"
    )
    assert isinstance(raised.value.__cause__, ImportError)


@pytest.mark.asyncio
async def test_the_app_starts_with_the_adk_engine_when_google_adk_imports(monkeypatch) -> None:
    monkeypatch.setattr(settings, "pipeline_engine", "adk")
    monkeypatch.setitem(sys.modules, "google.adk", types.ModuleType("google.adk"))
    application = create_app()

    async with application.router.lifespan_context(application):
        pass


@pytest.mark.asyncio
async def test_the_native_engine_never_looks_for_google_adk(monkeypatch) -> None:
    monkeypatch.setattr(settings, "pipeline_engine", "native")
    monkeypatch.setitem(sys.modules, "google.adk", None)
    application = create_app()

    async with application.router.lifespan_context(application):
        pass


def test_agents_workflow_imports_without_google_adk() -> None:
    code = "import sys; sys.modules['google.adk'] = None; import app.agents.workflow as w; print(sorted(n for n in dir(w) if n in ('build_workflow', 'run_adk')))"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "APP_MODE": "demo"},
    )

    assert result.returncode == 0, result.stderr
    assert "build_workflow" in result.stdout and "run_adk" in result.stdout


# ---------------------------------------------------------------------------
# B2/B4: the orchestrator's _stage and the engine call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_orchestrator_picks_the_engine_once_per_run_and_hands_it_the_stage_callable(monkeypatch) -> None:
    picked: list[str] = []
    received: dict[str, Any] = {}

    async def recording_engine(ctx, stages, run_stage):
        received.update(stages=list(stages), run_stage=run_stage)
        return await engines.run_native(ctx, stages, run_stage)

    def get_engine(name: str):
        picked.append(name)
        return recording_engine

    monkeypatch.setattr(orchestrator, "get_engine", get_engine)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)

    assert state["state"] == "COMPLETE"
    assert picked == [settings.pipeline_engine], "once per run"
    assert received["stages"] == orchestrator.PIPELINE_STAGES == STAGES
    assert callable(received["run_stage"])


@pytest.mark.asyncio
async def test_a_stage_is_claim_checked_then_announced_then_worked_then_logged(monkeypatch) -> None:
    order: list[str] = []
    real_claim, real_stage, real_dispatch = orchestrator._ensure_claim, firestore.set_run_stage, orchestrator.dispatch

    async def claim(bundle_id: str, run_id: str, fence: int | None = None) -> None:
        order.append("claim")
        await real_claim(bundle_id, run_id, fence)

    async def stage_write(bundle_id, run_id, stage, progress):
        order.append(f"progress:{stage}")
        return await real_stage(bundle_id, run_id, stage=stage, progress=progress)

    async def work(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        order.append(f"work:{stage}")
        return await real_dispatch(stage, ctx)

    monkeypatch.setattr(orchestrator, "_ensure_claim", claim)
    monkeypatch.setattr(firestore, "set_run_stage", stage_write)
    monkeypatch.setattr(orchestrator, "dispatch", work)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        order.clear()
        with capture_logs() as logs:
            run_id = await orchestrator.start_run(bundle_id)
            await wait_for_run(bundle_id, run_id)

    for stage in STAGES:
        at = order.index(f"progress:{stage}")
        assert order[at - 1] == "claim", f"{stage}: the claim is checked right before the progress write"
        assert order.index(f"work:{stage}") > at, f"{stage}: progress is written BEFORE the work"
    finished = [e for e in logs if e["event"] == "stage_finished"]
    assert [e["stage"] for e in finished] == STAGES
    assert all(e["run_id"] == run_id and e["duration_ms"] >= 0 and e["log_level"] == "info" for e in finished)


@pytest.mark.asyncio
async def test_stage_finished_is_not_logged_for_a_stage_that_failed(monkeypatch) -> None:
    real = orchestrator.dispatch

    async def failing(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        if stage == "ground":
            raise RuntimeError("boom")
        return await real(stage, ctx)

    monkeypatch.setattr(orchestrator, "dispatch", failing)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        with capture_logs() as logs:
            run_id = await orchestrator.start_run(bundle_id)
            state = await wait_for_run(bundle_id, run_id)

    assert state["state"] == "ERROR"
    assert [e["stage"] for e in logs if e["event"] == "stage_finished"] == ["preprocess", "extract", "discrepancy"]


@pytest.mark.asyncio
async def test_the_tracker_names_the_failing_stage_in_the_audit_event(monkeypatch) -> None:
    real = orchestrator.dispatch

    async def failing(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        if stage == "confidence":
            raise RuntimeError("boom")
        return await real(stage, ctx)

    monkeypatch.setattr(orchestrator, "dispatch", failing)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        await wait_for_run(bundle_id, run_id)
        events = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["events"]

    [failed] = [e for e in events if e["event_type"] == "ANALYSIS_FAILED"]
    assert failed["payload"]["stage"] == "confidence"
