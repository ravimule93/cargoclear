"""Reasoning Delta attribution (B5): a resolved requirement is credited only to a new document of the right type."""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.schemas import ExtractedDocument
from app.services import reasoning

MTC_REQ = {
    "id": "ME-MILL_TEST_CERTIFICATE",
    "document_label": "Mill Test Certificate",
    "hs_code": "73041900",
    "reason": "required",
}
INVOICE_REQ = {
    "id": "ME-CORE-COMMERCIAL_INVOICE",
    "document_label": "Commercial Invoice",
    "hs_code": "GENERAL",
    "reason": "baseline trade document",
}


def _doc(document_id: str, filename: str, doc_type: str) -> dict[str, Any]:
    return {"document_id": document_id, "filename": filename, "doc_type": doc_type}


def _extracted(document_id: str, doc_type: str) -> ExtractedDocument:
    return ExtractedDocument(document_id=document_id, doc_type=doc_type, doc_type_confidence=0.99)


def _ctx(
    *,
    prev_missing: list[dict[str, Any]],
    curr_missing: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    extracted: list[ExtractedDocument],
    prev_status: str = "MISSING_EVIDENCE",
    final_status: str = "COMPLIANT_FOR_SUBMISSION",
    prev_documents: tuple[str, ...] = ("d1", "d2", "d3"),
) -> dict[str, Any]:
    return {
        "previous_iteration": {
            "status": prev_status,
            "checks": [],
            "documents": list(prev_documents),
            "missing_evidence": prev_missing,
        },
        "final_status": final_status,
        "checks": [],
        "missing_evidence": curr_missing,
        "documents": documents,
        "extracted": extracted,
    }


BASE_DOCS = [
    _doc("d1", "commercial_invoice.pdf", "COMMERCIAL_INVOICE"),
    _doc("d2", "bill_of_lading.pdf", "BILL_OF_LADING"),
    _doc("d3", "packing_list.pdf", "PACKING_LIST"),
]
BASE_EXTRACTED = [
    _extracted("d1", "COMMERCIAL_INVOICE"),
    _extracted("d2", "BILL_OF_LADING"),
    _extracted("d3", "PACKING_LIST"),
]


def _changes(delta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["field"]: c for c in delta["changes"]}


@pytest.mark.asyncio
async def test_matching_new_document_is_cited_for_the_requirement_and_the_status_change() -> None:
    ctx = _ctx(
        prev_missing=[MTC_REQ],
        curr_missing=[],
        documents=[*BASE_DOCS, _doc("d4", "mtc_pipe_test_cert.pdf", "MILL_TEST_CERTIFICATE")],
        extracted=[*BASE_EXTRACTED, _extracted("d4", "MILL_TEST_CERTIFICATE")],
    )

    delta = (await reasoning.build(ctx))["reasoning_delta"]
    changes = _changes(delta)

    assert changes["missing_evidence.ME-MILL_TEST_CERTIFICATE"]["because"] == (
        "Uploaded mtc_pipe_test_cert.pdf (MILL_TEST_CERTIFICATE) satisfies requirement "
        "'Mill Test Certificate' for HS 73041900."
    )
    assert changes["status"]["because"] == (
        "Uploaded new document(s) mtc_pipe_test_cert.pdf (MILL_TEST_CERTIFICATE) resolved pending compliance issues."
    )


@pytest.mark.asyncio
async def test_stale_unknown_doc_type_is_refreshed_from_the_extraction_before_matching() -> None:
    """On Firestore the document dicts still say UNKNOWN after extraction; the extracted type wins."""
    ctx = _ctx(
        prev_missing=[MTC_REQ],
        curr_missing=[],
        documents=[*BASE_DOCS, _doc("d4", "mtc_pipe_test_cert.pdf", "UNKNOWN")],
        extracted=[*BASE_EXTRACTED, _extracted("d4", "MILL_TEST_CERTIFICATE")],
    )

    result = await reasoning.build(ctx)
    changes = _changes(result["reasoning_delta"])

    assert "Uploaded mtc_pipe_test_cert.pdf (MILL_TEST_CERTIFICATE) satisfies requirement" in (
        changes["missing_evidence.ME-MILL_TEST_CERTIFICATE"]["because"]
    )
    assert next(d for d in result["documents"] if d["document_id"] == "d4")["doc_type"] == "MILL_TEST_CERTIFICATE"


@pytest.mark.asyncio
async def test_core_requirement_maps_exactly_to_its_document_type() -> None:
    ctx = _ctx(
        prev_missing=[INVOICE_REQ],
        curr_missing=[],
        documents=[_doc("d2", "bill_of_lading.pdf", "BILL_OF_LADING"), _doc("d3", "packing_list.pdf", "PACKING_LIST"),
                   _doc("d9", "inv.pdf", "COMMERCIAL_INVOICE")],
        extracted=[_extracted("d2", "BILL_OF_LADING"), _extracted("d3", "PACKING_LIST"),
                   _extracted("d9", "COMMERCIAL_INVOICE")],
        prev_documents=("d2", "d3"),
    )

    changes = _changes((await reasoning.build(ctx))["reasoning_delta"])

    assert changes["missing_evidence.ME-CORE-COMMERCIAL_INVOICE"]["because"] == (
        "Uploaded inv.pdf (COMMERCIAL_INVOICE) satisfies requirement 'Commercial Invoice' for HS GENERAL."
    )


@pytest.mark.asyncio
async def test_new_document_of_another_type_is_not_credited_with_resolving_the_requirement() -> None:
    ctx = _ctx(
        prev_missing=[MTC_REQ],
        curr_missing=[],  # e.g. the tariff no longer asks for an MTC
        documents=[*BASE_DOCS, _doc("d4", "second_packing_list.pdf", "PACKING_LIST")],
        extracted=[*BASE_EXTRACTED, _extracted("d4", "PACKING_LIST")],
    )

    delta = (await reasoning.build(ctx))["reasoning_delta"]
    changes = _changes(delta)

    assert changes["missing_evidence.ME-MILL_TEST_CERTIFICATE"]["because"] == (
        "Requirement for Mill Test Certificate is no longer triggered."
    )
    assert changes["status"]["because"] == "Assessment inputs changed."
    assert "second_packing_list.pdf" not in delta["narrative"]


@pytest.mark.asyncio
async def test_new_document_without_a_type_never_matches_a_requirement() -> None:
    """The old `dtype in req_key` test made an empty doc_type match every requirement."""
    ctx = _ctx(
        prev_missing=[MTC_REQ],
        curr_missing=[],
        documents=[*BASE_DOCS, {"document_id": "d4", "filename": "mystery.pdf"}],
        extracted=BASE_EXTRACTED,
    )

    delta = (await reasoning.build(ctx))["reasoning_delta"]

    assert _changes(delta)["missing_evidence.ME-MILL_TEST_CERTIFICATE"]["because"] == (
        "Requirement for Mill Test Certificate is no longer triggered."
    )
    assert "mystery.pdf" not in delta["narrative"]


@pytest.mark.asyncio
async def test_resolved_requirement_with_no_new_documents_is_no_longer_triggered() -> None:
    ctx = _ctx(prev_missing=[MTC_REQ], curr_missing=[], documents=BASE_DOCS, extracted=BASE_EXTRACTED)

    changes = _changes((await reasoning.build(ctx))["reasoning_delta"])

    assert changes["missing_evidence.ME-MILL_TEST_CERTIFICATE"]["because"] == (
        "Requirement for Mill Test Certificate is no longer triggered."
    )


@pytest.mark.asyncio
async def test_status_change_does_not_cite_unrelated_new_documents() -> None:
    ctx = _ctx(
        prev_missing=[MTC_REQ],
        curr_missing=[MTC_REQ],  # nothing was resolved
        documents=[*BASE_DOCS, _doc("d4", "extra_invoice.pdf", "COMMERCIAL_INVOICE")],
        extracted=[*BASE_EXTRACTED, _extracted("d4", "COMMERCIAL_INVOICE")],
        final_status="SPECIALIST_REVIEW_REQUIRED",
    )

    delta = (await reasoning.build(ctx))["reasoning_delta"]

    assert _changes(delta)["status"]["because"] == "Assessment inputs changed."
    assert "extra_invoice.pdf" not in delta["narrative"]


@pytest.mark.asyncio
async def test_status_reason_cites_only_new_documents_whose_type_matches_a_resolved_requirement() -> None:
    ctx = _ctx(
        prev_missing=[MTC_REQ],
        curr_missing=[],
        documents=[
            *BASE_DOCS,
            _doc("d4", "mtc.pdf", "MILL_TEST_CERTIFICATE"),
            _doc("d5", "unrelated_packing.pdf", "PACKING_LIST"),
        ],
        extracted=[*BASE_EXTRACTED, _extracted("d4", "MILL_TEST_CERTIFICATE"), _extracted("d5", "PACKING_LIST")],
    )

    reason = _changes((await reasoning.build(ctx))["reasoning_delta"])["status"]["because"]

    assert "mtc.pdf (MILL_TEST_CERTIFICATE)" in reason
    assert "unrelated_packing.pdf" not in reason


@pytest.mark.asyncio
async def test_material_contradiction_keeps_its_specific_reason() -> None:
    ctx = _ctx(
        prev_missing=[],
        curr_missing=[],
        documents=BASE_DOCS,
        extracted=BASE_EXTRACTED,
        prev_status="COMPLIANT_FOR_SUBMISSION",
        final_status="MATERIAL_CONTRADICTION",
    )

    reason = _changes((await reasoning.build(ctx))["reasoning_delta"])["status"]["because"]

    assert reason == "Mathematical discrepancy or entity conflict detected exceeding allowable tolerance."


@pytest.mark.asyncio
async def test_an_explicit_status_reason_still_wins() -> None:
    ctx = _ctx(prev_missing=[], curr_missing=[], documents=BASE_DOCS, extracted=BASE_EXTRACTED,
               final_status="SPECIALIST_REVIEW_REQUIRED")
    ctx["status_reason"] = "Reviewer override."

    assert _changes((await reasoning.build(ctx))["reasoning_delta"])["status"]["because"] == "Reviewer override."


@pytest.mark.asyncio
async def test_first_iteration_is_an_initial_baseline() -> None:
    ctx = _ctx(prev_missing=[], curr_missing=[MTC_REQ], documents=BASE_DOCS, extracted=BASE_EXTRACTED,
               final_status="MISSING_EVIDENCE")
    ctx["previous_iteration"] = None

    delta = (await reasoning.build(ctx))["reasoning_delta"]

    assert delta["kind"] == "INITIAL"
    assert "3 trade documents" in delta["narrative"]


# --- plain words: no machine addresses, enum names or doubled full stops in the narrative a person reads -----------------


def _applied(path: str, document_id: str = "d4", **over: Any) -> dict[str, Any]:
    return {"correction_id": "cor-9", "status": "applied", "document_id": document_id, "path": path,
            "original_value": "0.35", "original_unit": "%", "value": "0.28", "unit": "%", "reason": "certificate prints 0.28", **over}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "words"),
    [
        ("test_results[20]", "certificate cell 21 of case_d_mtc_test_cert.pdf"),
        ("heat_numbers[0]", "heat number 1 of case_d_mtc_test_cert.pdf"),
        ("line_items[2].hs_code_declared", "line 3 · Hs code declared of case_d_mtc_test_cert.pdf"),
        ("total_gross_weight_kg", "total gross weight of case_d_mtc_test_cert.pdf"),
    ],
)
async def test_a_correction_is_narrated_with_a_label_and_a_file_name_not_a_machine_address(path: str, words: str) -> None:
    ctx = _ctx(prev_missing=[], curr_missing=[], documents=[*BASE_DOCS, _doc("d4", "case_d_mtc_test_cert.pdf", "MILL_TEST_CERTIFICATE")],
               extracted=[*BASE_EXTRACTED, _extracted("d4", "MILL_TEST_CERTIFICATE")], final_status="MISSING_EVIDENCE")
    ctx["corrections"] = [_applied(path)]

    narrative = (await reasoning.build(ctx))["reasoning_delta"]["narrative"]

    assert f"Correction by the authorised agent to {words} (certificate prints 0.28): 0.35 % became 0.28 %." in narrative
    assert "doc-" not in narrative and "test_results[" not in narrative and "d4" not in narrative


@pytest.mark.asyncio
async def test_an_undone_correction_is_narrated_the_same_way() -> None:
    ctx = _ctx(prev_missing=[], curr_missing=[], documents=[*BASE_DOCS, _doc("d4", "case_d_mtc_test_cert.pdf", "MILL_TEST_CERTIFICATE")],
               extracted=[*BASE_EXTRACTED, _extracted("d4", "MILL_TEST_CERTIFICATE")], final_status="MISSING_EVIDENCE")
    ctx["previous_iteration"]["corrections"] = [_applied("test_results[20]")]
    ctx["corrections"] = []

    narrative = (await reasoning.build(ctx))["reasoning_delta"]["narrative"]

    assert "A correction to certificate cell 21 of case_d_mtc_test_cert.pdf was undone: the value is back to 0.35 %." in narrative


@pytest.mark.asyncio
async def test_a_correction_to_an_unknown_document_still_reads_naturally() -> None:
    ctx = _ctx(prev_missing=[], curr_missing=[], documents=BASE_DOCS, extracted=BASE_EXTRACTED, final_status="MISSING_EVIDENCE")
    ctx["corrections"] = [_applied("test_results[0]", document_id="gone")]

    assert "to certificate cell 1 (certificate prints 0.28)" in (await reasoning.build(ctx))["reasoning_delta"]["narrative"]


def test_the_narrative_shows_statuses_as_words_and_does_not_double_a_full_stop() -> None:
    narrative = reasoning._narrate([
        {"field": "status", "from": "MATERIAL_CONTRADICTION", "to": "SPECIALIST_REVIEW_REQUIRED", "because": "1 correction(s) changed the inputs"},
        {"field": "M-001", "from": "MATERIAL", "to": "PASS", "because": "Certified chemistry reads as non-alloy. Elements not reported: Zr."},
    ])

    assert "Compliance status updated from Material Contradiction to Specialist Review Required (1 correction(s) changed the inputs)." in narrative
    assert "Check M-001 changed from MATERIAL to PASS: Certified chemistry reads as non-alloy. Elements not reported: Zr." in narrative
    assert ".." not in narrative
    assert reasoning._plain("not_a_status") == "not_a_status" and reasoning._plain("PASS") == "PASS" and reasoning._plain("Mixed Case") == "Mixed Case"
