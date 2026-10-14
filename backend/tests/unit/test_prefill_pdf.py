"""The printable pre-fill summary: it renders, says the verdict first, and survives hostile text."""

from __future__ import annotations

import re
from typing import Any

from app.services.prefill import assemble
from app.services.prefill_pdf import render
from tests.unit.test_prefill import NOW, bundle, docs, iteration, ref  # noqa: F401 - shared synthetic bundle

from app.reference.loader import get_reference


def pack(extracted=None, **kw: Any):
    return assemble(
        bundle=kw.pop("bundle_", bundle()), iteration=kw.pop("iteration_", iteration()),
        extracted=extracted if extracted is not None else docs(), audit_events=[], reference=get_reference(), now=NOW, **kw,
    )


def text_of(pdf: bytes) -> str:
    """The text of an uncompressed standard-font PDF: every `(text) Tj` string, escapes resolved, joined by spaces
    (the renderer leaves its streams uncompressed on purpose, so no PDF library is needed to read it)."""

    def unescape(raw: bytes) -> str:
        text = raw.decode("latin-1")
        text = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), text)
        return re.sub(r"\\(.)", r"\1", text)

    strings = re.findall(rb"\(((?:\\.|[^\\)])*)\) Tj", pdf)
    return " ".join(" ".join(unescape(s) for s in strings).split())


def pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type /Page\b", pdf))


def test_it_is_a_pdf_with_the_values_and_where_they_came_from() -> None:
    pdf = render(pack())
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF") and pages(pdf) >= 1
    text = text_of(pdf)
    for expected in ("Declaration pre-fill", "ACME PTE. LTD.", "TIANJIN STEEL CO", "BL-9", "FOB TIANJIN", "14,280.50 KGS", "73041900",
                     "ASTM A106 GR B", "H1, H2", "Commercial invoice p.1", "Bill of lading p.1"):
        assert expected in text, expected
    assert "compliant for submission" in text, "a cleared bundle says so"


def test_a_bundle_that_is_not_cleared_says_so_first_and_lists_what_blocks_it() -> None:
    checks = [{"check_id": "M-001", "severity": "MATERIAL", "message": "heat H2 reports Cr 0.35%"}]
    text = text_of(render(pack(iteration_=iteration("MATERIAL_CONTRADICTION", checks), pending_corrections=1)))
    assert text.index("NOT CLEARED") < text.index("ACME PTE. LTD."), "the verdict comes before any value"
    assert "Findings to resolve" in text and "heat H2 reports Cr 0.35%" in text and "Contradiction" in text
    assert "1 correction change(s) made after this assessment are NOT included" in text


def test_hostile_and_non_latin_text_does_not_break_the_layout() -> None:
    changed = docs()
    changed[0]["consignor"] = ref("天津华兴钢管有限公司 <b>&</b> Co & \x00 \"quotes\"")
    changed[0]["line_items"][0]["description"] = ref("PIPE " + "very long description " * 40)
    pdf = render(pack(changed))
    assert pdf.startswith(b"%PDF-") and pages(pdf) >= 1
    text = text_of(pdf)
    assert "?" in text and "天" not in text, "non-Latin characters print as ? (and the footer says so)"
    assert "non-Latin characters print as ? here" in text


def test_a_long_pack_runs_onto_more_pages_and_keeps_its_header_row() -> None:
    changed = docs()
    changed[0]["line_items"] = [{**changed[0]["line_items"][0], "description": ref(f"LINE {n} " + "x " * 30)} for n in range(60)]
    pdf = render(pack(changed))
    assert pages(pdf) >= 3
    assert text_of(pdf).count("HS code") >= 2, "the lines table repeats its header on each page"


def test_it_renders_with_nothing_but_an_empty_bundle() -> None:
    bare = [{"document_id": "inv", "doc_type": "COMMERCIAL_INVOICE", "line_items": []}]
    pdf = render(pack(bare, iteration_={"iteration": 1, "status": "MISSING_EVIDENCE", "documents": ["inv"]}))
    assert pdf.startswith(b"%PDF-") and "(not stated)" in text_of(pdf) and "NOT CLEARED" in text_of(pdf)
