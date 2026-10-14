"""Integration tests for Hero Demo Case C: the real journey through the real app, in-process.

Uses the committed sample PDFs in <repo>/fixtures/case_c/ (distinct bytes -> distinct document ids) and
the normal upload endpoint. Runs are awaited by polling the run state (no fixed sleeps).

Case C sequence:
  1. Upload Invoice + Bill of Lading + Packing List for HS 7304.
  2. POST /analyze -> W-001 and H-002 PASS, the Mill Test Certificate is missing -> MISSING_EVIDENCE.
  3. Upload mtc_pipe_test_cert.pdf, POST /reassess -> COMPLIANT_FOR_SUBMISSION, with a Reasoning Delta that
     cites the MTC, and an intact, complete audit chain.
"""

from __future__ import annotations

import pytest

from app.agents import extraction
from tests.helpers import api_client, case_c_pdf, wait_for_run

PRELOADED = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf")
MTC = "mtc_pipe_test_cert.pdf"
EXPECTED_TYPES = {
    "commercial_invoice.pdf": "COMMERCIAL_INVOICE",
    "bill_of_lading.pdf": "BILL_OF_LADING",
    "packing_list.pdf": "PACKING_LIST",
    MTC: "MILL_TEST_CERTIFICATE",
}


async def _upload(client, bundle_id: str, filename: str) -> dict:
    resp = await client.post(
        f"/api/v1/bundles/{bundle_id}/documents",
        files={"file": (filename, case_c_pdf(filename), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _run(client, bundle_id: str, action: str) -> dict:
    resp = await client.post(f"/api/v1/bundles/{bundle_id}/{action}")
    assert resp.status_code == 202, resp.text
    state = await wait_for_run(bundle_id, resp.json()["run_id"])
    assert state["state"] == "COMPLETE", f"run ended in {state}"
    return state


async def _doc_types(client, bundle_id: str) -> dict[str, str]:
    bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()
    return {d["filename"]: d["doc_type"] for d in bundle["documents"]}


@pytest.mark.asyncio
async def test_case_c_hero_demo_journey() -> None:
    async with api_client() as client:
        # --- 1. bundle with the three initial documents -------------------------------------------
        created = await client.post(
            "/api/v1/bundles", json={"reference": "HERO-CASE-C-7304", "destination_country": "SG"}
        )
        assert created.status_code == 201
        bundle_id = created.json()["id"]

        uploaded = [await _upload(client, bundle_id, name) for name in PRELOADED]
        assert len({d["document_id"] for d in uploaded}) == 3, "the sample PDFs must have distinct ids"
        registered = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()
        assert sorted(d["filename"] for d in registered["documents"]) == sorted(PRELOADED)

        # --- 2. first analysis ------------------------------------------------------------------------
        await _run(client, bundle_id, "analyze")

        first = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()
        assert first["iteration"] == 1
        assert first["status"] == "MISSING_EVIDENCE"
        severities = {c["check_id"]: c["severity"] for c in first["checks"]}
        assert severities["W-001"] == "PASS"
        assert severities["W-002"] == "PASS"  # the packing list declares net, tare and gross, and they add up
        assert severities["H-002"] == "PASS"
        assert severities["G-001"] == "PASS"  # the declared HS code is confirmed against the tariff at 8 digits
        assert not [i for i in severities if i.startswith("H-003")], "no certificate is in the bundle yet"
        # the entities agree on invoice, BoL and packing list; only the BoL states a vessel, so there is no E-vessel
        # invoice arithmetic (I-*) and the origin on invoice + packing list (E-origin) run from the first analysis; the
        # certificate checks (M-*) need a certificate
        assert set(severities) == {"W-001", "W-002", "H-002", "E-consignee", "E-consignor", "E-origin", "I-001", "I-002",
                                   "I-003", "G-001"}
        assert severities["E-consignee"] == severities["E-consignor"] == severities["E-origin"] == "PASS"
        assert severities["I-001"] == severities["I-002"] == severities["I-003"] == "PASS"  # 120 x 700.0 = 84,000.0 USD
        # the indicative estimate: CIF invoice (nothing to add), India -> Singapore: no customs duty, GST 9 % of the
        # (illustrative) SGD value; it is information, it never changed the status above
        valuation = first["valuation"]
        assert valuation["status"] == "ESTIMATED" and valuation["incoterm"] == "CIF"
        assert valuation["destination_country"] == "SG" and valuation["total_duty"] == 9828.0
        assert [line["name"] for line in valuation["duties"]] == ["Customs duty", "GST"]
        assert any("ILLUSTRATIVE" in a for a in valuation["assumptions"]), "the exchange rate is a stated assumption"
        assert set(first["reference_data"]) == {"hs_rules.json", "specs.json", "duty_rates.json", "valuation_defaults.json",
                                                "exchange_rates.json", "anti_dumping.json", "declaration_inputs.json"}
        assert all(c["assumptions"] == [] for c in first["checks"])  # the demo verdict rests on no assumption
        assert [m["id"] for m in first["missing_evidence"]] == ["ME-MILL_TEST_CERTIFICATE"]
        assert first["reasoning_delta"]["kind"] == "INITIAL"
        assert first["data_source"] == "fixture"
        assert sorted(first["documents"]) == sorted(d["document_id"] for d in uploaded)
        assert await _doc_types(client, bundle_id) == {n: EXPECTED_TYPES[n] for n in PRELOADED}

        # --- 3. corrective upload + reassessment -------------------------------------------------
        await _upload(client, bundle_id, MTC)
        await _run(client, bundle_id, "reassess")

        second = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()
        assert second["iteration"] == 2
        assert second["status"] == "COMPLIANT_FOR_SUBMISSION"
        assert second["missing_evidence"] == []
        assert second["data_source"] == "fixture"
        second_checks = {c["check_id"]: c for c in second["checks"]}
        assert second_checks["H-003-MILL_TEST_CERTIFICATE"]["severity"] == "PASS"  # the MTC states the invoice's code
        assert second_checks["H-003-MILL_TEST_CERTIFICATE"]["assumptions"] == []
        assert set(second_checks) == {"W-001", "W-002", "H-002", "H-003-MILL_TEST_CERTIFICATE", "E-consignee",
                                      "E-consignor", "E-origin", "I-001", "I-002", "I-003", "M-001", "M-002", "M-003",
                                      "M-004", "G-001"}
        # the certificate: chemistry inside API 5L PSL2 Grade B, CE(IIW) under 0.43, both heats on the packing list
        for check_id in ("M-001", "M-002", "M-003", "M-004"):
            assert second_checks[check_id]["severity"] == "PASS", second_checks[check_id]["message"]
        assert second_checks["M-002"]["rule_set"] == "demo-curated"  # a check that uses curated data names it
        assert len(second_checks["E-consignee"]["evidence"]) == 4  # invoice, BoL, packing list and the MTC
        assert second["confidence"]["action"] == "AUTO_ACCEPT"
        assert {c["severity"] for c in second["checks"]} == {"PASS"}
        assert len(second_checks) == len(second["checks"]), "check ids must stay unique"

        delta = second["reasoning_delta"]
        assert delta["kind"] == "REASSESSMENT"
        changes = {c["field"]: c for c in delta["changes"]}
        resolved = changes["missing_evidence.ME-MILL_TEST_CERTIFICATE"]
        assert resolved["from"] == "REQUIRED"
        assert resolved["to"] == "SATISFIED"
        assert f"{MTC} (MILL_TEST_CERTIFICATE)" in resolved["because"]
        status_change = changes["status"]
        assert (status_change["from"], status_change["to"]) == ("MISSING_EVIDENCE", "COMPLIANT_FOR_SUBMISSION")
        assert f"{MTC} (MILL_TEST_CERTIFICATE)" in status_change["because"]
        assert MTC in delta["narrative"]

        stored = await _doc_types(client, bundle_id)
        assert stored == EXPECTED_TYPES, "every stored document must be classified"
        assert "UNKNOWN" not in stored.values()

        iterations = (await client.get(f"/api/v1/bundles/{bundle_id}/iterations")).json()
        assert [it["iteration"] for it in iterations] == [1, 2]
        assert [it["data_source"] for it in iterations] == ["fixture", "fixture"]

        # --- 4. audit chain ----------------------------------------------------------------------------
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        assert audit["verified"] is True, audit["error"]
        assert audit["error"] is None
        types = [e["event_type"] for e in audit["events"]]
        assert "SYSTEM_EVENT" not in types, types
        assert types.count("DOCUMENT_UPLOADED") == 4
        lifecycle = [
            (e["event_type"], e["iteration"])
            for e in audit["events"]
            if e["event_type"] in ("ANALYSIS_STARTED", "ASSESSMENT_COMPLETED")
        ]
        assert lifecycle == [
            ("ANALYSIS_STARTED", 1),
            ("ASSESSMENT_COMPLETED", 1),
            ("ANALYSIS_STARTED", 2),
            ("ASSESSMENT_COMPLETED", 2),
        ]
        assert [e["seq"] for e in audit["events"]] == list(range(1, len(types) + 1))


@pytest.mark.asyncio
async def test_case_c_weight_mismatch_is_a_material_contradiction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative journey: break the packing list net weight so W-001 exceeds its tolerance."""
    real_fixture = extraction._generate_fixture_for_file

    def packing_list_with_wrong_net_weight(document_id: str, filename: str):
        doc = real_fixture(document_id, filename)
        if doc.doc_type == "PACKING_LIST":
            # 15 000 kg net + 280 kg tare vs 14 280 kg on the Bill of Lading: far outside +-71.4 kg
            doc.total_net_weight_kg = doc.total_net_weight_kg.model_copy(update={"value": 15000.0})
        return doc

    monkeypatch.setattr(extraction, "_generate_fixture_for_file", packing_list_with_wrong_net_weight)

    async with api_client() as client:
        created = await client.post("/api/v1/bundles", json={"reference": "CASE-C-NEG", "destination_country": "SG"})
        bundle_id = created.json()["id"]
        for name in PRELOADED:
            await _upload(client, bundle_id, name)

        await _run(client, bundle_id, "analyze")

        assessment = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()

    assert assessment["status"] == "MATERIAL_CONTRADICTION"
    w001 = next(c for c in assessment["checks"] if c["check_id"] == "W-001")
    assert w001["severity"] == "MATERIAL"
    assert w001["delta"] > w001["tolerance"]
    assert w001["delta"] == pytest.approx(1000.0)
    # a contradiction outranks the missing certificate, which is still reported
    assert [m["id"] for m in assessment["missing_evidence"]] == ["ME-MILL_TEST_CERTIFICATE"]
    assert audit["verified"] is True
