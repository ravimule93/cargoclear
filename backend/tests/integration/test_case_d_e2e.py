"""Case D, the India import: the real journey through the real app, in-process.

Chinese-origin seamless tubes, declared under the NON-ALLOY code 7304.31.00, with a certificate (ASTM A106 Gr B) whose
heat TH-77121 carries 0.35 % chromium: inside A106's own limit, but at or above the 0.30 % that makes a steel ALLOY
under HS Chapter 72 Note 1(f). One analysis, four documents, and the product has to say all of this:

  * status MATERIAL_CONTRADICTION (M-001), never "compliant",
  * the standard itself is met (M-003 PASS), the invoice adds up (I-*), the heats trace (M-004), the origin agrees,
  * an anti-dumping WARNING (SEC-002) and an indicative duty estimate that names every assumption,
  * an intact audit chain.
"""

from __future__ import annotations

import pytest

from tests.helpers import api_client, wait_for_run


async def analyse_case_d(client) -> tuple[str, dict]:
    created = await client.post("/api/v1/demo/case-d")
    assert created.status_code == 201, created.text
    bundle_id = created.json()["id"]
    started = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
    assert started.status_code == 202, started.text
    state = await wait_for_run(bundle_id, started.json()["run_id"])
    assert state["state"] == "COMPLETE", state
    return bundle_id, (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()


@pytest.mark.asyncio
async def test_case_d_is_a_material_contradiction_with_the_reasons_a_specialist_needs() -> None:
    async with api_client() as client:
        bundle_id, assessment = await analyse_case_d(client)
        types = {d["filename"]: d["doc_type"] for d in (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]}
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()

    assert assessment["status"] == "MATERIAL_CONTRADICTION"
    assert assessment["missing_evidence"] == [], "all four documents are there: this is a contradiction, not a gap"
    assert assessment["data_source"] == "fixture" and assessment["iteration"] == 1
    assert set(types.values()) == {"COMMERCIAL_INVOICE", "BILL_OF_LADING", "PACKING_LIST", "MILL_TEST_CERTIFICATE"}

    checks = {c["check_id"]: c for c in assessment["checks"]}
    severities = {i: c["severity"] for i, c in checks.items()}
    assert severities["M-001"] == "MATERIAL"
    assert "heat TH-77121 reports Cr 0.35%" in checks["M-001"]["message"] and "7304.51" in checks["M-001"]["message"]
    assert checks["M-001"]["rule_set"] == "demo-curated"

    # everything else a customs officer would check holds, which is what makes the one contradiction stand out
    for ok in ("I-001", "I-002", "I-003", "M-003", "M-004", "E-origin", "E-consignee", "E-consignor", "H-002", "W-001", "W-002", "G-001"):
        assert severities[ok] == "PASS", f"{ok}: {checks[ok]['message']}"
    assert "M-002" not in checks, "A106 sets no carbon-equivalent limit"
    assert "ASTM A106" in checks["M-003"]["message"], "the standard itself is met: only the HS declaration is contradicted"

    assert severities["SEC-002"] == "WARN" and "12 % of the assessable value" in checks["SEC-002"]["message"]
    assert "SEC-001" not in checks, "the steel is not just under a threshold: it is over it"

    # the evidence cites the trigger value on the certificate, with its position
    cited = [e for e in checks["M-001"]["evidence"] if e["field"] == "test_results"]
    assert len(cited) == 1 and cited[0]["raw_value"] == "TH-77121: Cr 0.35%" and cited[0]["bbox"] and cited[0]["row"] >= 0

    assert audit["verified"] is True
    assert [e["event_type"] for e in audit["events"]][-2:] == ["ANALYSIS_STARTED", "ASSESSMENT_COMPLETED"]


@pytest.mark.asyncio
async def test_case_d_gives_an_indicative_duty_estimate_that_states_what_it_assumed() -> None:
    async with api_client() as client:
        _bundle_id, assessment = await analyse_case_d(client)

    v = assessment["valuation"]
    assert v["status"] == "ESTIMATED" and v["destination_country"] == "IN" and v["destination_currency"] == "INR"
    assert v["incoterm"] == "FOB" and v["invoice_currency"] == "USD" and v["transaction_value"] == 61500.0
    assert v["freight"] == 1850.0, "freight is stated on the bill of lading"
    assert v["insurance"] == pytest.approx(691.88, abs=0.01), "insurance is not stated: the statutory default applies"
    assert v["assessable_value"] == pytest.approx((61500 + 1850 + 61500 * 0.01125) * 85, abs=0.01)
    assert [d["name"] for d in v["duties"]] == ["BCD", "SWS", "ADD", "IGST"]
    assert v["total_duty"] == pytest.approx(sum(d["amount"] for d in v["duties"]), abs=0.01)
    assert v["hs_code"] == "73043100" and v["implied_hs_code"] == "730451" and v["implied_total_duty"] is not None

    assumptions = " | ".join(v["assumptions"])
    for stated in ("insurance is not stated", "ILLUSTRATIVE", "anti-dumping rate is an illustrative", "not verified"):
        assert stated in assumptions, stated
    assert "Not a customs determination" in v["disclaimer"]
    assert set(assessment["reference_data"]) >= {"hs_rules.json", "specs.json", "anti_dumping.json"}


@pytest.mark.asyncio
async def test_the_estimate_does_not_decide_the_status() -> None:
    """Whatever the duty is, the status comes from the checks: a Case D re-run gives the same status and the same estimate."""
    async with api_client() as client:
        _a, first = await analyse_case_d(client)
        _b, second = await analyse_case_d(client)

    assert first["status"] == second["status"] == "MATERIAL_CONTRADICTION"
    assert first["valuation"] == second["valuation"] and first["reference_data"] == second["reference_data"]


@pytest.mark.asyncio
async def test_case_c_still_ends_compliant_and_case_d_never_does() -> None:
    """The two lanes side by side: the same engine, the same rules, opposite verdicts, each for a stated reason."""
    from tests.helpers import case_c_pdf

    async with api_client() as client:
        _id, case_d = await analyse_case_d(client)
        created = (await client.post("/api/v1/bundles", json={"reference": "C", "destination_country": "SG"})).json()
        for name in ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf", "mtc_pipe_test_cert.pdf"):
            up = await client.post(f"/api/v1/bundles/{created['id']}/documents", files={"file": (name, case_c_pdf(name), "application/pdf")})
            assert up.status_code == 201
        run = (await client.post(f"/api/v1/bundles/{created['id']}/analyze")).json()
        await wait_for_run(created["id"], run["run_id"])
        case_c = (await client.get(f"/api/v1/bundles/{created['id']}/assessment")).json()

    assert case_c["status"] == "COMPLIANT_FOR_SUBMISSION" and case_d["status"] == "MATERIAL_CONTRADICTION"
    assert {c["severity"] for c in case_c["checks"]} == {"PASS"}
    assert case_c["valuation"]["destination_country"] == "SG" and case_d["valuation"]["destination_country"] == "IN"
