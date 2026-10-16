#!/usr/bin/env python3
"""Records the geometry the Android document viewer has to get right, from the backend's REAL preprocessing.

    cd backend && .venv/bin/python ../android/tools/make_alignment_fixtures.py

For each case (a clean page, a tilted scan, a scan fed sideways and tilted, a PDF whose page carries /Rotate) it writes, under
android/fixtures/viewer/:

  <case>.pdf   the scanned page as a one-page image-only PDF: what the viewer opens
  <case>.json  the transform metadata the backend recorded for it (the same shape as GET .../transform-metadata), the box of the marker
               block on the PROCESSED page (what the model would cite: coordinates of the page image it was shown) and its box on the
               ORIGINAL page as a renderer displays it (what the viewer must outline)

The marker is the one solid block that tests/support/scans.py draws in the page margin; it is the largest dark blob of the page, so it is
found the same way in every orientation. The ORIGINAL box is measured on a render by poppler of the PDF itself, not worked out from what
we believe /Rotate does. The Kotlin tests then render the same PDF with Android's PdfRenderer, map the processed box through
mapProcessedBBoxToOriginal and the viewer's own layout code, and require it to land on the ink. The script also checks the mapping in
Python first and refuses to write a case whose own numbers disagree (so a backend bug cannot be baked into a fixture).

Synthetic pages only. Needs poppler (pdf2image), OpenCV, numpy and Pillow: the backend's development environment.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
OUT = REPO_ROOT / "android" / "fixtures" / "viewer"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services import preprocess  # noqa: E402
from tests.support import scans  # noqa: E402

DPI = 150  # 1240 x 1754 pixels is A4 at 150 dpi


def with_pdf_rotate(pdf: bytes, degrees: int) -> bytes:
    """The same one-page PDF with /Rotate on its page (what a scanner app does when it stores a sideways page 'upright')."""
    patched, count = re.subn(rb"/Type /Page\b(?!s)", f"/Type /Page\n/Rotate {degrees}".encode(), pdf, count=1)
    if count != 1:
        raise SystemExit("could not find the page object to rotate")
    return patched


def cases() -> dict[str, dict]:
    base = scans.make_page(seed=7)
    return {
        "clean": {"scan": base, "note": "an upright page: nothing was done to it"},
        "skew5": {"scan": scans.skew(base, 5.0), "note": "scanned with the text tilted 5 degrees downward to the right"},
        "skew-8": {"scan": scans.skew(base, -8.0), "note": "scanned with the text tilted 8 degrees the other way"},
        "sideways90-skew4": {"scan": scans.rotate_sideways(scans.skew(base, 4.0), 90), "note": "fed sideways (90 clockwise) and tilted 4 degrees"},
        "sideways270-skew4": {"scan": scans.rotate_sideways(scans.skew(base, 4.0), 270), "note": "fed sideways (270 clockwise) and tilted 4 degrees"},
        "sideways180": {"scan": scans.rotate_sideways(base, 180), "note": "fed upside down"},
        "pdf-rotate90": {"scan": base, "rotate": 90, "note": "an upright page stored in a PDF whose page says /Rotate 90, so every viewer shows it sideways"},
    }


def biggest_dark_blob(image: Image.Image) -> tuple[float, float, float, float]:
    """The box of the largest solid dark blob of the page, in 0-1000 coordinates (xmin, ymin, xmax, ymax). The marker is a solid block;
    text blocks are small and thin beside it."""
    width, height = image.size
    dark = (np.asarray(image.convert("L")) < 128).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(dark, connectivity=8)
    if count < 2:
        raise SystemExit("no ink on the page")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(stats[biggest, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    return (round(x / width * 1000, 3), round(y / height * 1000, 3), round((x + w) / width * 1000, 3), round((y + h) / height * 1000, 3))


def box(values: tuple[float, float, float, float]) -> dict[str, float]:
    return {"xmin": values[0], "ymin": values[1], "xmax": values[2], "ymax": values[3]}


def map_through(matrix: list[list[float]], b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    corners = [preprocess.apply_affine(matrix, x, y) for x, y in ((b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3]))]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    clamp = lambda v: min(1000.0, max(0.0, v))  # noqa: E731
    return clamp(min(xs)), clamp(min(ys)), clamp(max(xs)), clamp(max(ys))


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def main() -> int:
    from pdf2image import convert_from_bytes

    settings.preprocess_deskew = True  # the viewer must cope with a page the backend straightened
    OUT.mkdir(parents=True, exist_ok=True)
    for name, case in cases().items():
        pdf = scans.pdf(case["scan"], dpi=DPI)
        if "rotate" in case:
            pdf = with_pdf_rotate(pdf, case["rotate"])

        result = asyncio.run(preprocess.run({"raw_bytes": pdf, "document_id": "doc-1"}))
        [meta] = result["transform_meta"]
        processed = Image.open(io.BytesIO(result["processed_pages"][0]["payload"]))
        processed_box = biggest_dark_blob(processed)

        displayed = convert_from_bytes(pdf, dpi=72, fmt="png")[0]  # what any renderer shows: /Rotate applied
        original_box = biggest_dark_blob(displayed)

        affine = meta["processed_to_source_affine"]
        mapped = map_through(affine, processed_box)
        agreement = iou(mapped, original_box)
        print(f"{name:20s} rotation={meta['rotation']:3d} deskew={meta['deskew_deg']:5.1f} applied={meta['deskew_applied']!s:5s} "
              f"displayed={displayed.size} IoU(mapped, original)={agreement:.3f}")
        if agreement < 0.85:
            raise SystemExit(f"{name}: the backend's own metadata does not carry the marker back onto the page (IoU {agreement:.3f}); not writing it")

        (OUT / f"{name}.pdf").write_bytes(pdf)
        record = {
            "case": name,
            "description": case["note"],
            "transform_metadata": {"document_id": "doc-1", "transform_meta": [json.loads(json.dumps(meta, default=float))]},
            "processed_marker": box(processed_box),
            "original_marker": box(original_box),
            "displayed_pixels_at_72dpi": list(displayed.size),
        }
        (OUT / f"{name}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
