#!/usr/bin/env python3
"""A prototype of the deterministic gate the audit recommends, run over the fixtures, to see what it would wrongly keep or reject
BEFORE anybody builds it into the product. Test-side only: nothing in ``app/`` is imported or changed. No network, no Gemini.

    cd backend
    .venv/bin/python -I tests/gating/probe_gate_prototype.py

The gate reads the TEXT LAYER of each page with poppler's ``pdftotext`` (already in the container image) and decides, per file:

    accept       a recognised document type is named on page 1 (a title phrase, or several of its field words)
    needs_vision the page has no usable text layer (a scan): a deterministic gate cannot say; the cheapest vision check decides
    reject       page 1 has text and none of it names a document the product handles

and, per page, whether the page belongs to the document (kept) or is boilerplate (dropped). Printed per fixture. The rules are the
smallest that separate these fixtures; whether they hold on real documents is NOT measured here, and the Chinese invoice shows why
(an English-only list would reject it).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures" / "gating"

STRONG = {
    "COMMERCIAL_INVOICE": ("commercial invoice", "商业发票"),
    "BILL_OF_LADING": ("bill of lading", "提单"),
    "PACKING_LIST": ("packing list", "装箱单"),
    "MILL_TEST_CERTIFICATE": ("mill test certificate", "test certificate", "质量证明书"),
    "CERTIFICATE_OF_ORIGIN": ("certificate of origin", "原产地证"),
    "PHYTOSANITARY": ("phytosanitary certificate",),
}
WEAK = {
    "COMMERCIAL_INVOICE": ("invoice no", "unit price", "total value", "incoterm", "country of origin", "consignee"),
    "BILL_OF_LADING": ("vessel", "port of loading", "port of discharge", "shipper", "freight", "gross weight"),
    "PACKING_LIST": ("packages", "net weight", "gross weight", "marks"),
    "MILL_TEST_CERTIFICATE": ("heat no", "chemical composition", "yield strength", "tensile", "specification"),
}
MIN_TEXT_CHARS = 40          # fewer characters on page 1 than this: no text layer
WEAK_NEEDED = 3              # field words that name a type when its title is not printed
KEEP_PAGE_NUMERIC_TOKENS = 25  # a continuation page of a table has many numbers in its lines; boilerplate has almost none
# (the first version counted every number and kept all 16 pages of the terms fixture: clause numbers such as "3.12" read as numbers.
# A line's FIRST token is now ignored, which is where clause and row numbers sit.)


def page_texts(path: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=60).stdout
    return out.split("\f")[:-1] if out.endswith("\f") else out.split("\f")


def decide(first_page: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", first_page.lower()).strip()
    if len(text) < MIN_TEXT_CHARS:
        return "needs_vision", f"{len(text)} characters of text on page 1"
    for doc_type, phrases in STRONG.items():
        if any(p in text for p in phrases):
            return "accept", f"title phrase for {doc_type}"
    for doc_type, words in WEAK.items():
        hits = [w for w in words if w in text]
        if len(hits) >= WEAK_NEEDED:
            return "accept", f"{len(hits)} field words for {doc_type}"
    return "reject", "page 1 names no document type the product handles"


def keep_page(index: int, text: str) -> bool:
    if index == 0:
        return True
    numbers = sum(len(re.findall(r"\d[\d.,]*", " ".join(line.split()[1:]))) for line in text.splitlines())
    return numbers >= KEEP_PAGE_NUMERIC_TOKENS


def main() -> int:
    names = sorted(p.relative_to(FIXTURES).as_posix() for p in FIXTURES.rglob("*.pdf"))
    print(f"{'fixture':44} {'pages':>5}  {'gate':12} {'kept':>4}  reason")
    for name in names:
        path = FIXTURES / name
        try:
            texts = page_texts(path)
        except Exception as exc:  # noqa: BLE001 - a file poppler cannot read is refused by the upload checks long before this gate
            print(f"{name:44} {'?':>5}  {'unreadable':12} {'-':>4}  {type(exc).__name__}")
            continue
        if not texts or not path.read_bytes().startswith(b"%PDF-") or (len(texts) == 1 and not texts[0].strip() and path.stat().st_size < 400):
            print(f"{name:44} {'?':>5}  {'unreadable':12} {'-':>4}  poppler cannot read the file")
            continue
        verdict, reason = decide(texts[0])
        kept = sum(keep_page(i, t) for i, t in enumerate(texts)) if verdict != "reject" else 0
        print(f"{name:44} {len(texts):>5}  {verdict:12} {kept:>4}  {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
