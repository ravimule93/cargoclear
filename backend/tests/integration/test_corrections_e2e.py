"""Corrections by the authorised agent, through the real app: correct -> recompute -> a new, explained assessment.

The story is Case D: the checks say MATERIAL_CONTRADICTION because heat TH-77121 reads 0.35 % chromium. The agent looks at
the certificate, sees it prints 0.28 %, and corrects the cell. Nothing is read again (no model call): the stored extraction
is reused with the correction laid on, and the new iteration says what changed, why, and who said so.
"""

from __future__ import annotations

import pytest

from app.repo import firestore
from tests.helpers import api_client, case_c_pdf, wait_for_run

from .test_case_d_e2e import analyse_case_d


ORIGINAL = "0.35"  # the cell as the model read it; its unit is "%", which the Reasoning Delta shows next to the value


async def _recompute(client, bundle_id: str) -> dict:
    started = await client.post(f"/api/v1/bundles/{bundle_id}/recompute")
    assert started.status_code == 202, started.text
    state = await wait_for_run(bundle_id, started.json()["run_id"])
    assert state["state"] == "COMPLETE", state
    return (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()


async def _find_cell(client, bundle_id: str, heat: str, parameter: str, iteration: int | None = None) -> tuple[str, int, dict]:
    url = f"/api/v1/bundles/{bundle_id}/extractions" + (f"?iteration={iteration}" if iteration else "")
    for doc in (await client.get(url)).json():
        for index, row in enumerate(doc.get("test_results", [])):
            if row.get("heat_number") == heat and row.get("parameter") == parameter:
                return doc["document_id"], index, row
    raise AssertionError(f"no {parameter} cell for heat {heat}")


@pytest.mark.asyncio
async def test_correcting_the_chromium_cell_changes_the_verdict_and_says_why() -> None:
    async with api_client() as client:
        bundle_id, first = await analyse_case_d(client)
        assert first["status"] == "MATERIAL_CONTRADICTION" and first["corrections"] == [] and first["run_mode"] == "full"
        document_id, row, cell = await _find_cell(client, bundle_id, "TH-77121", "Cr")
        assert cell["value"] == ORIGINAL and "corrected" not in cell

        created = await client.post(
            f"/api/v1/bundles/{bundle_id}/corrections",
            json={"document_id": document_id, "path": f"test_results[{row}]", "value": "0.28", "reason": "certificate prints 0.28 in the Cr column"},
        )
        assert created.status_code == 201, created.text
        entry = created.json()
        assert entry["kind"] == "correction" and entry["value"] == "0.28" and entry["original_value"] == ORIGINAL
        assert entry["previous_value"] == ORIGINAL and entry["anchor"] == "TH77121|Cr" and entry["actor"] == "user"
        assert entry["correction_id"].startswith("cor-") and entry["reason"] == "certificate prints 0.28 in the Cr column"

        # recorded, in force, and not yet in any assessment
        listed = (await client.get(f"/api/v1/bundles/{bundle_id}/corrections")).json()
        assert listed["pending"] == 1 and listed["latest_iteration"] == 1
        assert [e["correction_id"] for e in listed["effective"]] == [entry["correction_id"]]
        still = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()
        assert still["iteration"] == 1 and still["status"] == "MATERIAL_CONTRADICTION", "a correction alone changes nothing"

        second = await _recompute(client, bundle_id)
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        extraction_two = await firestore.get_extraction_record(bundle_id, 2)
        viewed_one = await _find_cell(client, bundle_id, "TH-77121", "Cr", iteration=1)
        viewed_two = await _find_cell(client, bundle_id, "TH-77121", "Cr", iteration=2)
        after = (await client.get(f"/api/v1/bundles/{bundle_id}/corrections")).json()

    # the verdict follows the corrected value, and only that
    assert second["iteration"] == 2 and second["run_mode"] == "recompute"
    m001 = next(c for c in second["checks"] if c["check_id"] == "M-001")
    assert m001["severity"] == "PASS", m001["message"]
    assert second["status"] != "MATERIAL_CONTRADICTION"

    # the iteration lists the correction it used, and the Reasoning Delta names it with the value it replaced and the reason
    assert [(c["correction_id"], c["status"], c["value"], c["original_value"]) for c in second["corrections"]] == [
        (entry["correction_id"], "applied", "0.28", ORIGINAL)
    ]
    delta = second["reasoning_delta"]
    assert delta["kind"] == "REASSESSMENT"
    changes = {c["field"]: c for c in delta["changes"]}
    assert changes["M-001"]["from"] == "MATERIAL" and changes["M-001"]["to"] == "PASS"
    corrected = changes[f"correction.{document_id}.test_results[{row}]"]
    assert corrected["from"] == "0.35 %" and corrected["to"] == "0.28 %" and "certificate prints 0.28" in corrected["because"]
    assert "authorised agent" in changes["status"]["because"]

    # nothing was read again: the new iteration's extraction is a copy of the first, which stays exactly what the model read
    assert extraction_two is not None and extraction_two["derived_from"] == 1 and extraction_two["extraction_source"] == "fixture"
    assert viewed_one[2]["value"] == ORIGINAL and "corrected" not in viewed_one[2], "iteration 1 is untouched"
    assert viewed_two[2]["value"] == "0.28" and viewed_two[2]["corrected"] is True and viewed_two[2]["original_value"] == ORIGINAL
    assert viewed_two[2]["confidence"] == 1.0

    # the audit chain carries the whole story, in order, and still verifies
    types = [e["event_type"] for e in audit["events"]]
    assert audit["verified"] is True
    assert types[-3:] == ["FIELD_CORRECTED", "ANALYSIS_STARTED", "ASSESSMENT_COMPLETED"]
    started = [e for e in audit["events"] if e["event_type"] == "ANALYSIS_STARTED"][-1]
    completed = [e for e in audit["events"] if e["event_type"] == "ASSESSMENT_COMPLETED"][-1]
    assert started["payload"]["mode"] == "recompute"
    assert completed["payload"]["mode"] == "recompute" and completed["payload"]["corrections"] == [entry["correction_id"]]
    assert after["pending"] == 0


@pytest.mark.asyncio
async def test_a_recompute_reads_no_document_and_runs_no_extraction_but_a_reassessment_does(monkeypatch) -> None:
    """The claim "a recompute reads no document and calls no model", as a spy on the two doors a model call goes through."""
    from app.services import orchestrator

    dispatched: list[str] = []
    preprocessed: list[int] = []
    real_dispatch, real_preprocess = orchestrator.dispatch, orchestrator._preprocess_documents

    async def spy_dispatch(stage, ctx):
        dispatched.append(stage)
        return await real_dispatch(stage, ctx)

    async def spy_preprocess(ctx):
        preprocessed.append(1)
        return await real_preprocess(ctx)

    async with api_client() as client:
        bundle_id, _first = await analyse_case_d(client)
        document_id, row, _cell = await _find_cell(client, bundle_id, "TH-77121", "Cr")
        created = await client.post(
            f"/api/v1/bundles/{bundle_id}/corrections",
            json={"document_id": document_id, "path": f"test_results[{row}]", "value": "0.28", "reason": "certificate prints 0.28"},
        )
        assert created.status_code == 201, created.text

        monkeypatch.setattr(orchestrator, "dispatch", spy_dispatch)
        monkeypatch.setattr(orchestrator, "_preprocess_documents", spy_preprocess)
        second = await _recompute(client, bundle_id)
        assert second["run_mode"] == "recompute" and second["status"] == "SPECIALIST_REVIEW_REQUIRED"
        assert "extract" not in dispatched and preprocessed == [], (dispatched, preprocessed)
        assert dispatched, "the other stages (grounding, the checks, the synthesis) did run"

        dispatched.clear()
        again = await client.post(f"/api/v1/bundles/{bundle_id}/reassess", json={"mode": "full"})
        assert again.status_code == 202, again.text
        await wait_for_run(bundle_id, again.json()["run_id"])
        assert "extract" in dispatched and preprocessed, "control: a reassessment does read the documents"


@pytest.mark.asyncio
async def test_undoing_a_correction_brings_back_what_the_model_read() -> None:
    async with api_client() as client:
        bundle_id, _ = await analyse_case_d(client)
        document_id, row, _cell = await _find_cell(client, bundle_id, "TH-77121", "Cr")
        entry = (await client.post(
            f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": document_id, "path": f"test_results[{row}]", "value": "0.28"}
        )).json()
        await _recompute(client, bundle_id)

        undone = await client.post(f"/api/v1/bundles/{bundle_id}/corrections/{entry['correction_id']}/revert", json={"reason": "misread the column"})
        assert undone.status_code == 201, undone.text
        assert undone.json()["kind"] == "revert" and undone.json()["reverts"] == entry["correction_id"]
        listed = (await client.get(f"/api/v1/bundles/{bundle_id}/corrections")).json()
        assert listed["effective"] == [] and len(listed["corrections"]) == 2 and listed["pending"] == 1, "history is kept, the overlay is empty"

        third = await _recompute(client, bundle_id)
        # undoing it twice is refused: it is no longer in force
        again = await client.post(f"/api/v1/bundles/{bundle_id}/corrections/{entry['correction_id']}/revert")
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()

    assert third["iteration"] == 3 and third["status"] == "MATERIAL_CONTRADICTION" and third["corrections"] == []
    changes = {c["field"]: c for c in third["reasoning_delta"]["changes"]}
    undo_change = changes[f"correction.{document_id}.test_results[{row}]"]
    assert undo_change["from"] == "0.28 %" and undo_change["to"] == "0.35 %" and "undone" in undo_change["because"]
    assert changes["M-001"]["to"] == "MATERIAL"
    assert again.status_code == 404
    assert [e["event_type"] for e in audit["events"] if e["event_type"].startswith(("FIELD_", "CORRECTION_"))] == ["FIELD_CORRECTED", "CORRECTION_REVERTED"]
    assert audit["verified"] is True


@pytest.mark.asyncio
async def test_a_reassessment_keeps_the_agents_corrections() -> None:
    """A full run reads the documents again, then lays the same corrections over the fresh extraction."""
    async with api_client() as client:
        bundle_id, _ = await analyse_case_d(client)
        document_id, row, _cell = await _find_cell(client, bundle_id, "TH-77121", "Cr")
        await client.post(f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": document_id, "path": f"test_results[{row}]", "value": "0.28"})

        started = await client.post(f"/api/v1/bundles/{bundle_id}/reassess")
        assert started.status_code == 202, started.text
        assert (await wait_for_run(bundle_id, started.json()["run_id"]))["state"] == "COMPLETE"
        second = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()

    assert second["run_mode"] == "reassess"
    assert next(c for c in second["checks"] if c["check_id"] == "M-001")["severity"] == "PASS"
    assert [c["status"] for c in second["corrections"]] == ["applied"]


@pytest.mark.asyncio
async def test_a_header_correction_and_a_confirmation_are_recorded_differently() -> None:
    async with api_client() as client:
        bundle_id, _ = await analyse_case_d(client)
        docs = (await client.get(f"/api/v1/bundles/{bundle_id}/extractions")).json()
        invoice = next(d for d in docs if d["doc_type"] == "COMMERCIAL_INVOICE")
        currency = invoice["invoice_currency"]["value"]

        confirmed = (await client.post(
            f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": invoice["document_id"], "path": "invoice_currency", "value": currency.lower()}
        )).json()
        corrected = (await client.post(
            f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": invoice["document_id"], "path": "invoice_currency", "value": "EUR"}
        )).json()
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        listed = (await client.get(f"/api/v1/bundles/{bundle_id}/corrections")).json()

    assert confirmed["kind"] == "confirmation" and confirmed["value"] == currency, "same value, different case: the agent confirmed it"
    assert corrected["kind"] == "correction" and corrected["previous_value"] == currency and corrected["original_value"] == currency
    assert [e["event_type"] for e in audit["events"]][-2:] == ["FIELD_CONFIRMED", "FIELD_CORRECTED"]
    assert [e["correction_id"] for e in listed["effective"]] == [corrected["correction_id"]], "the newest entry per address is in force"
    assert listed["pending"] == 1


@pytest.mark.asyncio
async def test_what_cannot_be_corrected_is_refused_with_a_reason_and_records_nothing() -> None:
    async with api_client() as client:
        created = await client.post("/api/v1/demo/case-d")
        bundle_id = created.json()["id"]
        doc_id = created.json()["documents"][0]["document_id"]
        url = f"/api/v1/bundles/{bundle_id}/corrections"

        before_analysis = await client.post(url, json={"document_id": doc_id, "path": "consignee", "value": "X"})
        recompute_first = await client.post(f"/api/v1/bundles/{bundle_id}/recompute")

        bundle_id, _ = await analyse_case_d(client)
        docs = (await client.get(f"/api/v1/bundles/{bundle_id}/extractions")).json()
        invoice = next(d for d in docs if d["doc_type"] == "COMMERCIAL_INVOICE")
        certificate = next(d for d in docs if d["doc_type"] == "MILL_TEST_CERTIFICATE")
        url = f"/api/v1/bundles/{bundle_id}/corrections"
        inv = invoice["document_id"]

        cases = {
            "unknown document": ({"document_id": "doc-nope", "path": "consignee", "value": "X"}, 404),
            "row out of range": ({"document_id": certificate["document_id"], "path": "test_results[9999]", "value": "0.1"}, 404),
            "path outside the grammar": ({"document_id": inv, "path": "document_id", "value": "X"}, 422),
            "ambiguous number": ({"document_id": inv, "path": "invoice_value", "value": "14,280"}, 422),
            "weight without a unit": ({"document_id": inv, "path": "tare_weight_kg", "value": "280"}, 422),
            "no value": ({"document_id": inv, "path": "consignee"}, 422),
            "value and clear": ({"document_id": inv, "path": "consignee", "value": "X", "clear": True}, 422),
            "clearing a certificate cell": ({"document_id": certificate["document_id"], "path": "test_results[0]", "clear": True}, 422),
            "unknown document type": ({"document_id": inv, "path": "doc_type", "value": "UNKNOWN"}, 422),
            "too long": ({"document_id": inv, "path": "consignee", "value": "x" * 501}, 422),
        }
        refused = {name: (await client.post(url, json=body)).status_code for name, (body, _expected) in cases.items()}
        bad_id = await client.post(f"{url}/not-an-id/revert")
        unknown_entry = await client.post(f"{url}/cor-999/revert")
        listed = (await client.get(url)).json()

    assert before_analysis.status_code == 409 and "Run the analysis" in before_analysis.json()["message"]
    assert recompute_first.status_code == 409
    assert refused == {name: expected for name, (_body, expected) in cases.items()}
    assert bad_id.status_code == 404 and unknown_entry.status_code == 404
    assert listed["corrections"] == [], "a refused correction leaves no trace"


@pytest.mark.asyncio
async def test_a_recompute_is_refused_once_the_bundle_has_a_document_the_extraction_never_saw() -> None:
    async with api_client() as client:
        bundle_id, _ = await analyse_case_d(client)
        extra = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents", files={"file": ("mtc_pipe_test_cert.pdf", case_c_pdf("mtc_pipe_test_cert.pdf"), "application/pdf")}
        )
        assert extra.status_code == 201, extra.text
        refused = await client.post(f"/api/v1/bundles/{bundle_id}/recompute")
        # a correction on an already-analysed document is still fine: the next reassessment will use it
        docs = (await client.get(f"/api/v1/bundles/{bundle_id}/extractions")).json()
        accepted = await client.post(
            f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": docs[0]["document_id"], "path": "document_number", "value": "X-1"}
        )

    assert refused.status_code == 409 and "Reassess" in refused.json()["message"]
    assert accepted.status_code == 201


@pytest.mark.asyncio
async def test_a_corrected_document_type_reaches_the_rail_and_the_missing_evidence_logic() -> None:
    async with api_client() as client:
        bundle_id, _ = await analyse_case_d(client)
        docs = (await client.get(f"/api/v1/bundles/{bundle_id}/extractions")).json()
        packing = next(d for d in docs if d["doc_type"] == "PACKING_LIST")
        entry = await client.post(f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": packing["document_id"], "path": "doc_type", "value": "BILL_OF_LADING"})
        assert entry.status_code == 201, entry.text
        second = await _recompute(client, bundle_id)
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()

    types = {d["document_id"]: d["doc_type"] for d in bundle["documents"]}
    assert types[packing["document_id"]] == "BILL_OF_LADING"
    assert "ME-CORE-PACKING_LIST" in {m["id"] for m in second["missing_evidence"]}, "with no packing list left the baseline requirement returns"


@pytest.mark.asyncio
async def test_a_concurrent_append_makes_a_correction_read_again_and_record_the_value_actually_in_force(monkeypatch) -> None:
    """Two tabs correct the same cell: the second to be written must record the first one's value as the value it replaced,
    not the model's reading it saw when it started, and no entry may be lost or duplicated."""
    from app.services import audit

    async with api_client() as client:
        bundle_id, _first = await analyse_case_d(client)
        document_id, row, _cell = await _find_cell(client, bundle_id, "TH-77121", "Cr")
        path = f"test_results[{row}]"

        real_record = audit.record
        raced = {"done": False}

        async def record_after_a_rival_wrote(ctx):
            if ctx.get("after_seq") is not None and not raced["done"]:
                raced["done"] = True  # the rival's correction lands between this writer's read and its append
                await real_record({
                    "bundle_id": bundle_id, "iteration": 1, "audit_event_type": "FIELD_CORRECTED", "actor": "user",
                    "audit_payload": {"document_id": document_id, "path": path, "anchor": "TH77121|Cr", "value": "0.31", "unit": "%",
                                      "original_value": "0.35", "original_unit": "%", "previous_value": "0.35", "previous_unit": "%", "reason": "rival"},
                })
            return await real_record(ctx)

        monkeypatch.setattr(audit, "record", record_after_a_rival_wrote)
        mine = await client.post(f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": document_id, "path": path, "value": "0.28", "reason": "mine"})
        monkeypatch.setattr(audit, "record", real_record)

        assert mine.status_code == 201, mine.text
        entry = mine.json()
        assert entry["value"] == "0.28" and entry["previous_value"] == "0.31", "it replaced the rival's value, which it re-read"
        listed = (await client.get(f"/api/v1/bundles/{bundle_id}/corrections")).json()
        assert [e["reason"] for e in listed["corrections"]] == ["rival", "mine"]
        assert [e["reason"] for e in listed["effective"]] == ["mine"]


@pytest.mark.asyncio
async def test_an_undo_is_still_possible_when_the_bundle_has_reached_the_cap_on_entries(monkeypatch) -> None:
    from app.core.config import settings

    async with api_client() as client:
        bundle_id, _first = await analyse_case_d(client)
        document_id, row, _cell = await _find_cell(client, bundle_id, "TH-77121", "Cr")
        created = await client.post(f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": document_id, "path": f"test_results[{row}]", "value": "0.28"})
        assert created.status_code == 201

        monkeypatch.setattr(settings, "max_corrections_per_bundle", 1)  # the bundle is now full
        refused = await client.post(f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": document_id, "path": f"test_results[{row}]", "value": "0.27"})
        assert refused.status_code == 422, "no new entry past the cap"

        undone = await client.post(f"/api/v1/bundles/{bundle_id}/corrections/{created.json()['correction_id']}/revert", json={"reason": "wrong"})
        assert undone.status_code == 201, "but the wrong one can still be taken back"
