#!/usr/bin/env python3
"""Generate the Case C and Case D sample PDFs into fixtures/case_c/ and fixtures/case_d/.

Case C: India -> Singapore, the Missing Evidence -> Compliant journey. Case D: a Chinese-origin shipment imported into
India whose certificate chemistry contradicts the declared (non-alloy) HS code. Both are synthetic.

The PDFs are *drawn from the offline extraction fixtures*: every value is printed inside the
bounding box the fixture reports for it (0-1000 normalised, top-left origin), so the UI's
evidence overlays land on the printed text. Weights print their unit after the value ("14000.0 KGS").
Values therefore have a single source of truth.

Run from anywhere with the backend dependencies installed (needs ``reportlab``):

    backend/venv/bin/python scripts/generate_case_c_pdfs.py [--case case_c|case_d] [--out DIR]

Output is deterministic (reportlab invariant mode, uncompressed streams): identical inputs give
identical bytes, which tests/unit/test_case_c_pdfs.py enforces against the committed files.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
DEFAULT_OUT_DIR = REPO_ROOT / "fixtures" / "case_c"
FIXTURES_DIR = REPO_ROOT / "fixtures"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfbase.pdfmetrics import stringWidth  # noqa: E402
from reportlab.pdfgen.canvas import Canvas  # noqa: E402

# _generate_fixture_for_file is private, imported deliberately: the offline extractor is the
# single source of truth for the values and boxes, and duplicating them here would let the
# printed PDFs drift from what the pipeline "reads".
from app.agents.extraction import _generate_fixture_for_file  # noqa: E402
from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LineItem, QuantityRef  # noqa: E402

PAGE_W, PAGE_H = A4  # 595.28 x 841.89 pt
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
BASE_FONT_SIZE = 10.0
MIN_FONT_SIZE = 5.0
LABEL_FONT_SIZE = 6.0
LABEL_GREY = (0.45, 0.45, 0.45)
TITLE_ZONE = 70  # top 7% of the page (0-1000 units): no fixture bbox starts above y=100

# filename -> document title printed in the top zone
DOCUMENTS: dict[str, str] = {
    "commercial_invoice.pdf": "COMMERCIAL INVOICE",
    "bill_of_lading.pdf": "BILL OF LADING",
    "packing_list.pdf": "PACKING LIST",
    "mtc_pipe_test_cert.pdf": "MILL TEST CERTIFICATE",
}
CASE_D_DOCUMENTS: dict[str, str] = {
    "case_d_commercial_invoice.pdf": "COMMERCIAL INVOICE",
    "case_d_bill_of_lading.pdf": "BILL OF LADING",
    "case_d_packing_list.pdf": "PACKING LIST",
    "case_d_mtc_test_cert.pdf": "MILL TEST CERTIFICATE",
}
# case name -> (its documents, the label printed in the PDF metadata)
CASES: dict[str, tuple[dict[str, str], str]] = {
    "case_c": (DOCUMENTS, "Case C"),
    "case_d": (CASE_D_DOCUMENTS, "Case D"),
}

LABELS = {
    "document_number": "Document No.",
    "consignee": "Consignee",
    "consignor": "Consignor",
    "vessel_or_flight": "Vessel / Flight",
    "port_of_loading": "Port of Loading",
    "port_of_discharge": "Port of Discharge",
    "shipment_date": "Shipment Date",
    "invoice_value": "Invoice Value",
    "invoice_currency": "Cur.",
    "total_net_weight_kg": "Net Weight (kg)",
    "total_gross_weight_kg": "Gross Weight (kg)",
    "tare_weight_kg": "Tare (kg)",
    "package_count": "Packages",
    "hs_code_header": "HS Code",
    "description": "Description",
    "quantity": "Quantity",
    "net_weight_kg": "Net (kg)",
    "gross_weight_kg": "Gross (kg)",
    "hs_code_declared": "HS Code",
    "unit_price": "Unit Price",
    "total_value": "Total Value",
    "currency": "Cur.",
    "incoterm": "Incoterm",
    "country_of_origin": "Country of Origin",
    "freight_amount": "Freight",
    "freight_currency": "Cur.",
    "insurance_amount": "Insurance",
    "insurance_currency": "Cur.",
    "specification": "Specification",
    "unit_price_basis": "Price per",
    "heat_numbers": "Heat No.",
}

# (label, text, bbox) with the bbox in 0-1000 page coordinates
Box = tuple[str, str, BBox]


def collect_boxes(doc: ExtractedDocument) -> list[Box]:
    """Every field that has both a value and a bbox: header fields, the heat numbers and test results of a certificate,
    then the line items."""
    boxes: list[Box] = []

    def add(name: str, ref: FieldRef | None, label: str | None = None) -> None:
        if ref is not None and ref.bbox is not None and ref.value is not None:
            # a weight prints its unit after the value ("14000.0 KGS"); everything else prints as before
            text = f"{ref.value} {ref.unit}" if isinstance(ref, QuantityRef) and ref.unit else str(ref.value)
            boxes.append((label or LABELS.get(name, name.replace("_", " ").title()), text, ref.bbox))

    for name in ExtractedDocument.model_fields:
        value = getattr(doc, name)
        if isinstance(value, FieldRef):
            add(name, value)
    for heat in doc.heat_numbers:
        add("heat_numbers", heat)
    for result in doc.test_results:
        unit = f" ({result.unit})" if result.unit else ""
        add("test_results", result, label=f"{result.parameter}{unit}")  # a table cell prints its value; the column heading is its label
    for item in doc.line_items:
        for name in LineItem.model_fields:
            add(name, getattr(item, name))
    return boxes


def _rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """Rectangles as (xmin, ymin, xmax, ymax); touching edges do not overlap."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _fit_font_size(text: str, box_w: float) -> float:
    """Largest size <= BASE_FONT_SIZE whose text fits box_w, floored at MIN_FONT_SIZE."""
    size = BASE_FONT_SIZE
    while size > MIN_FONT_SIZE and stringWidth(text, FONT, size) > box_w:
        size -= 0.25
    return max(size, MIN_FONT_SIZE)


def _draw_value(c: Canvas, text: str, bbox: BBox) -> None:
    x = bbox.xmin / 1000 * PAGE_W
    y_top = bbox.ymin / 1000 * PAGE_H
    box_h = (bbox.ymax - bbox.ymin) / 1000 * PAGE_H
    box_w = (bbox.xmax - bbox.xmin) / 1000 * PAGE_W
    baseline = PAGE_H - y_top - box_h * 0.7

    size = _fit_font_size(text, box_w)
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, PAGE_H - y_top - box_h, box_w, box_h)  # clip anything still too wide at MIN size
    c.clipPath(clip, stroke=0, fill=0)
    c.setFillColorRGB(0, 0, 0)
    c.setFont(FONT, size)
    c.drawString(x, baseline, text)
    c.restoreState()


def _draw_labels(c: Canvas, boxes: list[Box]) -> None:
    """Grey 6 pt label directly above a box, only where that strip is free of other boxes/labels."""
    label_h = LABEL_FONT_SIZE * 1.3 / PAGE_H * 1000  # strip height in page units
    box_rects = [(b.xmin, b.ymin, b.xmax, b.ymax) for _, _, b in boxes]
    placed: list[tuple[float, float, float, float]] = []

    for idx, (label, _text, bbox) in enumerate(boxes):
        label_w = stringWidth(label, FONT, LABEL_FONT_SIZE) / PAGE_W * 1000
        strip = (bbox.xmin, bbox.ymin - label_h, bbox.xmin + label_w, bbox.ymin)
        if strip[1] < TITLE_ZONE:
            continue
        others = [r for j, r in enumerate(box_rects) if j != idx]
        if any(_rects_overlap(strip, r) for r in others + placed):
            continue
        placed.append(strip)
        c.setFillColorRGB(*LABEL_GREY)
        c.setFont(FONT, LABEL_FONT_SIZE)
        c.drawString(
            bbox.xmin / 1000 * PAGE_W,
            PAGE_H - bbox.ymin / 1000 * PAGE_H + LABEL_FONT_SIZE * 0.3,
            label,
        )


def render_pdf(filename: str) -> bytes:
    """Render one sample document (Case C or Case D) to PDF bytes (deterministic)."""
    for documents, case_label in CASES.values():
        if filename in documents:
            title = documents[filename]
            break
    else:
        raise KeyError(f"{filename} is not a known sample document")
    doc = _generate_fixture_for_file(f"doc-{Path(filename).stem}", filename)
    boxes = collect_boxes(doc)
    off_page = [b for _, _, b in boxes if b.page != 1]
    if off_page:
        raise ValueError(f"{filename}: only single-page fixtures are supported, got {off_page[0]}")

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4, invariant=1, pageCompression=0)
    c.setTitle(f"{title} (CargoClear {case_label} sample)")
    c.setAuthor("CargoClear demo fixtures")
    c.setSubject(f"Synthetic sample document for the CargoClear {case_label} demo")
    c.setCreator("scripts/generate_case_c_pdfs.py")

    c.setFillColorRGB(0, 0, 0)
    c.setFont(FONT_BOLD, 14)
    c.drawString(PAGE_W * 0.08, PAGE_H - 30, title)
    c.setFillColorRGB(*LABEL_GREY)
    c.setFont(FONT, 6.5)
    c.drawString(PAGE_W * 0.08, PAGE_H - 45, "Synthetic sample for the CargoClear demo - not a real shipping document")

    _draw_labels(c, boxes)
    for _label, text, bbox in boxes:
        _draw_value(c, text, bbox)

    c.showPage()
    c.save()
    return buf.getvalue()


def generate(out_dir: Path, case: str = "case_c") -> list[Path]:
    """Write the four sample PDFs of ``case`` into ``out_dir`` and return their paths."""
    documents, _label = CASES[case]
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename in documents:
        path = out_dir / filename
        path.write_bytes(render_pdf(filename))
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", choices=sorted(CASES), default=None, help="one case (default: both)")
    parser.add_argument("--out", type=Path, default=None, help="output directory (only with --case; default fixtures/<case>)")
    args = parser.parse_args()
    if args.out is not None and args.case is None:
        parser.error("--out needs --case")
    for case in [args.case] if args.case else sorted(CASES):
        for path in generate(args.out or FIXTURES_DIR / case, case):
            print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
