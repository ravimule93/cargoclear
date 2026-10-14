#!/usr/bin/env python3
"""Make degraded copies of the sample PDFs, to compare extraction under realistic scan quality.

    backend/.venv/bin/python scripts/make_degraded_scans.py [--out DIR] [--docs PDF ...] [--only NAME ...]

Each sample PDF (default: every PDF in fixtures/case_c and fixtures/case_d) is rendered at 200 DPI, degraded in a way real
scans go wrong, and written as an image-only PDF with the SAME FILE NAME under <out>/<degradation>/. The printed values are
unchanged, so ``live_smoke_extraction.py --as-fixtures --docs <out>/<degradation>/*.pdf`` can grade the model against the same
expectations as the clean files. Then A/B the model's input on the same set:

    live_smoke_extraction.py --as-fixtures --page-mode bw   --docs <out>/skew3/*.pdf
    live_smoke_extraction.py --as-fixtures --page-mode gray --docs <out>/skew3/*.pdf
    compare_smoke_reports.py <report A> <report B>

The degradations are deterministic (seeded) and are the ones the preprocessing tests use (backend/tests/support/scans.py):
skew3, skew-6 (the text tilted), noise, blur, faded, jpeg, unevenlight, and sideways90 (fed sideways) + skew3.
Synthetic documents only. Needs poppler (pdf2image) and Pillow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tests.support import scans  # noqa: E402

DEGRADATIONS = {
    "skew3": lambda page: scans.skew(page, 3.0),
    "skew-6": lambda page: scans.skew(page, -6.0),
    "noise": scans.noisy,
    "blur": scans.blurred,
    "faded": scans.faded,
    "jpeg": scans.jpeg,
    "unevenlight": scans.unevenly_lit,
    "sideways90": lambda page: scans.rotate_sideways(scans.skew(page, 3.0), 90),
}


def degrade(pdf: bytes, how: str) -> bytes:
    """The first page of ``pdf``, degraded, as an image-only one-page PDF (what a scanner produces)."""
    from pdf2image import convert_from_bytes

    pages = convert_from_bytes(pdf, dpi=200, fmt="png")
    return scans.pdf(DEGRADATIONS[how](pages[0].convert("L")), dpi=200)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make degraded copies of the sample PDFs.")
    parser.add_argument("--out", type=Path, default=BACKEND_DIR / "data" / "degraded_scans")
    parser.add_argument("--docs", nargs="+", type=Path,
                        default=sorted((REPO_ROOT / "fixtures" / "case_c").glob("*.pdf")) + sorted((REPO_ROOT / "fixtures" / "case_d").glob("*.pdf")))
    parser.add_argument("--only", nargs="+", choices=sorted(DEGRADATIONS), help="only these degradations")
    args = parser.parse_args(argv)

    written = 0
    for how in args.only or sorted(DEGRADATIONS):
        target = args.out / how
        target.mkdir(parents=True, exist_ok=True)
        for path in args.docs:
            (target / path.name).write_bytes(degrade(path.read_bytes(), how))
            written += 1
        print(f"{how}: {len(args.docs)} files in {target}")
    print(f"{written} degraded PDFs written. Grade them with live_smoke_extraction.py --as-fixtures (see the module docstring).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
