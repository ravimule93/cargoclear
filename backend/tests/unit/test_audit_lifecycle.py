"""Audit lifecycle of one pipeline run (B2).

Expected shape of a successful run:
    ANALYSIS_STARTED -> [stages] -> finalize -> iteration persisted -> ASSESSMENT_COMPLETED -> run COMPLETE
A failed run records ANALYSIS_FAILED and never ASSESSMENT_COMPLETED.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.gateway import dispatch as dispatch_module
from app.repo import firestore
from app.services import audit, orchestrator
from tests.helpers import api_client, audit_event_types, create_bundle_with_documents, wait_for_run

FILES = {
    "commercial_invoice.pdf": b"%PDF-1.4 lifecycle invoice",
    "bill_of_lading.pdf": b"%PDF-1.4 lifecycle bol",
    "packing_list.pdf": b"%PDF-1.4 lifecycle packing",
}


async def _run_to_completion(client, bundle_id: str) -> dict[str, Any]:
    run_id = await orchestrator.start_run(bundle_id)
    return await wait_for_run(bundle_id, run_id)


@pytest.mark.asyncio
async def test_successful_run_ends_with_started_then_completed_and_no_system_event() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        state = await _run_to_completion(client, bundle_id)
        assert state["state"] == "COMPLETE", state

        types = await audit_event_types(client, bundle_id)

    assert types[-2:] == ["ANALYSIS_STARTED", "ASSESSMENT_COMPLETED"], types
    assert "SYSTEM_EVENT" not in types
    assert types.count("ANALYSIS_STARTED") == types.count("ASSESSMENT_COMPLETED") == 1


@pytest.mark.asyncio
async def test_two_runs_each_record_one_started_and_one_completed() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        assert (await _run_to_completion(client, bundle_id))["state"] == "COMPLETE"
        assert (await _run_to_completion(client, bundle_id))["state"] == "COMPLETE"
        types = await audit_event_types(client, bundle_id)

    lifecycle = [t for t in types if t.startswith("ANALYSIS_") or t == "ASSESSMENT_COMPLETED"]
    assert lifecycle == ["ANALYSIS_STARTED", "ASSESSMENT_COMPLETED"] * 2


def test_generic_audit_stage_is_gone_from_the_pipeline() -> None:
    assert "audit" not in orchestrator.PIPELINE_STAGES
    assert "audit" not in dispatch_module._get_handlers()
    assert orchestrator.PIPELINE_STAGES[-1] == "synthesize"


@pytest.mark.asyncio
async def test_finalize_order_is_stage_then_iteration_then_audit_then_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

    calls: list[tuple[str, Any]] = []
    real_stage, real_write, real_state, real_record = (
        firestore.set_run_stage,
        firestore.write_iteration,
        firestore.set_run_state,
        audit.record,
    )

    async def spy_stage(bundle_id, run_id, stage, progress):
        calls.append(("stage", (stage, progress)))
        return await real_stage(bundle_id, run_id, stage=stage, progress=progress)

    async def spy_write(ctx):
        calls.append(("write_iteration", ctx["iteration"]))
        return await real_write(ctx)

    async def spy_state(bundle_id, run_id, state, progress, only_if_state=None, fence=None):
        calls.append(("run_state", (state, progress)))
        return await real_state(bundle_id, run_id, state=state, progress=progress, only_if_state=only_if_state, fence=fence)

    async def spy_record(ctx):
        calls.append(("audit", ctx.get("audit_event_type")))
        return await real_record(ctx)

    monkeypatch.setattr(firestore, "set_run_stage", spy_stage)
    monkeypatch.setattr(firestore, "write_iteration", spy_write)
    monkeypatch.setattr(firestore, "set_run_state", spy_state)
    monkeypatch.setattr(audit, "record", spy_record)

    run_id = await orchestrator.start_run(bundle_id)
    state = await wait_for_run(bundle_id, run_id)
    assert state["state"] == "COMPLETE"

    kinds = [c[0] for c in calls]
    stages = [c[1][0] for c in calls if c[0] == "stage"]
    assert stages[-2:] == ["synthesize", "finalize"], stages
    assert ("stage", ("finalize", 0.98)) in calls

    # strictly: ... finalize -> write_iteration -> audit ASSESSMENT_COMPLETED -> run COMPLETE (1.0)
    tail = calls[calls.index(("stage", ("finalize", 0.98))):]
    assert tail == [
        ("stage", ("finalize", 0.98)),
        ("write_iteration", 1),
        ("audit", "ASSESSMENT_COMPLETED"),
        ("run_state", ("COMPLETE", 1.0)),
    ], tail
    # ANALYSIS_STARTED is recorded before the first pipeline stage runs, and nothing else is audited
    assert calls.index(("audit", "ANALYSIS_STARTED")) < calls.index(("stage", ("preprocess", 0.15)))
    assert [c[1] for c in calls if c[0] == "audit"] == ["ANALYSIS_STARTED", "ASSESSMENT_COMPLETED"]
    assert kinds.count("write_iteration") == 1


@pytest.mark.asyncio
async def test_forced_failure_records_analysis_failed_and_no_assessment_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

        real_dispatch = orchestrator.dispatch

        async def exploding_dispatch(stage, ctx):
            if stage == "discrepancy":
                raise RuntimeError("rules engine exploded")
            return await real_dispatch(stage, ctx)

        monkeypatch.setattr(orchestrator, "dispatch", exploding_dispatch)

        state = await _run_to_completion(client, bundle_id)
        types = await audit_event_types(client, bundle_id)
        events = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        assessment = await client.get(f"/api/v1/bundles/{bundle_id}/assessment")

    assert state["state"] == "ERROR"
    # a non-domain exception is never shown: clients get a fixed text and a reference into the operator's log
    assert state["message"] == f"The analysis failed unexpectedly (reference: {state['run_id']})."
    assert "rules engine exploded" not in state["message"]
    assert types[-2:] == ["ANALYSIS_STARTED", "ANALYSIS_FAILED"], types
    assert "ASSESSMENT_COMPLETED" not in types
    assert "SYSTEM_EVENT" not in types
    failed = events["events"][-1]
    assert failed["payload"] == {
        "run_id": state["run_id"], "mode": "full", "stage": "discrepancy", "error_type": "RuntimeError",
        "code": "INTERNAL_ERROR", "message": f"The analysis failed unexpectedly (reference: {state['run_id']}).",
    }
    assert "rules engine exploded" not in str(events), "the immutable audit log must not hold the raw exception text"
    assert events["verified"] is True
    assert assessment.status_code == 404, "a failed run must not leave an iteration behind"


@pytest.mark.asyncio
async def test_audit_failure_never_masks_the_original_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

    real_dispatch, real_record = orchestrator.dispatch, audit.record

    async def exploding_dispatch(stage, ctx):
        if stage == "extract":
            raise RuntimeError("original failure")
        return await real_dispatch(stage, ctx)

    async def failing_audit(ctx):
        if ctx.get("audit_event_type") == "ANALYSIS_FAILED":
            raise OSError("audit store is down")
        return await real_record(ctx)

    monkeypatch.setattr(orchestrator, "dispatch", exploding_dispatch)
    monkeypatch.setattr(audit, "record", failing_audit)

    run_id = await orchestrator.start_run(bundle_id)
    state = await wait_for_run(bundle_id, run_id)

    assert state["state"] == "ERROR"
    assert state["message"] == f"The analysis failed unexpectedly (reference: {run_id})."  # the original failure, not the audit one
    assert "audit store is down" not in state["message"]


@pytest.mark.asyncio
async def test_assessment_completed_is_never_written_when_the_iteration_was_not_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

        async def failing_write(_ctx):
            raise OSError("firestore write failed")

        monkeypatch.setattr(firestore, "write_iteration", failing_write)

        state = await _run_to_completion(client, bundle_id)
        types = await audit_event_types(client, bundle_id)

    assert state["state"] == "ERROR"
    assert "ASSESSMENT_COMPLETED" not in types
    assert types[-1] == "ANALYSIS_FAILED"


@pytest.mark.asyncio
async def test_failure_before_the_first_stage_is_still_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """ANALYSIS_STARTED lives inside the try block: if it cannot be written the run ends in ERROR, not limbo."""
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

    real_record = audit.record

    async def failing_started(ctx):
        if ctx.get("audit_event_type") == "ANALYSIS_STARTED":
            raise OSError("audit store is down")
        return await real_record(ctx)

    monkeypatch.setattr(audit, "record", failing_started)

    run_id = await orchestrator.start_run(bundle_id)
    state = await wait_for_run(bundle_id, run_id)

    assert state["state"] == "ERROR"
    assert state["message"] == f"The analysis failed unexpectedly (reference: {run_id})."
    assert "audit store is down" not in state["message"]
