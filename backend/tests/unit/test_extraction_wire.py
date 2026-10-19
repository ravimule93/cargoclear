"""agents/extraction_wire.py: the shape of the model's answer, and how it becomes an ExtractedDocument.

Gemini refuses a response schema that is too large for its constrained decoding ("too many states"), and the nested ExtractedDocument
was one. The answer is therefore lists of entries with the field name as an enum. What is pinned here: the field lists follow the
document model, a faithful answer rebuilds every fixture document exactly, a sloppy answer loses only what has no place, and the
extraction path accepts both the new shape and a document-shaped answer. Nothing here touches a model or the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agents import extraction, extraction_wire as wire
from app.core.config import settings
from app.domain.schemas import ExtractedDocument, LineItem
from tests.helpers import REPO_ROOT
from tests.unit.extraction_fakes import FakeGenai, always, ctx_for, response

_BASE_DIR = (REPO_ROOT / "samples") if (REPO_ROOT / "samples" / "case_c").is_dir() else (REPO_ROOT / "fixtures")
FIXTURES = sorted(
    path for case in ("case_c", "case_d") for path in (_BASE_DIR / case).glob("*.pdf")
)


def fixture_document(path: Path) -> ExtractedDocument:
    return extraction._generate_fixture_for_file(f"doc-{path.stem}", path.name)


def as_text(node: Any) -> Any:
    """The document dict with every value as text: the wire carries text, a fixture may hold a number."""
    if isinstance(node, dict):
        if "value" in node and "confidence" in node and node["value"] is not None:
            node = {**node, "value": str(node["value"])}
        return {key: as_text(child) for key, child in node.items()}
    if isinstance(node, list):
        return [as_text(child) for child in node]
    return node


def cell(name: str, value: str | None = "x", **extra: Any) -> dict[str, Any]:
    return {"name": name, "value": value, "unit": None, "confidence": 0.9, "page": 1, "box": [10, 20, 30, 40], **extra}


def answer(**parts: Any) -> dict[str, Any]:
    base = {"doc_type": "COMMERCIAL_INVOICE", "doc_type_confidence": 0.9, "fields": [], "heat_numbers": [], "line_cells": [],
            "test_results": []}
    return {**base, **parts}


def line(row: int, name: str, value: str | None = "x", **extra: Any) -> dict[str, Any]:
    return {"row": row, **cell(name, value, **extra)}


# ---------------------------------------------------------------------------
# which fields exist: derived from the document model
# ---------------------------------------------------------------------------


def test_every_scalar_reference_field_of_the_document_model_is_a_wire_name() -> None:
    """Derived a second way (by the text of each annotation) so a change to how the module derives the names is caught."""

    def names(model: type, *, lists: bool) -> set[str]:
        return {
            n for n, f in model.model_fields.items()
            if (str(f.annotation).startswith("list[") == lists)
            and any(k in str(f.annotation) for k in ("FieldRef", "QuantityRef", "TextRef", "TextField", "WeightRef", "LabResult"))
        }

    assert set(wire.HEADER_FIELDS) == names(ExtractedDocument, lists=False)
    assert set(wire.LINE_FIELDS) == names(LineItem, lists=False)
    assert {"heat_numbers", "test_results"} == names(ExtractedDocument, lists=True)  # lists have their own entry shape
    assert "document_id" not in wire.HEADER_FIELDS


def test_weights_are_quantities_amounts_are_numbers_and_the_rest_is_text() -> None:
    quantities = {n for n, k in wire.HEADER_FIELDS.items() if k == "quantity"}
    assert quantities == {"total_net_weight_kg", "total_gross_weight_kg", "tare_weight_kg"}
    assert {n for n, k in wire.LINE_FIELDS.items() if k == "quantity"} == {"net_weight_kg", "gross_weight_kg"}
    assert {n for n, k in wire.HEADER_FIELDS.items() if k == "number"} == {
        "invoice_value", "package_count", "freight_amount", "insurance_amount",
    }
    assert wire.HEADER_FIELDS["consignee"] == "text" and wire.LINE_FIELDS["hs_code_declared"] == "text"


def test_the_required_line_fields_are_the_ones_a_line_item_cannot_do_without() -> None:
    assert set(wire.REQUIRED_LINE_FIELDS) == {"description", "quantity", "net_weight_kg", "gross_weight_kg", "hs_code_declared"}


# ---------------------------------------------------------------------------
# a faithful answer rebuilds every fixture document exactly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", FIXTURES, ids=[p.name for p in FIXTURES])
def test_a_faithful_answer_rebuilds_the_document_it_was_made_from(path: Path) -> None:
    original = fixture_document(path)
    faithful = wire.document_to_answer(original)

    wire.Answer.model_validate(faithful)  # it satisfies the schema the model is given
    rebuilt, warnings = wire.answer_to_document(faithful, page_count=1)
    rebuilt["document_id"] = original.document_id

    assert warnings == []
    assert as_text(ExtractedDocument.model_validate(rebuilt).model_dump(mode="json")) == as_text(original.model_dump(mode="json"))


def test_the_certificate_table_comes_back_row_for_row() -> None:
    original = fixture_document(_BASE_DIR / "case_d" / "case_d_mtc_test_cert.pdf")
    rebuilt, _ = wire.answer_to_document(wire.document_to_answer(original), page_count=1)

    assert len(rebuilt["test_results"]) == len(original.test_results) == 30
    first = rebuilt["test_results"][0]
    assert (first["heat_number"], first["parameter"], first["value"], first["unit"]) == (
        original.test_results[0].heat_number, original.test_results[0].parameter,
        original.test_results[0].value, original.test_results[0].unit,
    )
    assert [r["value"] for r in rebuilt["heat_numbers"]] == [h.value for h in original.heat_numbers]


# ---------------------------------------------------------------------------
# a sloppy answer loses only what has no place
# ---------------------------------------------------------------------------


def test_an_unknown_name_and_a_second_value_are_dropped_with_a_warning_that_names_no_value() -> None:
    raw = answer(fields=[
        cell("consignee", "FIRST LTD"), cell("consignee", "SECOND LTD"), cell("shoe_size", "SECRET-DOCUMENT-TEXT"),
        {"name": None, "value": "v", "unit": None, "confidence": 0.5, "page": 1, "box": None}, "not an object",
    ])

    out, warnings = wire.answer_to_document(raw, page_count=1)

    assert out["consignee"]["value"] == "FIRST LTD" and "shoe_size" not in out
    assert sorted(w["path"] for w in warnings) == ["fields[1]", "fields[2]", "fields[3]", "fields[4]"]
    assert "SECRET-DOCUMENT-TEXT" not in json.dumps(warnings) and "SECOND LTD" not in json.dumps(warnings)


def test_a_unit_is_kept_for_a_weight_and_ignored_for_text() -> None:
    raw = answer(fields=[cell("total_gross_weight_kg", "25,400.00", unit="KGS"), cell("consignee", "A LTD", unit="KGS")])

    out, _ = wire.answer_to_document(raw, page_count=1)

    assert out["total_gross_weight_kg"]["unit"] == "KGS" and "unit" not in out["consignee"]


def test_line_cells_are_grouped_by_row_in_the_documents_own_order() -> None:
    raw = answer(line_cells=[  # column by column, rows out of order: the row number decides, not the position
        line(2, "description", "SECOND"), line(1, "description", "FIRST"),
        line(2, "net_weight_kg", "5", unit="MT"), line(1, "net_weight_kg", "3", unit="MT"),
        line(1, "unit_price", "100"),
    ])

    out, warnings = wire.answer_to_document(raw, page_count=1)

    assert warnings == []
    assert [i["description"]["value"] for i in out["line_items"]] == ["FIRST", "SECOND"]
    assert out["line_items"][0]["net_weight_kg"] == {"value": "3", "confidence": 0.9, "bbox": {
        "page": 1, "ymin": 10, "xmin": 20, "ymax": 30, "xmax": 40}, "unit": "MT"}
    assert out["line_items"][0]["unit_price"]["value"] == "100" and "unit_price" not in out["line_items"][1]


def test_a_required_line_cell_the_model_left_out_is_rebuilt_as_not_printed() -> None:
    out, _ = wire.answer_to_document(answer(line_cells=[line(1, "description", "ONLY THIS")]), page_count=1)

    [item] = out["line_items"]
    for name in ("quantity", "net_weight_kg", "gross_weight_kg", "hs_code_declared"):
        assert item[name] == {"value": None, "confidence": 0.0, "bbox": None}
    ExtractedDocument.model_validate({**out, "document_id": "d"})  # and the document model accepts the line


def test_a_line_value_without_a_usable_row_or_name_is_dropped() -> None:
    raw = answer(line_cells=[
        line(1, "description", "KEPT"), {**line(1, "description", "SECOND"), "row": 1}, {**line(1, "quantity"), "row": "one"},
        {**line(1, "quantity"), "row": True}, line(3, "colour", "?"),
    ])

    out, warnings = wire.answer_to_document(raw, page_count=1)

    assert [w["path"] for w in warnings] == [f"line_cells[{i}]" for i in (1, 2, 3, 4)]
    assert len(out["line_items"]) == 1 and out["line_items"][0]["description"]["value"] == "KEPT"


def test_a_whole_number_row_sent_as_a_float_is_accepted() -> None:
    out, warnings = wire.answer_to_document(answer(line_cells=[{**line(1, "description", "A"), "row": 2.0}]), page_count=1)

    assert warnings == [] and len(out["line_items"]) == 1


def test_a_value_that_is_not_a_list_is_ignored_with_a_warning() -> None:
    out, warnings = wire.answer_to_document(answer(fields="oops", heat_numbers={"a": 1}), page_count=1)

    assert out["heat_numbers"] == [] and {w["path"] for w in warnings} == {"fields", "heat_numbers"}


# ---------------------------------------------------------------------------
# the box: [ymin, xmin, ymax, xmax] and a page become the bbox the system uses
# ---------------------------------------------------------------------------


def test_the_box_becomes_a_bbox_and_a_missing_page_is_the_page_when_one_page_was_sent() -> None:
    raw = answer(fields=[cell("consignee", page=None)])

    one, _ = wire.answer_to_document(raw, page_count=1)
    several, _ = wire.answer_to_document(raw, page_count=3)

    assert one["consignee"]["bbox"] == {"page": 1, "ymin": 10, "xmin": 20, "ymax": 30, "xmax": 40}
    assert several["consignee"]["bbox"]["page"] is None  # not in doubt only for one page: the sanitiser drops it


def test_a_malformed_box_is_dropped_by_the_sanitiser_with_a_reason() -> None:
    raw = answer(fields=[
        cell("consignee", box=[1, 2, 3]), cell("consignor", box="top left"), cell("incoterm", box=[500, 500, 100, 900]),
        cell("country_of_origin", page=None),
    ])
    out, converted = wire.answer_to_document(raw, page_count=2)

    clean, warnings = extraction._sanitise_extraction(out, 2)

    assert converted == []
    assert all(clean[name]["bbox"] is None for name in ("consignee", "consignor", "incoterm", "country_of_origin"))
    reasons = {w["path"]: w["reason"] for w in warnings}
    assert "missing or non-numeric" in reasons["consignee.bbox"]
    assert "not an object" in reasons["consignor.bbox"]
    assert "ymax <= ymin" in reasons["incoterm.bbox"]
    assert "page is not a whole number" in reasons["country_of_origin.bbox"]


def test_a_confidence_outside_zero_to_one_is_clamped_by_the_sanitiser_as_before() -> None:
    out, _ = wire.answer_to_document(answer(fields=[cell("consignee", confidence=1.4)]), page_count=1)

    clean, warnings = extraction._sanitise_extraction(out, 1)

    assert clean["consignee"]["confidence"] == 1.0 and warnings[0]["path"] == "consignee.confidence"


# ---------------------------------------------------------------------------
# which answers are in the wire shape
# ---------------------------------------------------------------------------


def test_only_an_answer_in_the_wire_shape_is_converted() -> None:
    assert wire.is_answer(answer()) and wire.is_answer({"doc_type": "UNKNOWN", "line_cells": []})
    document_shaped = fixture_document(FIXTURES[0]).model_dump(mode="json")
    assert not wire.is_answer(document_shaped) and not wire.is_answer([]) and not wire.is_answer("text")


# ---------------------------------------------------------------------------
# through the extraction path
# ---------------------------------------------------------------------------


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch):
    def install(fake: FakeGenai) -> FakeGenai:
        monkeypatch.setattr(settings, "app_mode", "live")
        monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
        return fake

    return install


@pytest.mark.asyncio
@pytest.mark.parametrize("path", FIXTURES, ids=[p.name for p in FIXTURES])
async def test_extraction_reads_a_wire_answer_into_the_expected_document(live, path: Path) -> None:
    original = fixture_document(path)
    fake = live(FakeGenai(always(response(wire.document_to_answer(original)))))

    result = await extraction.run_extraction_agent(ctx_for("doc-1"))

    [document] = result["extracted"]
    expected = original.model_copy(update={"document_id": "doc-1"})
    assert as_text(document.model_dump(mode="json")) == as_text(expected.model_dump(mode="json"))
    assert fake.calls[0]["config"].response_schema is wire.Answer
    assert result["extraction_warnings"] == []


@pytest.mark.asyncio
async def test_extraction_still_reads_a_document_shaped_answer(live) -> None:
    original = fixture_document(FIXTURES[0])
    live(FakeGenai(always(response(original.model_dump(mode="json")))))

    result = await extraction.run_extraction_agent(ctx_for("doc-1"))

    assert result["extracted"][0].doc_type == original.doc_type and result["extraction_warnings"] == []


@pytest.mark.asyncio
async def test_what_could_not_be_placed_reaches_the_run_as_a_warning(live) -> None:
    original = fixture_document(_BASE_DIR / "case_c" / "commercial_invoice.pdf")
    faithful = wire.document_to_answer(original)
    faithful["fields"].append(cell("shoe_size", "9"))
    live(FakeGenai(always(response(faithful))))

    result = await extraction.run_extraction_agent(ctx_for("doc-1"))

    [warning] = result["extraction_warnings"]
    assert warning["reason"] == "not a known header field; dropped" and warning["path"].startswith("fields[")


@pytest.mark.asyncio
async def test_a_wire_answer_the_document_model_rejects_is_retried_and_then_fails_like_any_other(live, monkeypatch) -> None:
    from app.gateway.errors import ExtractionError

    fake = live(FakeGenai(always(response(answer(doc_type="SHOE")))))

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(extraction, "_sleep", no_wait)

    with pytest.raises(ExtractionError):
        await extraction.run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == settings.gemini_max_attempts


@pytest.mark.asyncio
async def test_a_confidence_that_is_not_a_number_becomes_zero_with_a_warning_and_the_run_goes_on(live) -> None:
    live(FakeGenai(always(response(answer(fields=[cell("consignee", "X", confidence="high")])))))

    result = await extraction.run_extraction_agent(ctx_for("doc-1"))

    assert result["extracted"][0].consignee.confidence == 0.0
    assert any(w["path"] == "consignee.confidence" for w in result["extraction_warnings"])
