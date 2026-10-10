"""Case C fixtures state their weight units (G1): every weight is a QuantityRef printed in "KGS".

`fixture_values_snapshot.json` is the fixture content as it was BEFORE units were added: every other value,
confidence and bbox must be unchanged, so the only difference is the unit on the weights.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.extraction import _generate_fixture_for_file
from app.domain.schemas import ExtractedDocument, FieldRef, LineItem, QuantityRef, TextRef

SNAPSHOT = json.loads((Path(__file__).parent / "fixture_values_snapshot.json").read_text(encoding="utf-8"))
HERO_FILES = ["commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf", "mtc_pipe_test_cert.pdf"]
WEIGHT_NAMES = {"total_net_weight_kg", "total_gross_weight_kg", "tare_weight_kg", "net_weight_kg", "gross_weight_kg"}


def fields_of(doc: ExtractedDocument) -> dict[str, FieldRef]:
    out: dict[str, FieldRef] = {}
    for name in ExtractedDocument.model_fields:
        value = getattr(doc, name)
        if isinstance(value, FieldRef):
            out[name] = value
    for i, item in enumerate(doc.line_items):
        for name in LineItem.model_fields:
            value = getattr(item, name)
            if isinstance(value, FieldRef):
                out[f"line_items[{i}].{name}"] = value
    return out


def is_weight(path: str) -> bool:
    return path.split(".")[-1] in WEIGHT_NAMES


@pytest.mark.parametrize("filename", HERO_FILES)
def test_every_weight_is_a_quantity_ref_in_kgs(filename: str) -> None:
    fields = fields_of(_generate_fixture_for_file("doc-x", filename))
    weights = {path: ref for path, ref in fields.items() if is_weight(path)}
    assert weights, f"{filename}: no weight fields found"
    for path, ref in weights.items():
        assert type(ref) is QuantityRef, f"{filename}:{path} is {type(ref).__name__}"
        assert ref.unit == "KGS", f"{filename}:{path} unit={ref.unit!r}"


NUMERIC_NAMES = {"invoice_value", "package_count", "unit_price", "total_value"}


@pytest.mark.parametrize("filename", HERO_FILES)
def test_non_weight_fields_are_text_refs_or_numeric_field_refs_never_quantity_refs(filename: str) -> None:
    for path, ref in fields_of(_generate_fixture_for_file("doc-x", filename)).items():
        if is_weight(path):
            continue
        expected = FieldRef if path.split(".")[-1] in NUMERIC_NAMES else TextRef
        assert type(ref) is expected, f"{filename}:{path} is {type(ref).__name__}, expected {expected.__name__}"


@pytest.mark.parametrize("filename", HERO_FILES)
def test_nothing_but_the_units_changed(filename: str) -> None:
    """Same doc_type and, for every field, the same value, confidence and bbox as before the unit layer."""
    doc = _generate_fixture_for_file("doc-x", filename)
    expected = SNAPSHOT[filename]
    assert doc.doc_type == expected["doc_type"]

    actual = {
        path: [
            ref.value,
            ref.confidence,
            [ref.bbox.page, ref.bbox.ymin, ref.bbox.xmin, ref.bbox.ymax, ref.bbox.xmax] if ref.bbox else None,
        ]
        for path, ref in fields_of(doc).items()
    }
    assert actual == expected["fields"]


def test_the_packing_list_declares_net_tare_and_gross_so_w002_applies() -> None:
    pl = _generate_fixture_for_file("doc-x", "packing_list.pdf")
    assert pl.total_net_weight_kg is not None and pl.total_net_weight_kg.value == 14000.0
    assert pl.tare_weight_kg is not None and pl.tare_weight_kg.value == 280.0
    assert pl.total_gross_weight_kg is not None and pl.total_gross_weight_kg.value == 14280.0
