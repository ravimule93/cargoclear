"""The declaration pre-fill pack through the real app: Case D (not cleared), a correction, and Case C (cleared)."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.services import audit
from app.services.prefill import content_hash
from app.domain.prefill import PrefillPack
from tests.helpers import api_client, case_c_pdf, wait_for_run

from .test_case_d_e2e import analyse_case_d
from .test_corrections_e2e import _find_cell, _recompute


@pytest.mark.asyncio
async def test_case_d_pack_says_not_cleared_and_gives_the_values_with_their_sources() -> None:
    async with api_client() as client:
        bundle_id, assessment = await analyse_case_d(client)
        response = await client.get(f"/api/v1/bundles/{bundle_id}/prefill")
        downloaded = await client.get(f"/api/v1/bundles/{bundle_id}/prefill?download=true")
        audit_events = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["events"]

    assert response.status_code == 200 and "content-disposition" not in response.headers
    assert downloaded.headers["content-disposition"] == f'attachment; filename="cargoclear-prefill-{bundle_id}-assessment1.json"'
    pack = PrefillPack.model_validate(response.json())

    assert pack.banner is not None and pack.banner.startswith("NOT CLEARED. The assessment is material contradiction")
    assert pack.assessment.status == "MATERIAL_CONTRADICTION" and pack.assessment.iteration == 1
    assert [f.check_id for f in pack.assessment.blocking] == ["M-001"] and [f.check_id for f in pack.assessment.review] == ["SEC-002"]
    assert pack.declaration.declaration == "Import declaration (Bill of Entry)" and pack.declaration.destination_country == "IN"
    assert {i.id for i in pack.to_be_supplied} >= {"IEC", "GSTIN", "CHA"}

    assert pack.parties.consignee.value == "MUMBAI INFRA PIPING PVT LTD" and pack.parties.consignor.value == "TIANJIN HUAXING STEEL TUBE CO LTD"
    assert pack.parties.consignee.source and pack.parties.consignee.source.filename == "case_d_commercial_invoice.pdf"
    assert pack.shipment.total_gross_weight.value == "25400" and pack.shipment.total_gross_weight.unit == "KGS"
    assert pack.shipment.incoterm.value == "FOB TIANJIN" and pack.shipment.country_of_origin.value == "CHINA"
    assert pack.commercial.invoice_value.value == "61500" and pack.commercial.invoice_currency.value == "USD"

    # the declared (non-alloy) HS code is on the line, flagged by the finding that contradicts it
    assert [l.hs_code.value for l in pack.lines] == ["73043100"]
    assert pack.lines[0].hs_code.review == ["M-001 (material) cites this value", "SEC-002 (warn) cites this value"]
    assert pack.material.heat_numbers == ["TH-77120", "TH-77121"] and pack.material.specification.value == "ASTM A106 GR B"

    # the estimate is the assessment's, copied as it is
    assert pack.valuation is not None and pack.valuation.model_dump(mode="json") == assessment["valuation"]
    assert len(pack.documents) == 4 and all(len(d.sha256) == 64 for d in pack.documents)

    # tied to the audit trail it was made from, and verifiable from the file alone
    assert pack.provenance.audit_events == len(audit_events) and pack.provenance.audit_head_hash == audit_events[-1]["hash"]
    assert pack.provenance.audit_chain_verified is True
    assert content_hash(pack) == pack.integrity.content_sha256
    assert hashlib.sha256(audit.canonical_json({k: v for k, v in response.json().items() if k != "integrity"}).encode()).hexdigest() == pack.integrity.content_sha256


@pytest.mark.asyncio
async def test_a_correction_reaches_the_pack_only_after_the_recompute_and_says_so_meanwhile() -> None:
    async with api_client() as client:
        bundle_id, _ = await analyse_case_d(client)
        document_id, row, _cell = await _find_cell(client, bundle_id, "TH-77121", "Cr")
        docs = (await client.get(f"/api/v1/bundles/{bundle_id}/extractions")).json()
        invoice = next(d for d in docs if d["doc_type"] == "COMMERCIAL_INVOICE")
        await client.post(f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": invoice["document_id"], "path": "consignee", "value": "MUMBAI INFRA PIPING LLP", "reason": "name on the stamp"})
        before = (await client.get(f"/api/v1/bundles/{bundle_id}/prefill")).json()
        await _recompute(client, bundle_id)
        after = (await client.get(f"/api/v1/bundles/{bundle_id}/prefill")).json()
        first_again = (await client.get(f"/api/v1/bundles/{bundle_id}/prefill?iteration=1")).json()

    assert before["parties"]["consignee"]["value"] == "MUMBAI INFRA PIPING PVT LTD" and before["parties"]["consignee"]["corrected"] is False
    assert before["assessment"]["pending_corrections"] == 1 and "1 correction change(s) made after this assessment are NOT included" in before["banner"]

    consignee = after["parties"]["consignee"]
    assert consignee["value"] == "MUMBAI INFRA PIPING LLP" and consignee["corrected"] is True and consignee["confidence"] == 1.0
    assert after["assessment"]["pending_corrections"] == 0 and after["assessment"]["run_mode"] == "recompute"
    assert [(c["path"], c["value"], c["reason"]) for c in after["corrections"]] == [("consignee", "MUMBAI INFRA PIPING LLP", "name on the stamp")]
    # the agent's value wins, but the pack does not hide that the other documents still say what they said
    assert consignee["conflict"] is True and consignee["alternatives"] and any("documents disagree" in note for note in consignee["review"])

    # an older assessment is still available, and says it is not the latest
    assert first_again["assessment"]["iteration"] == 1 and first_again["parties"]["consignee"]["corrected"] is False
    assert first_again["banner"].count("SUPERSEDED") == 1 and "assessment 2 is newer" in first_again["banner"]
    assert document_id and row >= 0


@pytest.mark.asyncio
async def test_a_cleared_case_c_bundle_has_no_banner() -> None:
    async with api_client() as client:
        created = (await client.post("/api/v1/demo/case-c")).json()
        bundle_id = created["id"]
        started = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        await wait_for_run(bundle_id, started.json()["run_id"])
        missing = (await client.get(f"/api/v1/bundles/{bundle_id}/prefill")).json()
        await client.post(
            f"/api/v1/bundles/{bundle_id}/documents", files={"file": ("mtc_pipe_test_cert.pdf", case_c_pdf("mtc_pipe_test_cert.pdf"), "application/pdf")}
        )
        started = await client.post(f"/api/v1/bundles/{bundle_id}/reassess")
        await wait_for_run(bundle_id, started.json()["run_id"])
        cleared = (await client.get(f"/api/v1/bundles/{bundle_id}/prefill")).json()

    assert missing["assessment"]["status"] == "MISSING_EVIDENCE" and missing["banner"].startswith("NOT CLEARED")
    assert missing["assessment"]["missing_documents"], "the pack lists the document that is missing"
    assert cleared["assessment"]["status"] == "COMPLIANT_FOR_SUBMISSION" and cleared["banner"] is None
    assert cleared["declaration"]["destination_country"] == "SG" and {i["id"] for i in cleared["to_be_supplied"]} >= {"UEN", "DECLARANT"}
    assert cleared["material"]["certificate_document_id"] and cleared["material"]["heat_numbers"]
    assert json.dumps(cleared)  # plain JSON all the way down


@pytest.mark.asyncio
async def test_the_pdf_summary_downloads_with_the_same_verdict() -> None:
    async with api_client() as client:
        bundle_id, _ = await analyse_case_d(client)
        response = await client.get(f"/api/v1/bundles/{bundle_id}/prefill.pdf")
        older = await client.get(f"/api/v1/bundles/{bundle_id}/prefill.pdf?iteration=1")

    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="cargoclear-prefill-{bundle_id}-assessment1.pdf"'
    assert response.content.startswith(b"%PDF-") and b"NOT CLEARED" in response.content
    assert older.status_code == 200


@pytest.mark.asyncio
async def test_nothing_to_pre_fill_from_is_a_clear_refusal() -> None:
    async with api_client() as client:
        created = (await client.post("/api/v1/demo/case-d")).json()
        bundle_id = created["id"]
        before_analysis = await client.get(f"/api/v1/bundles/{bundle_id}/prefill")
        before_analysis_pdf = await client.get(f"/api/v1/bundles/{bundle_id}/prefill.pdf")
        unknown = await client.get("/api/v1/bundles/bnd-000000000000/prefill")
        started = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        await wait_for_run(bundle_id, started.json()["run_id"])
        bundle_two = (await client.get("/api/v1/bundles/" + bundle_id)).json()
        no_such_iteration = await client.get(f"/api/v1/bundles/{bundle_id}/prefill?iteration=7")
        bad_iteration = await client.get(f"/api/v1/bundles/{bundle_id}/prefill?iteration=0")

    assert bundle_two["id"] == bundle_id
    assert before_analysis.status_code == 409 and "Run the analysis first" in before_analysis.json()["message"]
    assert before_analysis_pdf.status_code == 409
    assert unknown.status_code == 404
    assert no_such_iteration.status_code == 404 and "Assessment 7 not found" in no_such_iteration.json()["message"]
    assert bad_iteration.status_code == 422
