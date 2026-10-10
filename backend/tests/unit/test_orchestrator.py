"""Unit tests for the pipeline orchestrator, assessment API, and precedence rules."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.status import Status, resolve_status
from app.main import app
from app.repo import firestore
from app.services.orchestrator import start_run
from tests.helpers import wait_for_run


def test_status_precedence_complete_matrix():
    # 1. Material contradiction beats everything
    assert resolve_status([
        Status.COMPLIANT_FOR_SUBMISSION,
        Status.SPECIALIST_REVIEW_REQUIRED,
        Status.MISSING_EVIDENCE,
        Status.MATERIAL_CONTRADICTION,
    ]) == Status.MATERIAL_CONTRADICTION

    # 2. Missing evidence beats specialist review and compliant
    assert resolve_status([
        Status.COMPLIANT_FOR_SUBMISSION,
        Status.SPECIALIST_REVIEW_REQUIRED,
        Status.MISSING_EVIDENCE,
    ]) == Status.MISSING_EVIDENCE

    # 3. Specialist review beats compliant
    assert resolve_status([
        Status.COMPLIANT_FOR_SUBMISSION,
        Status.SPECIALIST_REVIEW_REQUIRED,
    ]) == Status.SPECIALIST_REVIEW_REQUIRED

    # 4. Clean list is compliant
    assert resolve_status([]) == Status.COMPLIANT_FOR_SUBMISSION


@pytest.mark.asyncio
async def test_full_analyze_pipeline_execution():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create bundle
        bnd_resp = await client.post(
            "/api/v1/bundles",
            json={"reference": "REF-ORCH-01", "destination_country": "SG"},
        )
        assert bnd_resp.status_code == 201
        bundle_id = bnd_resp.json()["id"]

        # Upload a document so the bundle is non-empty (empty bundle -> 422)
        fake_pdf = b"%PDF-1.5 Test invoice content"
        upload_resp = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files={"file": ("invoice.pdf", fake_pdf, "application/pdf")},
        )
        assert upload_resp.status_code == 201

        # Trigger analysis
        analyze_resp = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        assert analyze_resp.status_code == 202
        run_data = analyze_resp.json()
        assert run_data["run_id"].startswith("run-")

        # Wait for the background run to finish (polls the run state; no fixed sleep)
        final_state = await wait_for_run(bundle_id, run_data["run_id"])
        assert final_state["state"] == "COMPLETE", final_state
        assert await firestore.latest_iteration(bundle_id) is not None, "a completed run must persist an iteration"

        # Retrieve assessment
        assess_resp = await client.get(f"/api/v1/bundles/{bundle_id}/assessment")
        assert assess_resp.status_code == 200
        assessment = assess_resp.json()

        assert assessment["bundle_id"] == bundle_id
        assert assessment["iteration"] == 1
        assert "status" in assessment
        assert "checks" in assessment
        assert "confidence" in assessment

        # Retrieve iterations list
        iters_resp = await client.get(f"/api/v1/bundles/{bundle_id}/iterations")
        assert iters_resp.status_code == 200
        assert len(iters_resp.json()) >= 1


@pytest.mark.asyncio
async def test_run_context_carries_no_unused_uploaded_types(monkeypatch):
    """ctx["uploaded_types"] was set at the start of a run and never read by any stage; it is gone."""
    from app.services import orchestrator

    captured: dict = {}

    async def capture(ctx):
        captured.update(ctx)

    monkeypatch.setattr(orchestrator, "_execute_pipeline", capture)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bundle_id = (await client.post("/api/v1/bundles", json={"reference": "CTX"})).json()["id"]
        await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files={"file": ("invoice.pdf", b"%PDF-1.5 ctx test", "application/pdf")},
        )
        await start_run(bundle_id)
        for task in list(orchestrator._RUNNING_TASKS):
            await task

    assert captured["bundle_id"] == bundle_id
    assert "uploaded_types" not in captured
    assert {"run_id", "mode", "iteration", "documents", "previous_iteration"} <= set(captured)
