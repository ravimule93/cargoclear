"""Integration test for Hero Demo Case C (End-to-End Adjudication Journey).

Case C sequence:
  1. Upload initial 3-document bundle for HS 7304 (Invoice + BoL + Packing List).
  2. POST /analyze -> Pipeline evaluates math parity (PASS), detects missing Mill Test Cert.
  3. Status: MISSING_EVIDENCE.
  4. Upload missing Mill Test Certificate (MTC).
  5. POST /reassess -> Pipeline re-evaluates all documents.
  6. Status: COMPLIANT_FOR_SUBMISSION.
  7. Verify Reasoning Delta reflects: MISSING_EVIDENCE -> COMPLIANT_FOR_SUBMISSION with explanation.
"""

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_case_c_hero_demo_journey():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Create shipment bundle
        bnd_resp = await client.post(
            "/api/v1/bundles",
            json={"reference": "HERO-CASE-C-7304", "destination_country": "SG"},
        )
        assert bnd_resp.status_code == 201
        bundle_id = bnd_resp.json()["id"]

        # Step 2: Upload initial documents (Invoice, BoL, Packing List)
        fake_pdf = b"%PDF-1.4 Mock Payload"

        inv_resp = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files={"file": ("commercial_invoice.pdf", fake_pdf, "application/pdf")},
        )
        assert inv_resp.status_code == 201

        bol_resp = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files={"file": ("bill_of_lading.pdf", fake_pdf, "application/pdf")},
        )
        assert bol_resp.status_code == 201

        pl_resp = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files={"file": ("packing_list.pdf", fake_pdf, "application/pdf")},
        )
        assert pl_resp.status_code == 201

        # Step 3: Trigger first analysis
        analyze_resp = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        assert analyze_resp.status_code == 202

        # Allow background pipeline to finish
        await asyncio.sleep(0.6)

        # Step 4: Verify Iteration 1 is MISSING_EVIDENCE
        iter1_resp = await client.get(f"/api/v1/bundles/{bundle_id}/assessment")
        assert iter1_resp.status_code == 200
        iter1 = iter1_resp.json()

        assert iter1["iteration"] == 1
        assert iter1["status"] == "MISSING_EVIDENCE"
        assert len(iter1["missing_evidence"]) >= 1
        assert iter1["missing_evidence"][0]["id"] == "ME-MILL_TEST_CERTIFICATE"
        assert iter1["reasoning_delta"]["kind"] == "INITIAL"

        # Step 5: Upload the missing Mill Test Certificate (MTC)
        mtc_resp = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files={"file": ("mtc_pipe_test_cert.pdf", fake_pdf, "application/pdf")},
        )
        assert mtc_resp.status_code == 201

        # Step 6: Trigger reassessment
        reassess_resp = await client.post(f"/api/v1/bundles/{bundle_id}/reassess")
        assert reassess_resp.status_code == 202

        # Allow reassessment pipeline to finish
        await asyncio.sleep(0.6)

        # Step 7: Verify Iteration 2 is COMPLIANT_FOR_SUBMISSION with Reasoning Delta
        iter2_resp = await client.get(f"/api/v1/bundles/{bundle_id}/assessment")
        assert iter2_resp.status_code == 200
        iter2 = iter2_resp.json()

        assert iter2["iteration"] == 2
        assert iter2["status"] == "COMPLIANT_FOR_SUBMISSION"
        assert len(iter2["missing_evidence"]) == 0

        # Check Reasoning Delta
        delta = iter2["reasoning_delta"]
        assert delta is not None
        assert delta["kind"] == "REASSESSMENT"
        assert any(c["field"] == "status" for c in delta["changes"])
        assert any(c["to"] == "COMPLIANT_FOR_SUBMISSION" for c in delta["changes"])
        assert any("MILL_TEST_CERTIFICATE" in c["field"] for c in delta["changes"])
