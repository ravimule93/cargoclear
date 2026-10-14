"""Layout guard for the offline extraction fixtures.

The Case C sample PDFs (scripts/generate_case_c_pdfs.py) are drawn from these
fixture bounding boxes, so every box has to be on the page and no two boxes on the
same page of the same document may overlap -- otherwise printed values collide.
"""

from __future__ import annotations

import itertools

import pytest

from app.agents.extraction import _generate_fixture_for_file
from app.domain.schemas import BBox, ExtractedDocument, FieldRef

CASE_C_FILENAMES = [
    "commercial_invoice.pdf",
    "bill_of_lading.pdf",
    "packing_list.pdf",
    "mtc_pipe_test_cert.pdf",
]
CASE_D_FILENAMES = [
    "case_d_commercial_invoice.pdf",
    "case_d_bill_of_lading.pdf",
    "case_d_packing_list.pdf",
    "case_d_mtc_test_cert.pdf",
]
HERO_FILENAMES = CASE_C_FILENAMES + CASE_D_FILENAMES


def collect_boxes(doc: ExtractedDocument) -> list[tuple[str, BBox]]:
    """Return (label, bbox) for every FieldRef with a bbox, header and line-item fields alike."""
    boxes: list[tuple[str, BBox]] = []
    for name in ExtractedDocument.model_fields:
        value = getattr(doc, name)
        if isinstance(value, FieldRef) and value.bbox is not None:
            boxes.append((name, value.bbox))
    for idx, heat in enumerate(doc.heat_numbers):
        if heat.bbox is not None:
            boxes.append((f"heat_numbers[{idx}]", heat.bbox))
    for idx, result in enumerate(doc.test_results):
        if result.bbox is not None:
            boxes.append((f"test_results[{idx}]({result.heat_number}.{result.parameter})", result.bbox))
    for idx, item in enumerate(doc.line_items):
        for name in type(item).model_fields:
            value = getattr(item, name)
            if isinstance(value, FieldRef) and value.bbox is not None:
                boxes.append((f"line_items[{idx}].{name}", value.bbox))
    return boxes


def overlaps(a: BBox, b: BBox) -> bool:
    """True when the boxes share positive area (touching edges do not count)."""
    return (
        a.page == b.page
        and a.xmin < b.xmax
        and b.xmin < a.xmax
        and a.ymin < b.ymax
        and b.ymin < a.ymax
    )


@pytest.mark.parametrize("filename", HERO_FILENAMES)
def test_every_bbox_is_in_range(filename: str) -> None:
    doc = _generate_fixture_for_file("doc-layout", filename)
    boxes = collect_boxes(doc)
    assert boxes, f"{filename}: fixture has no bounding boxes"
    for label, box in boxes:
        assert box.page >= 1, f"{filename}:{label} page"
        assert 0 <= box.xmin < box.xmax <= 1000, f"{filename}:{label} x range {box}"
        assert 0 <= box.ymin < box.ymax <= 1000, f"{filename}:{label} y range {box}"


@pytest.mark.parametrize("filename", HERO_FILENAMES)
def test_no_two_bboxes_overlap_on_a_page(filename: str) -> None:
    doc = _generate_fixture_for_file("doc-layout", filename)
    clashes = [
        f"{la} {a.model_dump()} x {lb} {b.model_dump()}"
        for (la, a), (lb, b) in itertools.combinations(collect_boxes(doc), 2)
        if overlaps(a, b)
    ]
    assert clashes == [], f"{filename}: overlapping bboxes: {clashes}"


def test_invoice_arithmetic_is_consistent() -> None:
    doc = _generate_fixture_for_file("doc-layout", "commercial_invoice.pdf")
    item = doc.line_items[0]
    qty = float(str(item.quantity.value).split()[0])
    assert item.unit_price is not None and item.total_value is not None
    assert doc.invoice_value is not None
    assert item.unit_price.value == 700.0
    assert qty * float(item.unit_price.value) == float(item.total_value.value) == 84000.0
    assert doc.invoice_value.value == 84000.0


def test_quantity_typo_is_fixed() -> None:
    for filename in ("commercial_invoice.pdf", "packing_list.pdf", "mtc_pipe_test_cert.pdf"):
        doc = _generate_fixture_for_file("doc-layout", filename)
        assert doc.line_items[0].quantity.value == "120 LENGTHS"
