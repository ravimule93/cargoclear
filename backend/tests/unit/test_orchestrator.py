"""Unit tests for the pipeline orchestrator, assessment API, and precedence rules."""

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.status import Status, resolve_status
from app.main import app
from app.services.orchestrator import start_run


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

        # Trigger analysis
        analyze_resp = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        assert analyze_resp.status_code == 202
        run_data = analyze_resp.json()
        assert run_data["run_id"].startswith("run-")

        # Allow background task to complete
        await asyncio.sleep(0.5)

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
