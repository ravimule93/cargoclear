"""Entity checks (E-consignee / E-consignor / E-vessel) also report AGREEMENT, with evidence.

They used to emit nothing when the documents agreed, so those fields were never cited by any check and the
confidence routing could not see them: a consignee read at 0.55 on every document (agreeing) caused no review.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents import extraction
from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LineItem
from app.services import calculation, confidence
from app.services.calculation import check_entity_alignment

ATTRIBUTES = {"consignee": "E-consignee", "consignor": "E-consignor", "vessel_or_flight": "E-vessel"}


def ref(value, conf=0.99, page=1, y=10) -> FieldRef:
    return FieldRef(value=value, confidence=conf, bbox=BBox(page=page, ymin=y, xmin=20, ymax=y + 20, xmax=40))


def doc(document_id: str, doc_type: str = "PACKING_LIST", **fields) -> ExtractedDocument:
    return ExtractedDocument(document_id=document_id, doc_type=doc_type, doc_type_confidence=0.99, **fields)


def by_id(results) -> dict[str, Any]:
    ids = [r.check_id for r in results]
    assert len(ids) == len(set(ids)), f"duplicate check ids: {ids}"
    return {r.check_id: r for r in results}


# ---------------------------------------------------------------------------
# agreement
# ---------------------------------------------------------------------------


def test_two_documents_that_agree_give_a_pass_with_two_evidence_entries() -> None:
    results = by_id(check_entity_alignment([
        doc("inv", "COMMERCIAL_INVOICE", consignee=ref("ACME PTE LTD", page=2)),
        doc("pl", consignee=ref("ACME PTE LTD", page=3, y=50)),
    ]))

    check = results["E-consignee"]
    assert check.severity == "PASS"
    assert check.message == "consignee is consistent across 2 documents: ['ACME PTE LTD']"
    assert check.assumptions == []
    assert [(e["doc"], e["field"], e["page"], e["raw_value"]) for e in check.evidence] == [
        ("inv", "consignee", 2, "ACME PTE LTD"), ("pl", "consignee", 3, "ACME PTE LTD"),
    ]
    assert all(e["bbox"] and e["bbox"]["xmax"] == 40 for e in check.evidence)


def test_four_documents_that_agree_give_four_evidence_entries() -> None:
    docs = [doc(f"d{i}", consignor=ref("BHARAT SEAMLESS PIPES LTD")) for i in range(4)]

    check = by_id(check_entity_alignment(docs))["E-consignor"]

    assert check.severity == "PASS"
    assert check.message == "consignor is consistent across 4 documents: ['BHARAT SEAMLESS PIPES LTD']"
    assert [e["doc"] for e in check.evidence] == ["d0", "d1", "d2", "d3"]


def test_the_vessel_check_has_its_own_id_and_passes_when_two_documents_agree() -> None:
    docs = [doc("bol", "BILL_OF_LADING", vessel_or_flight=ref("EVER GIVEN V-104E")),
            doc("inv", "COMMERCIAL_INVOICE", vessel_or_flight=ref("EVER GIVEN V-104E"))]

    check = by_id(check_entity_alignment(docs))["E-vessel"]

    assert (check.severity, check.message) == (
        "PASS", "vessel_or_flight is consistent across 2 documents: ['EVER GIVEN V-104E']"
    )


@pytest.mark.parametrize(
    ("a", "b"),
    [("ACME PTE. LTD.", "Acme Pte Ltd"), ("  Acme   Pte  Ltd ", "ACME PTE LTD"), ("A.C.M.E, PTE LTD", "acme pte ltd")],
)
def test_punctuation_case_and_spacing_differences_still_agree(a: str, b: str) -> None:
    check = by_id(check_entity_alignment([doc("a", consignee=ref(a)), doc("b", "BILL_OF_LADING", consignee=ref(b))]))[
        "E-consignee"
    ]

    assert check.severity == "PASS"
    assert "consistent across 2 documents" in check.message
    assert {e["raw_value"] for e in check.evidence} == {a.strip(), b.strip()}  # what each document prints


# ---------------------------------------------------------------------------
# nothing to compare
# ---------------------------------------------------------------------------


def test_one_document_stating_the_field_gives_no_check() -> None:
    results = check_entity_alignment([doc("a", consignee=ref("ACME PTE LTD")), doc("b", "BILL_OF_LADING")])
    assert results == []


def test_no_document_stating_the_field_gives_no_check() -> None:
    assert check_entity_alignment([doc("a"), doc("b", "BILL_OF_LADING")]) == []
    assert check_entity_alignment([]) == []


def test_a_field_with_no_value_does_not_count_as_stating_it() -> None:
    results = check_entity_alignment([doc("a", consignee=ref("ACME PTE LTD")), doc("b", consignee=ref(None))])
    assert results == []


@pytest.mark.parametrize("empty", ["", "   ", "...", "!!!", " , . "])
def test_a_value_that_normalises_to_nothing_is_ignored(empty: str) -> None:
    one_real = check_entity_alignment([doc("a", consignee=ref("ACME PTE LTD")), doc("b", consignee=ref(empty))])
    assert one_real == []  # only one document really states it

    two_real = by_id(check_entity_alignment([
        doc("a", consignee=ref("ACME PTE LTD")), doc("b", consignee=ref(empty)), doc("c", consignee=ref("ACME PTE LTD")),
    ]))["E-consignee"]
    assert two_real.severity == "PASS"
    assert two_real.message == "consignee is consistent across 2 documents: ['ACME PTE LTD']"
    assert [e["doc"] for e in two_real.evidence] == ["a", "c"]


# ---------------------------------------------------------------------------
# disagreement is unchanged
# ---------------------------------------------------------------------------


def test_disagreement_is_still_material_with_the_established_message() -> None:
    docs = [doc("a", consignee=ref("ACME PTE LTD")), doc("b", "BILL_OF_LADING", consignee=ref("OTHER TRADING CO"))]

    check = by_id(check_entity_alignment(docs))["E-consignee"]

    assert check.severity == "MATERIAL"
    assert check.message == "Inconsistent consignee across documents: ['ACME PTE LTD', 'OTHER TRADING CO']."
    assert [e["doc"] for e in check.evidence] == ["a", "b"]


def test_each_attribute_is_judged_on_its_own() -> None:
    docs = [
        doc("a", consignee=ref("ACME PTE LTD"), consignor=ref("SELLER ONE"), vessel_or_flight=ref("MV ONE")),
        doc("b", consignee=ref("ACME PTE LTD"), consignor=ref("SELLER TWO")),
    ]

    results = by_id(check_entity_alignment(docs))

    assert {k: v.severity for k, v in results.items()} == {"E-consignee": "PASS", "E-consignor": "MATERIAL"}
    # the vessel is stated once: nothing to compare


@pytest.mark.asyncio
async def test_check_ids_stay_unique_in_the_engine_with_duplicates_and_entities() -> None:
    docs = [
        doc("pl-1", consignee=ref("ACME")), doc("pl-2", consignee=ref("ACME")),
        doc("inv", "COMMERCIAL_INVOICE", consignee=ref("ACME")),
    ]

    ids = [c["check_id"] for c in (await calculation.run({"extracted": docs}))["checks"]]

    assert len(ids) == len(set(ids))
    assert "E-consignee" in ids and "D-DUP-PACKING_LIST" in ids


# ---------------------------------------------------------------------------
# the point: confidence can now see an agreeing, low-confidence entity
# ---------------------------------------------------------------------------


def _bundle(consignee_confidence: float) -> list[ExtractedDocument]:
    """Invoice + packing list + BoL; the HS codes (cited by H-002) are read confidently, the consignee is not."""
    def line() -> LineItem:
        return LineItem(description=ref("pipes"), quantity=ref("1"), net_weight_kg=ref(1.0),
                        gross_weight_kg=ref(1.0), hs_code_declared=ref("73041900"))

    consignee = lambda: ref("SINGAPORE PRECISION PIPING PTE LTD", consignee_confidence)  # noqa: E731
    return [
        doc("inv", "COMMERCIAL_INVOICE", consignee=consignee(), line_items=[line()]),
        doc("pl", consignee=consignee(), line_items=[line()]),
        doc("bol", "BILL_OF_LADING", consignee=consignee()),
    ]


@pytest.mark.asyncio
async def test_a_low_confidence_consignee_that_agrees_now_forces_interactive_review() -> None:
    ctx = await confidence.route(await calculation.run({"extracted": _bundle(0.80)}))

    assert {c["check_id"]: c["severity"] for c in ctx["checks"]}["E-consignee"] == "PASS"
    assert ctx["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"
    assert ctx["confidence"]["min_overall_confidence"] == 0.80
    assert {(e["document_id"], e["field"], e["used_by"][0]) for e in ctx["confidence"]["low_confidence_fields"]} == {
        ("inv", "consignee", "E-consignee"), ("pl", "consignee", "E-consignee"), ("bol", "consignee", "E-consignee"),
    }


@pytest.mark.asyncio
async def test_a_consignee_read_at_055_on_every_document_is_manual_entry_not_an_auto_flag() -> None:
    ctx = await confidence.route(await calculation.run({"extracted": _bundle(0.55)}))

    assert ctx["confidence"]["action"] == "MANUAL_ENTRY"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"
    assert "consignee" in ctx["confidence"]["reason"]


@pytest.mark.asyncio
async def test_a_confident_agreeing_consignee_changes_nothing() -> None:
    ctx = await confidence.route(await calculation.run({"extracted": _bundle(0.99)}))
    assert ctx["confidence"]["action"] in ("AUTO_ACCEPT", "AUTO_FLAG")
    assert "force_status" not in ctx


# ---------------------------------------------------------------------------
# Case C
# ---------------------------------------------------------------------------

CASE_C = {"inv-001": "commercial_invoice.pdf", "bol-001": "bill_of_lading.pdf", "pl-001": "packing_list.pdf",
          "mtc-001": "mtc_pipe_test_cert.pdf"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("with_mtc", "documents"), [(False, 3), (True, 4)])
async def test_case_c_has_entity_pass_checks_for_consignee_and_consignor_but_not_the_vessel(with_mtc, documents) -> None:
    wanted = ["inv-001", "bol-001", "pl-001"] + (["mtc-001"] if with_mtc else [])
    docs = [extraction._generate_fixture_for_file(i, CASE_C[i]) for i in wanted]

    checks = {c["check_id"]: c for c in (await calculation.run({"extracted": docs}))["checks"]}

    assert checks["E-consignee"]["severity"] == "PASS"
    assert checks["E-consignor"]["severity"] == "PASS"
    assert "E-vessel" not in checks  # only the Bill of Lading states a vessel
    assert f"consistent across {documents} documents" in checks["E-consignee"]["message"]
    assert len(checks["E-consignee"]["evidence"]) == documents
