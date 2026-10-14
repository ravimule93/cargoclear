"""The correction overlay (domain/corrections.py): addresses, validation, the history -> overlay rule, and how it lies on an extraction.

Pure functions, so these tests build documents as plain dicts, exactly the shape the stored extraction has.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.domain import corrections as c
from app.domain.schemas import CorrectionRecord, ExtractedDocument, FieldRef, LineItem

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def ref(value: Any, confidence: float = 0.9, unit: str | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "confidence": confidence, "bbox": {"page": 1, "ymin": 1, "xmin": 1, "ymax": 2, "xmax": 2}}
    if unit is not None:
        out["unit"] = unit
    out.update(extra)
    return out


def lab(heat: str, parameter: str, value: str, unit: str = "%") -> dict[str, Any]:
    return {**ref(value, unit=unit), "parameter": parameter, "heat_number": heat}


def certificate() -> dict[str, Any]:
    return {
        "document_id": "mtc-1",
        "doc_type": "MILL_TEST_CERTIFICATE",
        "doc_type_confidence": 0.8,
        "specification": ref("ASTM A106 GR B"),
        "heat_numbers": [ref("H1"), ref("H2")],
        "test_results": [lab("H1", "C", "0.18"), lab("H1", "Cr", "0.10"), lab("H2", "C", "0.20"), lab("H2", "Cr", "0.35")],
        "line_items": [],
    }


def line(description: str, quantity: str, total: str) -> dict[str, Any]:
    return {
        "description": ref(description), "quantity": ref(quantity), "hs_code_declared": ref("73043100"), "total_value": ref(total),
        "net_weight_kg": ref(None, 0.5, unit="KGS"), "gross_weight_kg": ref(None, 0.5, unit="KGS"),
    }


def invoice() -> dict[str, Any]:
    return {
        "document_id": "inv-1",
        "doc_type": "COMMERCIAL_INVOICE",
        "doc_type_confidence": 0.99,
        "consignee": ref("ACME PTE LTD"),
        "total_gross_weight_kg": ref("14,280.50", unit="KGS"),
        "invoice_currency": ref("USD"),
        "line_items": [line("SEAMLESS PIPE 6 INCH", "100", "1000"), line("SEAMLESS PIPE 8 INCH", "50", "900")],
    }


def record(seq: int, path: str, value: str | None, *, document_id: str = "inv-1", kind: str = "correction", unit: str | None = None,
           anchor: str | None = None, reverts: str | None = None, original_value: str | None = None) -> CorrectionRecord:
    return CorrectionRecord(
        correction_id=f"cor-{seq}", kind=kind, seq=seq, created_at=f"2026-10-14T00:00:{seq:02d}+00:00", iteration=1,  # type: ignore[arg-type]
        document_id=document_id, path=path, anchor=anchor, value=value, unit=unit, reverts=reverts, original_value=original_value,
    )


# ---------------------------------------------------------------------------
# addresses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "scope", "field", "index", "kind"),
    [
        ("consignee", "header", "consignee", None, "text"),
        ("total_gross_weight_kg", "header", "total_gross_weight_kg", None, "weight"),
        ("line_items[2].hs_code_declared", "line", "hs_code_declared", 2, "hs"),
        ("heat_numbers[0]", "row", "heat_numbers", 0, "heat"),
        ("test_results[13]", "row", "test_results", 13, "lab"),
        ("doc_type", "doc_type", "doc_type", None, "doc_type"),
    ],
)
def test_a_path_names_exactly_one_address(path: str, scope: str, field: str, index: int | None, kind: str) -> None:
    address = c.parse_path(path)
    assert (address.scope, address.field, address.index, address.kind) == (scope, field, index, kind)
    assert address.path == path, "the canonical path round-trips"


@pytest.mark.parametrize(
    "path",
    ["", "bogus", "line_items", "line_items[0]", "line_items[0].bogus", "line_items[x].description", "heat_numbers", "test_results[-1]",
     "consignee.value", "../consignee", "line_items[99999].description", "doc_type_confidence", "document_id", "line_items[0].description "],
)
def test_a_path_outside_the_grammar_is_refused(path: str) -> None:
    if path == "line_items[0].description ":  # surrounding whitespace is tolerated, nothing else about the grammar is
        assert c.parse_path(path).path == "line_items[0].description"
        return
    with pytest.raises(c.CorrectionError):
        c.parse_path(path)


def test_every_extracted_field_is_either_correctable_or_deliberately_not() -> None:
    """A field added to the schema must be a decision here, never an accident: it is correctable (a table entry) or listed as not."""
    not_correctable_header = {"document_id", "doc_type", "doc_type_confidence", "line_items", "heat_numbers", "test_results"}
    for name, field in ExtractedDocument.model_fields.items():
        if name in not_correctable_header:
            continue
        assert name in c.HEADER_FIELDS, f"ExtractedDocument.{name} is neither correctable nor listed as not"
        assert field is not None
    for name in LineItem.model_fields:
        assert name in c.LINE_FIELDS, f"LineItem.{name} is neither correctable nor listed as not"
    assert set(c.HEADER_FIELDS) <= set(ExtractedDocument.model_fields)
    assert set(c.LINE_FIELDS) <= set(LineItem.model_fields)
    assert FieldRef  # the tables only name FieldRef-typed fields (the apply step builds {value, confidence, bbox} for them)


# ---------------------------------------------------------------------------
# validation: a value the engines could not read without guessing is refused
# ---------------------------------------------------------------------------


def v(path: str, value: str, unit: str | None = None, **kw: Any) -> tuple[str, str | None]:
    return c.validate_value(c.parse_path(path), value, unit, **kw)


def test_text_is_cleaned_and_never_empty_or_cut() -> None:
    assert v("consignee", "  ACME \t PTE\n LTD ")[0] == "ACME PTE LTD"
    with pytest.raises(c.CorrectionError, match="empty"):
        v("consignee", "   ")
    with pytest.raises(c.CorrectionError, match="longer than 200"):
        v("consignee", "x" * 201)
    assert len(v("line_items[0].description", "x" * 500)[0]) == 500
    with pytest.raises(c.CorrectionError, match="longer than 500"):
        v("line_items[0].description", "x" * 501)


def test_currency_hs_and_doc_type() -> None:
    assert v("invoice_currency", "usd")[0] == "USD"
    for bad in ("US", "DOLLARS", "U5D", "12"):
        with pytest.raises(c.CorrectionError, match="3-letter"):
            v("invoice_currency", bad)
    assert v("hs_code_header", "7304.19.00")[0] == "7304.19.00"
    for bad in ("73", "abcdef", "7304 19 00 00 00", "7304.x"):
        with pytest.raises(c.CorrectionError, match="HS code"):
            v("hs_code_header", bad)
    assert v("doc_type", "PACKING_LIST")[0] == "PACKING_LIST"
    for bad in ("UNKNOWN", "packing list", "INVOICE"):
        with pytest.raises(c.CorrectionError, match="Document type"):
            v("doc_type", bad)


def test_numbers_must_be_unambiguous() -> None:
    assert v("invoice_value", "12,500.50")[0] == "12,500.50"
    assert v("package_count", "12")[0] == "12"
    with pytest.raises(c.CorrectionError, match="not a number"):
        v("invoice_value", "twelve")
    with pytest.raises(c.CorrectionError, match="ambiguous"):
        v("invoice_value", "14,280")
    with pytest.raises(c.CorrectionError, match="whole number"):
        v("package_count", "12.5")
    with pytest.raises(c.CorrectionError, match="not a number"):
        v("line_items[0].total_value", "-5")


def test_a_weight_needs_a_unit_the_engines_know() -> None:
    assert v("total_gross_weight_kg", "14280.5", "KGS") == ("14280.5", "KGS")
    assert v("total_gross_weight_kg", "14.2805", "MT")[1] == "MT"
    assert v("total_gross_weight_kg", "14280.5 KGS") == ("14280.5 KGS", None), "a unit typed into the value counts, and is not duplicated"
    assert v("total_gross_weight_kg", "14280.5", existing_unit="KGS") == ("14280.5", None), "the unit already on the field is kept"
    with pytest.raises(c.CorrectionError, match="State the unit"):
        v("total_gross_weight_kg", "14280.5")
    with pytest.raises(c.CorrectionError, match="Unrecognised unit"):
        v("total_gross_weight_kg", "14280.5", "SACKS")
    with pytest.raises(c.CorrectionError, match="State the unit once"):
        v("total_gross_weight_kg", "14 MT", "KGS")
    assert v("total_gross_weight_kg", "14 MT", "metric tons")[0] == "14 MT", "the same unit written twice agrees"


def test_a_lab_value_is_a_number_a_bound_or_not_detected() -> None:
    for good in ("0.18", "<0.005", "ND", "0,18", "350"):
        assert v("test_results[0]", good)[0] == good
    assert v("test_results[0]", "350", "MPa") == ("350", "MPa")
    with pytest.raises(c.CorrectionError, match="Use a number"):
        v("test_results[0]", "abc")
    with pytest.raises(c.CorrectionError, match="characters a unit"):
        v("test_results[0]", "350", "MPa; DROP")


# ---------------------------------------------------------------------------
# history -> overlay
# ---------------------------------------------------------------------------


def event(seq: int, event_type: str, **payload: Any) -> dict[str, Any]:
    return {"seq": seq, "ts": "2026-10-14T00:00:00+00:00", "iteration": 1, "actor": "user", "event_type": event_type,
            "payload": {"document_id": "inv-1", **payload}}


def test_the_history_is_read_from_audit_events_and_other_events_are_ignored() -> None:
    events = [
        {"seq": 1, "event_type": "BUNDLE_CREATED", "payload": {}},
        event(2, c.EVENT_CORRECTED, path="consignee", value="ACME", original_value="ACM3"),
        event(3, c.EVENT_CONFIRMED, path="invoice_currency", value="USD"),
        event(4, c.EVENT_REVERTED, path="consignee", reverts="cor-2"),
        {"seq": 5, "event_type": c.EVENT_CORRECTED, "ts": "t", "payload": {"value": "no document, no path"}},
        {"event_type": c.EVENT_CORRECTED, "payload": {}},
        {"seq": 7, "event_type": "ASSESSMENT_COMPLETED", "payload": {}},
    ]
    records = c.parse_events(events)
    assert [(r.correction_id, r.kind) for r in records] == [("cor-2", "correction"), ("cor-3", "confirmation"), ("cor-4", "revert")]
    assert records[0].original_value == "ACM3" and records[2].reverts == "cor-2"


def test_the_newest_entry_per_address_is_in_force_and_an_undo_brings_back_the_one_before() -> None:
    a, b = record(1, "consignee", "A"), record(2, "consignee", "B")
    other = record(3, "invoice_currency", "USD")
    assert [r.correction_id for r in c.effective([a, b, other])] == ["cor-2", "cor-3"]

    undo_newest = record(4, "consignee", None, kind="revert", reverts="cor-2")
    assert [r.correction_id for r in c.effective([a, b, other, undo_newest])] == ["cor-1", "cor-3"]

    undo_both = [*[a, b, other, undo_newest], record(5, "consignee", None, kind="revert", reverts="cor-1")]
    assert [r.correction_id for r in c.effective(undo_both)] == ["cor-3"], "back to what the model read"

    undo_older_only = [a, b, record(4, "consignee", None, kind="revert", reverts="cor-1")]
    assert [r.correction_id for r in c.effective(undo_older_only)] == ["cor-2"], "undoing an entry that is not the newest changes nothing in force"

    assert c.effective([]) == []


# ---------------------------------------------------------------------------
# applying the overlay
# ---------------------------------------------------------------------------


def test_apply_never_changes_what_the_model_read() -> None:
    raw = [invoice(), certificate()]
    before = copy.deepcopy(raw)
    result = c.apply(raw, [record(1, "consignee", "ACME LTD"), record(2, "test_results[3]", "0.28", document_id="mtc-1", anchor="H2|Cr")])
    assert raw == before
    assert result.docs is not raw and result.docs[0] is not raw[0]


def test_a_corrected_header_value_has_full_confidence_keeps_its_box_and_remembers_the_original() -> None:
    result = c.apply([invoice()], [record(1, "consignee", "ACME LTD")])
    consignee = result.docs[0]["consignee"]
    assert consignee["value"] == "ACME LTD" and consignee["confidence"] == 1.0
    assert consignee["bbox"] == invoice()["consignee"]["bbox"], "the box of the printed value is kept: the viewer still points there"
    assert consignee["corrected"] is True and consignee["original_value"] == "ACME PTE LTD"
    assert [(o.correction_id, o.status, o.note) for o in result.outcomes] == [("cor-1", "applied", None)]


def test_a_weight_correction_keeps_its_unit_unless_a_new_one_is_given() -> None:
    kept = c.apply([invoice()], [record(1, "total_gross_weight_kg", "14,300.00")]).docs[0]["total_gross_weight_kg"]
    assert (kept["value"], kept["unit"], kept["original_unit"]) == ("14,300.00", "KGS", "KGS")
    changed = c.apply([invoice()], [record(1, "total_gross_weight_kg", "14.3", unit="MT")]).docs[0]["total_gross_weight_kg"]
    assert (changed["value"], changed["unit"], changed["original_unit"]) == ("14.3", "MT", "KGS")


def test_a_field_the_model_left_empty_can_be_filled_and_one_it_invented_can_be_cleared() -> None:
    filled = c.apply([invoice()], [record(1, "incoterm", "FOB TIANJIN")]).docs[0]["incoterm"]
    assert filled["value"] == "FOB TIANJIN" and filled["confidence"] == 1.0 and filled["bbox"] is None and filled["original_value"] is None

    cleared = c.apply([invoice()], [record(1, "consignee", None)]).docs[0]["consignee"]
    assert cleared["value"] is None and cleared["corrected"] is True and cleared["original_value"] == "ACME PTE LTD"

    filled_weight = c.apply([invoice()], [record(1, "tare_weight_kg", "280", unit="KGS")]).docs[0]["tare_weight_kg"]
    assert (filled_weight["value"], filled_weight["unit"]) == ("280", "KGS")


def test_the_corrected_extraction_is_still_a_valid_extraction_and_the_markers_are_ignored() -> None:
    result = c.apply([invoice(), certificate()], [record(1, "consignee", "ACME LTD"), record(2, "doc_type", "PACKING_LIST", document_id="mtc-1")])
    docs = [ExtractedDocument.model_validate(d) for d in result.docs]
    assert docs[0].consignee is not None and docs[0].consignee.value == "ACME LTD" and docs[0].consignee.confidence == 1.0
    assert docs[1].doc_type == "PACKING_LIST" and docs[1].doc_type_confidence == 1.0
    assert result.docs[1]["doc_type_original"] == "MILL_TEST_CERTIFICATE" and result.docs[1]["doc_type_corrected"] is True


def test_a_line_item_correction_finds_its_line() -> None:
    result = c.apply([invoice()], [record(1, "line_items[1].total_value", "950", anchor="seamless pipe 8 inch")])
    lines = result.docs[0]["line_items"]
    assert lines[0]["total_value"]["value"] == "1000" and "corrected" not in lines[0]["total_value"]
    assert lines[1]["total_value"]["value"] == "950" and lines[1]["total_value"]["original_value"] == "900"


def test_a_certificate_cell_is_found_again_when_the_table_is_read_in_another_order() -> None:
    """The correction was made for heat H2's chromium (row 3). If the next extraction lists the rows differently, it must land on the SAME cell."""
    reordered = certificate()
    reordered["test_results"] = list(reversed(reordered["test_results"]))  # H2/Cr is now row 0
    result = c.apply([reordered], [record(1, "test_results[3]", "0.28", document_id="mtc-1", anchor="H2|Cr")])
    rows = result.docs[0]["test_results"]
    assert [(r["heat_number"], r["parameter"], r["value"]) for r in rows] == [
        ("H2", "Cr", "0.28"), ("H2", "C", "0.20"), ("H1", "Cr", "0.10"), ("H1", "C", "0.18")
    ]
    assert result.outcomes[0].status == "applied"
    # ...and the heat anchor is the same whatever the heat is printed like, and the parameter whatever it is spelt
    spelt = certificate()
    spelt["test_results"][3] = lab("h-2", "Chromium", "0.35")
    assert c.apply([spelt], [record(1, "test_results[3]", "0.28", document_id="mtc-1", anchor="H2|Cr")]).outcomes[0].status == "applied"


def test_a_correction_is_skipped_rather_than_applied_to_a_row_it_was_not_made_for() -> None:
    different = certificate()
    different["test_results"] = [lab("H9", "C", "0.10")]  # the table now has nothing like H2/Cr
    result = c.apply([different], [record(1, "test_results[3]", "0.28", document_id="mtc-1", anchor="H2|Cr")])
    assert result.docs[0]["test_results"] == different["test_results"], "nothing changed"
    assert result.outcomes[0].status == "skipped" and "no longer in the extraction" in (result.outcomes[0].note or "")

    ambiguous = certificate()
    ambiguous["test_results"] = [lab("H2", "Cr", "0.35"), lab("H2", "Cr", "0.36")]  # two cells claim to be H2/Cr, neither at index 3
    assert c.apply([ambiguous], [record(1, "test_results[3]", "0.28", document_id="mtc-1", anchor="H2|Cr")]).outcomes[0].status == "skipped"


def test_a_correction_for_a_document_or_field_that_is_gone_is_skipped_with_the_reason() -> None:
    result = c.apply(
        [invoice()],
        [record(1, "consignee", "X", document_id="not-here"), record(2, "bogus_field", "X")],
    )
    assert [o.status for o in result.outcomes] == ["skipped", "skipped"]
    assert "not part of this analysis" in (result.outcomes[0].note or "")
    assert "not a field" in (result.outcomes[1].note or "")


def test_later_corrections_to_one_row_still_find_it_after_an_earlier_one_changed_the_row_s_anchor_field() -> None:
    """Rows are found against what the model read, so correcting a line's description does not orphan a correction of its price."""
    result = c.apply(
        [invoice()],
        [
            record(1, "line_items[0].description", "SEAMLESS PIPE 6 IN", anchor="seamless pipe 6 inch"),
            record(2, "line_items[0].total_value", "1100", anchor="seamless pipe 6 inch"),
        ],
    )
    line = result.docs[0]["line_items"][0]
    assert line["description"]["value"] == "SEAMLESS PIPE 6 IN" and line["total_value"]["value"] == "1100"
    assert [o.status for o in result.outcomes] == ["applied", "applied"]


def test_the_applied_entry_carries_what_the_iteration_stores() -> None:
    outcome = c.apply([invoice()], [record(7, "consignee", "ACME LTD", original_value="ACME PTE LTD")]).outcomes[0].model_dump()
    assert outcome["correction_id"] == "cor-7" and outcome["seq"] == 7 and outcome["path"] == "consignee"
    assert outcome["value"] == "ACME LTD" and outcome["original_value"] == "ACME PTE LTD" and outcome["status"] == "applied"


# ---------------------------------------------------------------------------
# reading values back
# ---------------------------------------------------------------------------


def test_read_value_reports_value_and_unit_or_nothing_where_there_is_no_such_address() -> None:
    doc = invoice()
    assert c.read_value(doc, c.parse_path("consignee")) == ("ACME PTE LTD", None)
    assert c.read_value(doc, c.parse_path("total_gross_weight_kg")) == ("14,280.50", "KGS")
    assert c.read_value(doc, c.parse_path("incoterm")) == (None, None), "an empty field is an address with no value"
    assert c.read_value(doc, c.parse_path("line_items[1].quantity")) == ("50", None)
    assert c.read_value(doc, c.parse_path("line_items[5].quantity")) is None, "there is no sixth line"
    assert c.read_value(certificate(), c.parse_path("test_results[3]")) == ("0.35", "%")
    assert c.read_value(certificate(), c.parse_path("heat_numbers[1]")) == ("H2", None)
    assert c.read_value(certificate(), c.parse_path("heat_numbers[2]")) is None
    assert c.read_value(doc, c.parse_path("doc_type")) == ("COMMERCIAL_INVOICE", None)
    assert c.read_value({"total_gross_weight_kg": {"value": 14000.0, "unit": "KGS", "confidence": 1}}, c.parse_path("total_gross_weight_kg")) == ("14000", "KGS")


# --- the words a person sees for an address: one table of vectors, tested here and in the frontend -----------------------------


def test_every_address_label_matches_the_shared_vectors() -> None:
    import json

    from app.domain.corrections import path_label
    from tests.helpers import REPO_ROOT

    vectors = json.loads((REPO_ROOT / "docs" / "schemas" / "path-labels.json").read_text(encoding="utf-8"))["vectors"]
    assert len(vectors) >= 8
    for vector in vectors:
        assert path_label(vector["path"]) == vector["label"], vector


def test_the_narrative_uses_the_same_label_as_the_card_with_a_lower_case_first_letter() -> None:
    from app.services.reasoning import _where

    docs = [{"document_id": "d1", "filename": "mtc.pdf"}]
    assert _where("line_items[0].hs_code_declared", "d1", docs) == "line 1 · Hs code declared of mtc.pdf"
    assert _where("test_results[20]", "d1", docs) == "certificate cell 21 of mtc.pdf"
    assert _where("test_results[20]", "gone", docs) == "certificate cell 21"
