"""H-003: the HS code a certificate states must agree with the commercial invoice (or, failing that, the packing list).

Same comparison rules as H-002 (digits only; 8 digits when every code states 8, otherwise 6 with a WARN and an
assumption; differing sets are MATERIAL; malformed codes are never compared). One check per certificate TYPE, with
id ``H-003-<DOC_TYPE>``. A certificate that states no HS code is not checked.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.grounding import run_grounding_agent
from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LineItem
from app.services import calculation, confidence
from app.services.calculation import check_hs_consistency
from app.services.orchestrator import resolve_final_status

SIX_DIGIT_ASSUMPTION = "compared at 6 digits; 8-digit AHTN code not stated"
MTC = "MILL_TEST_CERTIFICATE"
COO = "CERTIFICATE_OF_ORIGIN"
PHYTO = "PHYTOSANITARY"
IDS = {"COMMERCIAL_INVOICE": "inv-001", "PACKING_LIST": "pl-001", "BILL_OF_LADING": "bol-001", MTC: "mtc-001",
       COO: "coo-001", PHYTO: "phy-001"}


def ref(value, conf=0.97, page=1) -> FieldRef:
    return FieldRef(value=value, confidence=conf, bbox=BBox(page=page, ymin=10, xmin=20, ymax=30, xmax=40))


def doc(doc_type: str, codes=(), header=None, document_id: str | None = None) -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id or IDS[doc_type],
        doc_type=doc_type,
        doc_type_confidence=0.99,
        hs_code_header=ref(header, page=2) if header is not None else None,
        line_items=[
            LineItem(
                description=ref("pipes"), quantity=ref("1"), net_weight_kg=ref(1.0), gross_weight_kg=ref(1.0),
                hs_code_declared=ref(code, page=3),
            )
            for code in codes
        ],
    )


def invoice(*codes, header=None) -> ExtractedDocument:
    return doc("COMMERCIAL_INVOICE", codes, header)


def packing(*codes, header=None) -> ExtractedDocument:
    return doc("PACKING_LIST", codes, header)


def mtc(*codes, header=None, document_id=None) -> ExtractedDocument:
    return doc(MTC, codes, header, document_id)


async def checks_for(*docs: ExtractedDocument) -> dict[str, dict[str, Any]]:
    ctx = await calculation.run({"extracted": list(docs)})
    ids = [c["check_id"] for c in ctx["checks"]]
    assert len(ids) == len(set(ids)), f"duplicate check ids: {ids}"
    return {c["check_id"]: c for c in ctx["checks"]}


def h003(checks: dict[str, dict[str, Any]], doc_type: str = MTC) -> dict[str, Any]:
    return checks[f"H-003-{doc_type}"]


def no_h003(checks: dict[str, dict[str, Any]]) -> bool:
    return not [i for i in checks if i.startswith("H-003")]


# ---------------------------------------------------------------------------
# agreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_certificate_with_the_invoices_code_passes() -> None:
    checks = await checks_for(invoice("73041900"), packing("73041900"), mtc("73041900"))

    check = h003(checks)
    assert check["severity"] == "PASS"
    assert check["assumptions"] == []
    assert "Mill Test Certificate" in check["message"]
    assert "73041900" in check["message"]
    assert checks["H-002"]["severity"] == "PASS"  # H-002 is untouched


@pytest.mark.asyncio
@pytest.mark.parametrize("formatted", ["7304.19.00", "7304 19 00", " 73041900 ", 73041900, 73041900.0])
async def test_formatted_and_plain_certificate_codes_are_equal(formatted) -> None:
    checks = await checks_for(invoice("73041900"), mtc(formatted))
    assert h003(checks)["severity"] == "PASS"


@pytest.mark.asyncio
async def test_the_header_code_alone_is_enough_and_is_compared() -> None:
    checks = await checks_for(invoice("73041900"), mtc(header="73041900"))
    assert h003(checks)["severity"] == "PASS"

    checks = await checks_for(invoice("73041900"), mtc(header="73041100"))
    assert h003(checks)["severity"] == "MATERIAL"


@pytest.mark.asyncio
async def test_header_and_line_codes_on_the_certificate_are_both_compared() -> None:
    checks = await checks_for(invoice("73041900"), mtc("73041100", header="73041900"))
    assert h003(checks)["severity"] == "MATERIAL"


# ---------------------------------------------------------------------------
# disagreement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_certificate_with_a_different_code_is_a_material_divergence() -> None:
    checks = await checks_for(invoice("73041900"), packing("73041900"), mtc("73041100"))

    check = h003(checks)
    assert check["severity"] == "MATERIAL"
    assert "73041100" in check["message"] and "73041900" in check["message"]
    assert "8 digits" in check["message"]
    assert check["assumptions"] == []
    assert checks["H-002"]["severity"] == "PASS"  # the invoice and the packing list agree; the certificate does not


@pytest.mark.asyncio
async def test_a_wrong_certificate_code_makes_the_pipeline_status_a_material_contradiction() -> None:
    ctx = await calculation.run({"extracted": [invoice("73041900"), packing("73041900"), doc("BILL_OF_LADING"),
                                               mtc("73041100")]})
    assert ctx["math_status"] == "MATERIAL_CONTRADICTION"

    ctx = await run_grounding_agent(ctx)
    ctx = await confidence.route(ctx)
    assert resolve_final_status(ctx) == "MATERIAL_CONTRADICTION"


@pytest.mark.asyncio
async def test_a_matching_certificate_does_not_change_the_pipeline_status() -> None:
    ctx = await calculation.run({"extracted": [invoice("73041900"), packing("73041900"), doc("BILL_OF_LADING"),
                                               mtc("73041900")]})
    assert not [c for c in ctx["checks"] if c["severity"] == "MATERIAL"]


@pytest.mark.asyncio
async def test_a_six_digit_certificate_against_an_eight_digit_invoice_is_a_warn_with_the_assumption() -> None:
    check = h003(await checks_for(invoice("73041900"), mtc("730419")))

    assert check["severity"] == "WARN"
    assert check["assumptions"] == [SIX_DIGIT_ASSUMPTION]
    assert "6 digits" in check["message"]


@pytest.mark.asyncio
async def test_a_six_digit_certificate_that_differs_at_six_digits_is_material() -> None:
    check = h003(await checks_for(invoice("73041900"), mtc("730411")))
    assert check["severity"] == "MATERIAL"
    assert "6 digits" in check["message"]


@pytest.mark.asyncio
async def test_a_malformed_certificate_code_is_named_and_never_compared() -> None:
    check = h003(await checks_for(invoice("73041900"), mtc("N/A")))

    assert check["severity"] == "WARN"
    assert "N/A" in check["message"]
    assert "not compared" in check["message"]


@pytest.mark.asyncio
async def test_a_seven_digit_certificate_code_carries_the_leading_zero_hint() -> None:
    check = h003(await checks_for(invoice("73041900"), mtc("7304190")))
    assert "leading zero" in check["message"]


# ---------------------------------------------------------------------------
# when H-003 does not apply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_certificate_without_any_hs_code_produces_no_h003() -> None:
    checks = await checks_for(invoice("73041900"), packing("73041900"), mtc())
    assert no_h003(checks)

    blank = doc(MTC)
    blank.hs_code_header = ref(None)
    assert no_h003(await checks_for(invoice("73041900"), blank))


@pytest.mark.asyncio
async def test_a_certificate_line_with_an_empty_code_counts_as_no_code() -> None:
    assert no_h003(await checks_for(invoice("73041900"), mtc("")))


@pytest.mark.asyncio
async def test_with_no_invoice_the_packing_list_is_the_reference() -> None:
    checks = await checks_for(packing("73041900"), mtc("73041100"))

    check = h003(checks)
    assert check["severity"] == "MATERIAL"
    assert "Packing List" in check["message"]
    assert {e["doc"] for e in check["evidence"]} == {"mtc-001", "pl-001"}

    assert h003(await checks_for(packing("73041900"), mtc("73041900")))["severity"] == "PASS"


@pytest.mark.asyncio
async def test_an_invoice_that_states_no_code_hands_over_to_the_packing_list() -> None:
    checks = await checks_for(invoice(), packing("73041900"), mtc("73041900"))

    assert h003(checks)["severity"] == "PASS"
    assert {e["doc"] for e in h003(checks)["evidence"]} == {"mtc-001", "pl-001"}


@pytest.mark.asyncio
async def test_the_invoice_wins_over_the_packing_list_as_the_reference() -> None:
    checks = await checks_for(invoice("73041900"), packing("73041100"), mtc("73041900"))

    assert h003(checks)["severity"] == "PASS"  # compared with the invoice
    assert checks["H-002"]["severity"] == "MATERIAL"  # H-002 still reports the invoice/packing-list divergence


@pytest.mark.asyncio
async def test_with_neither_invoice_nor_packing_list_codes_there_is_no_h003_at_all() -> None:
    assert no_h003(await checks_for(mtc("73041900")))
    assert no_h003(await checks_for(invoice(), packing(), mtc("73041900")))
    assert no_h003(await checks_for(doc("BILL_OF_LADING"), mtc("73041900")))


@pytest.mark.asyncio
async def test_a_bundle_without_certificates_has_no_h003() -> None:
    assert no_h003(await checks_for(invoice("73041900"), packing("73041900")))


# ---------------------------------------------------------------------------
# several certificates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_certificate_types_give_two_distinct_ids() -> None:
    checks = await checks_for(
        invoice("73041900"), packing("73041900"), mtc("73041900"), doc(COO, ["73041100"]), doc(PHYTO, ["73041900"])
    )

    assert sorted(i for i in checks if i.startswith("H-003")) == [
        "H-003-CERTIFICATE_OF_ORIGIN", "H-003-MILL_TEST_CERTIFICATE", "H-003-PHYTOSANITARY",
    ]
    assert h003(checks, MTC)["severity"] == "PASS"
    assert h003(checks, COO)["severity"] == "MATERIAL"
    assert h003(checks, PHYTO)["severity"] == "PASS"
    assert "Certificate Of Origin" in h003(checks, COO)["message"]


@pytest.mark.asyncio
async def test_two_certificates_of_one_type_compare_only_the_first() -> None:
    first = mtc("73041900", document_id="mtc-first")
    second = mtc("73041100", document_id="mtc-second")
    checks = await checks_for(invoice("73041900"), first, second)

    assert h003(checks)["severity"] == "PASS"  # the second, wrong one is not compared
    assert {e["doc"] for e in h003(checks)["evidence"]} == {"mtc-first", "inv-001"}
    assert checks["D-DUP-MILL_TEST_CERTIFICATE"]["severity"] == "WARN"  # the duplicate is flagged elsewhere


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_cites_the_certificate_fields_and_the_reference_side_with_page_and_bbox() -> None:
    check = h003(await checks_for(invoice("73041900"), mtc("73041100", header="73041100")))

    entries = {(e["doc"], e["field"], e.get("line_item")): e for e in check["evidence"]}
    assert set(entries) == {
        ("mtc-001", "hs_code_declared", 0),
        ("mtc-001", "hs_code_header", None),
        ("inv-001", "hs_code_declared", 0),
    }
    for entry in entries.values():
        assert entry["bbox"]["xmax"] == 40 and entry["page"] in (2, 3)
    assert entries[("mtc-001", "hs_code_header", None)]["page"] == 2
    assert entries[("mtc-001", "hs_code_declared", 0)]["raw_value"] == "73041100"
    assert entries[("inv-001", "hs_code_declared", 0)]["raw_value"] == "73041900"


# ---------------------------------------------------------------------------
# the shared comparison did not change H-002
# ---------------------------------------------------------------------------


def test_h002_is_unchanged_by_the_shared_comparison() -> None:
    same = check_hs_consistency(invoice("73041900"), packing("73041900"))
    assert (same.check_id, same.severity, same.message) == (
        "H-002", "PASS", "Declared HS codes are consistent: ['73041900']."
    )
    diff = check_hs_consistency(invoice("73041900"), packing("73041100"))
    assert diff.message == "HS code divergence detected at 8 digits. Invoice: ['73041900'], Packing List: ['73041100']."


# ---------------------------------------------------------------------------
# a certificate may cover only SOME of the invoice's lines (real certificates are per product / heat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_certificate_for_one_of_two_invoice_lines_passes() -> None:
    checks = await checks_for(invoice("73041900", "73043100"), packing("73041900", "73043100"), mtc("73041900"))

    check = h003(checks)
    assert check["severity"] == "PASS", check["message"]
    assert check["assumptions"] == []
    assert check["message"] == (
        "Mill Test Certificate vs Invoice: Mill Test Certificate states 1 of the 2 codes declared on the Invoice: "
        "['73041900']."
    )


@pytest.mark.asyncio
async def test_a_subset_certificate_does_not_make_the_pipeline_a_material_contradiction() -> None:
    ctx = await calculation.run({"extracted": [invoice("73041900", "73043100"), packing("73041900", "73043100"),
                                               doc("BILL_OF_LADING"), mtc("73041900")]})
    assert not [c for c in ctx["checks"] if c["severity"] == "MATERIAL"]
    assert ctx["math_status"] != "MATERIAL_CONTRADICTION"


@pytest.mark.asyncio
async def test_the_message_counts_the_codes_on_both_sides() -> None:
    four = invoice("73041900", "73043100", "73063000", "73069000")
    check = h003(await checks_for(four, mtc("73041900", "7306.30.00")))

    assert check["severity"] == "PASS"
    assert "states 2 of the 4 codes declared on the Invoice: ['73041900', '73063000']." in check["message"]


@pytest.mark.asyncio
async def test_the_header_and_line_copies_of_one_code_count_once() -> None:
    check = h003(await checks_for(invoice("73041900", "73043100"), mtc("73041900", header="73041900")))
    assert check["severity"] == "PASS"
    assert "states 1 of the 2 codes" in check["message"]


@pytest.mark.asyncio
async def test_a_subset_certificate_against_the_packing_list_reference_passes_too() -> None:
    check = h003(await checks_for(packing("73041900", "73043100"), mtc("73043100")))
    assert check["severity"] == "PASS"
    assert "states 1 of the 2 codes declared on the Packing List: ['73043100']." in check["message"]


@pytest.mark.asyncio
async def test_one_valid_and_one_foreign_certificate_code_is_material_and_names_the_foreign_one() -> None:
    check = h003(await checks_for(invoice("73041900", "73043100"), mtc("73041900", "73041100")))

    assert check["severity"] == "MATERIAL"
    assert check["message"].endswith("Not declared on the Invoice: ['73041100'].")  # only the foreign code is named


@pytest.mark.asyncio
async def test_a_certificate_code_that_is_not_on_the_invoice_at_all_is_still_material() -> None:
    check = h003(await checks_for(invoice("73041900", "73043100"), mtc("73041100")))
    assert check["severity"] == "MATERIAL"
    assert "73041100" in check["message"]


@pytest.mark.asyncio
async def test_a_certificate_with_the_invoices_one_code_plus_an_extra_is_material() -> None:
    check = h003(await checks_for(invoice("73041900"), mtc("73041900", "73043100")))
    assert check["severity"] == "MATERIAL"
    assert "['73043100']" in check["message"]


@pytest.mark.asyncio
async def test_a_six_digit_subset_is_a_warn_with_the_assumption() -> None:
    check = h003(await checks_for(invoice("73041900", "73043100"), mtc("730419")))

    assert check["severity"] == "WARN"
    assert check["assumptions"] == [SIX_DIGIT_ASSUMPTION]
    assert "states 1 of the 2 codes declared on the Invoice: ['730419']." in check["message"]
    assert "6 digits" in check["message"]


@pytest.mark.asyncio
async def test_a_six_digit_certificate_code_not_on_the_invoice_is_material() -> None:
    check = h003(await checks_for(invoice("73041900", "73043100"), mtc("730411")))
    assert check["severity"] == "MATERIAL"


@pytest.mark.asyncio
async def test_a_subset_with_a_malformed_certificate_code_is_a_warn_naming_it() -> None:
    check = h003(await checks_for(invoice("73041900", "73043100"), mtc("73041900", "N/A")))
    assert check["severity"] == "WARN"
    assert "states 1 of the 2 codes" in check["message"]
    assert "N/A" in check["message"] and "not compared" in check["message"]


@pytest.mark.asyncio
async def test_an_equal_set_still_uses_the_agreement_message() -> None:
    check = h003(await checks_for(invoice("73041900", "73043100"), mtc("73041900", "73043100")))
    assert check["severity"] == "PASS"
    assert check["message"].endswith("Declared HS codes are consistent: ['73041900', '73043100'].")


@pytest.mark.asyncio
async def test_h002_still_treats_a_subset_as_a_divergence() -> None:
    """Invoice vs packing list is a symmetric comparison: a packing list with fewer codes is a real divergence."""
    checks = await checks_for(invoice("73041900", "73043100"), packing("73041900"))
    assert checks["H-002"]["severity"] == "MATERIAL"
    assert checks["H-002"]["message"] == (
        "HS code divergence detected at 8 digits. Invoice: ['73041900', '73043100'], Packing List: ['73041900']."
    )

    reverse = await checks_for(invoice("73041900"), packing("73041900", "73043100"))
    assert reverse["H-002"]["severity"] == "MATERIAL"


def test_the_shared_comparison_defaults_to_requiring_equal_sets() -> None:
    reference = calculation._collect_hs_codes(invoice("73041900", "73043100"))
    other = calculation._collect_hs_codes(mtc("73041900"))

    assert calculation._compare_hs_codes(reference, other).severity == "MATERIAL"
    assert calculation._compare_hs_codes(reference, other, other_may_be_subset=True).severity == "PASS"
