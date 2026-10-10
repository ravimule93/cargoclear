"""H-002: declared HS codes must agree between the commercial invoice and the packing list.

Codes are compared as digits only, at 8 digits when every code states 8, otherwise at 6 digits with a WARN
(the 8-digit AHTN code is then an assumption). Malformed codes are never compared.
"""

from __future__ import annotations

import pytest

from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LineItem
from app.services.calculation import check_hs_consistency

SIX_DIGIT_ASSUMPTION = "compared at 6 digits; 8-digit AHTN code not stated"


def ref(value) -> FieldRef:
    return FieldRef(value=value, confidence=0.97, bbox=BBox(page=1, ymin=0, xmin=0, ymax=10, xmax=10))


def doc(doc_type: str, codes=(), header=None, document_id: str | None = None) -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id or ("inv-001" if doc_type == "COMMERCIAL_INVOICE" else "pl-001"),
        doc_type=doc_type,
        doc_type_confidence=0.99,
        hs_code_header=ref(header) if header is not None else None,
        line_items=[
            LineItem(
                description=ref("pipes"), quantity=ref("1"), net_weight_kg=ref(1.0),
                gross_weight_kg=ref(1.0), hs_code_declared=ref(code),
            )
            for code in codes
        ],
    )


def invoice(*codes, header=None) -> ExtractedDocument:
    return doc("COMMERCIAL_INVOICE", codes, header)


def packing(*codes, header=None) -> ExtractedDocument:
    return doc("PACKING_LIST", codes, header)


# ---------------------------------------------------------------------------
# Equal codes
# ---------------------------------------------------------------------------


def test_plain_equal_codes_pass_with_the_established_message() -> None:
    r = check_hs_consistency(invoice("73041900"), packing("73041900"))
    assert r.check_id == "H-002"
    assert r.severity == "PASS"
    assert r.assumptions == []
    assert r.message == "Declared HS codes are consistent: ['73041900']."


@pytest.mark.parametrize("formatted", ["7304.19.00", "7304 19 00", "7304-19-00", " 73041900 ", "7304.19.00 "])
def test_formatted_and_plain_codes_are_equal(formatted: str) -> None:
    r = check_hs_consistency(invoice(formatted), packing("73041900"))
    assert r.severity == "PASS"
    assert r.assumptions == []


def test_formatting_differences_on_both_sides_are_normalised() -> None:
    r = check_hs_consistency(invoice("7304.19.00", "7306 30 00"), packing("73041900", "7306.30.00"))
    assert r.severity == "PASS"
    assert "['73041900', '73063000']" in r.message


@pytest.mark.parametrize("numeric", [73041900, 73041900.0])
def test_numeric_values_read_as_the_same_code(numeric) -> None:
    assert check_hs_consistency(invoice(numeric), packing("73041900")).severity == "PASS"


def test_ten_digit_national_line_is_truncated_to_eight_and_the_truncation_is_stated() -> None:
    r = check_hs_consistency(invoice("7304190000"), packing("73041900"))

    assert r.severity == "PASS"
    assert r.assumptions == []  # truncating a national suffix is a stated rule, not an assumption
    assert "truncated to 8 digits" in r.message
    assert "7304190000" in r.message


def test_national_suffixes_beyond_eight_digits_are_not_compared() -> None:
    r = check_hs_consistency(invoice("7304.19.00.11"), packing("73041900.99"))
    assert r.severity == "PASS"


# ---------------------------------------------------------------------------
# 6-digit comparison => WARN
# ---------------------------------------------------------------------------


def test_six_digit_code_against_eight_digit_with_the_same_prefix_warns() -> None:
    r = check_hs_consistency(invoice("730419"), packing("73041900"))

    assert r.severity == "WARN"
    assert r.assumptions == [SIX_DIGIT_ASSUMPTION]
    assert "6 digits" in r.message
    assert "['730419']" in r.message


def test_seven_digit_codes_are_compared_at_six_digits() -> None:
    r = check_hs_consistency(invoice("7304190"), packing("73041900"))
    assert r.severity == "WARN"
    assert r.assumptions == [SIX_DIGIT_ASSUMPTION]


def test_one_short_code_moves_the_whole_comparison_to_six_digits() -> None:
    r = check_hs_consistency(invoice("73041900", "730630"), packing("73041900", "73063000"))
    assert r.severity == "WARN"
    assert "['730419', '730630']" in r.message


def test_equal_six_digit_codes_on_both_sides_still_warn() -> None:
    r = check_hs_consistency(invoice("7304.19"), packing("730419"))
    assert r.severity == "WARN"
    assert r.assumptions == [SIX_DIGIT_ASSUMPTION]


def test_different_six_digit_codes_are_material() -> None:
    r = check_hs_consistency(invoice("730419"), packing("730431"))

    assert r.severity == "MATERIAL"
    assert r.assumptions == []
    assert "6 digits" in r.message
    assert "['730419']" in r.message
    assert "['730431']" in r.message


def test_a_six_digit_prefix_that_differs_from_an_eight_digit_code_is_material() -> None:
    r = check_hs_consistency(invoice("730419"), packing("73043100"))
    assert r.severity == "MATERIAL"


# ---------------------------------------------------------------------------
# Different codes at the comparison level
# ---------------------------------------------------------------------------


def test_different_eight_digit_codes_are_material_and_the_message_lists_both_sets() -> None:
    r = check_hs_consistency(invoice("73041900"), packing("73043100"))

    assert r.severity == "MATERIAL"
    assert r.assumptions == []
    assert "8 digits" in r.message
    assert "Invoice: ['73041900']" in r.message
    assert "Packing List: ['73043100']" in r.message


def test_a_code_missing_on_one_side_makes_the_sets_differ() -> None:
    r = check_hs_consistency(invoice("73041900", "73063000"), packing("73041900"))
    assert r.severity == "MATERIAL"


# ---------------------------------------------------------------------------
# Header-level codes
# ---------------------------------------------------------------------------


def test_header_only_code_on_the_invoice_is_collected() -> None:
    r = check_hs_consistency(invoice(header="7304.19.00"), packing("73041900"))
    assert r.severity == "PASS"
    assert ("inv-001", "hs_code_header") in {(e["doc"], e["field"]) for e in r.evidence}


def test_header_only_code_on_the_packing_list_is_collected() -> None:
    r = check_hs_consistency(invoice("73041900"), packing(header="73041900"))
    assert r.severity == "PASS"
    assert ("pl-001", "hs_code_header") in {(e["doc"], e["field"]) for e in r.evidence}


def test_header_and_line_codes_of_one_document_are_both_compared() -> None:
    same = check_hs_consistency(invoice("73041900", header="73041900"), packing("73041900"))
    differs = check_hs_consistency(invoice("73041900", header="73043100"), packing("73041900"))
    assert same.severity == "PASS"
    assert differs.severity == "MATERIAL"
    assert "['73041900', '73043100']" in differs.message


def test_evidence_names_the_fields_each_document_contributed() -> None:
    r = check_hs_consistency(invoice("73041900"), packing("73041900"))
    assert [(e["doc"], e["field"]) for e in r.evidence] == [
        ("inv-001", "hs_code_declared"),
        ("pl-001", "hs_code_declared"),
    ]


# ---------------------------------------------------------------------------
# Malformed and absent codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("garbage", ["N/A", "n/a", "TBC", "", "   ", "-", "7304", "73041", "7.3.0"])
def test_malformed_code_warns_and_is_not_compared(garbage: str) -> None:
    r = check_hs_consistency(invoice(garbage), packing("73041900"))

    assert r.severity == "WARN"
    if garbage.strip():
        assert f"malformed HS code '{garbage}'" in r.message


def test_a_malformed_code_next_to_a_valid_matching_one_still_warns() -> None:
    """The valid codes agree, but one code was not read: that must not be reported as a clean PASS."""
    r = check_hs_consistency(invoice("73041900", "N/A"), packing("73041900"))
    assert r.severity == "WARN"
    assert "malformed HS code 'N/A'" in r.message


def test_valid_codes_that_differ_stay_material_even_if_another_code_is_malformed() -> None:
    r = check_hs_consistency(invoice("73041900", "N/A"), packing("73043100"))
    assert r.severity == "MATERIAL"
    assert "malformed HS code 'N/A'" in r.message


def test_no_codes_at_all_on_one_side_warns() -> None:
    r = check_hs_consistency(ExtractedDocument(document_id="inv", doc_type="COMMERCIAL_INVOICE", doc_type_confidence=0.9),
                             packing("73041900"))
    assert r.severity == "WARN"
    assert "absent" in r.message


def test_only_malformed_codes_on_one_side_warns_and_names_them() -> None:
    r = check_hs_consistency(invoice("N/A"), packing("73041900"))
    assert r.severity == "WARN"
    assert "malformed HS code 'N/A'" in r.message


def test_a_declared_code_with_no_value_is_ignored() -> None:
    inv = invoice("73041900")
    inv.line_items.append(
        LineItem(description=ref("x"), quantity=ref("1"), net_weight_kg=ref(1.0), gross_weight_kg=ref(1.0),
                 hs_code_declared=FieldRef(value=None, confidence=0.0))
    )
    r = check_hs_consistency(inv, packing("73041900"))
    assert r.severity == "PASS"


# ---------------------------------------------------------------------------
# A3: a 7-digit code probably lost a leading zero
# ---------------------------------------------------------------------------


def test_seven_digit_code_message_says_a_leading_zero_may_have_been_dropped() -> None:
    r = check_hs_consistency(invoice("7304190"), packing("73041900"))
    assert r.severity == "WARN"
    assert "7304190" in r.message
    assert "a leading zero may have been dropped" in r.message


def test_a_dropped_leading_zero_on_chapters_01_to_09_is_explained_in_the_contradiction_message() -> None:
    """A model that emits 01012100 as a number yields 1012100; the false MATERIAL must say why."""
    r = check_hs_consistency(invoice(1012100), packing("01012100"))
    assert r.severity == "MATERIAL"
    assert "a leading zero may have been dropped" in r.message


@pytest.mark.parametrize("code", ["73041900", "730419", "7304190000"])
def test_other_lengths_do_not_get_the_leading_zero_hint(code: str) -> None:
    r = check_hs_consistency(invoice(code), packing("73041900"))
    assert "leading zero" not in r.message


# ---------------------------------------------------------------------------
# C7: H-002 evidence points at the HS fields (page + bbox, line item index)
# ---------------------------------------------------------------------------

BBOX = {"page": 1, "ymin": 0.0, "xmin": 0.0, "ymax": 10.0, "xmax": 10.0}


def test_evidence_has_one_entry_per_declared_code_with_page_bbox_and_line_item() -> None:
    r = check_hs_consistency(invoice("7304.19.00", "73063000"), packing("73041900", "73063000"))

    assert r.severity == "PASS"
    assert r.evidence == [
        {"doc": "inv-001", "field": "hs_code_declared", "line_item": 0, "page": 1, "bbox": BBOX, "raw_value": "7304.19.00"},
        {"doc": "inv-001", "field": "hs_code_declared", "line_item": 1, "page": 1, "bbox": BBOX, "raw_value": "73063000"},
        {"doc": "pl-001", "field": "hs_code_declared", "line_item": 0, "page": 1, "bbox": BBOX, "raw_value": "73041900"},
        {"doc": "pl-001", "field": "hs_code_declared", "line_item": 1, "page": 1, "bbox": BBOX, "raw_value": "73063000"},
    ]


def test_header_code_evidence_has_no_line_item() -> None:
    r = check_hs_consistency(invoice(header="7304.19.00"), packing("73041900"))
    header_entries = [e for e in r.evidence if e["field"] == "hs_code_header"]
    assert header_entries == [
        {"doc": "inv-001", "field": "hs_code_header", "page": 1, "bbox": BBOX, "raw_value": "7304.19.00"}
    ]


def test_evidence_without_a_bbox_has_neither_page_nor_bbox() -> None:
    inv = ExtractedDocument(
        document_id="inv-001", doc_type="COMMERCIAL_INVOICE", doc_type_confidence=0.9,
        line_items=[LineItem(description=ref("x"), quantity=ref("1"), net_weight_kg=ref(1.0), gross_weight_kg=ref(1.0),
                             hs_code_declared=FieldRef(value="73041900", confidence=0.9))],
    )
    r = check_hs_consistency(inv, packing("73041900"))
    entry = r.evidence[0]
    assert entry == {"doc": "inv-001", "field": "hs_code_declared", "line_item": 0, "raw_value": "73041900"}


def test_a_document_with_no_codes_still_gets_a_placeholder_entry() -> None:
    bare = ExtractedDocument(document_id="inv-001", doc_type="COMMERCIAL_INVOICE", doc_type_confidence=0.9)
    r = check_hs_consistency(bare, packing("73041900"))
    assert {"doc": "inv-001", "field": "hs_code_declared"} in r.evidence
