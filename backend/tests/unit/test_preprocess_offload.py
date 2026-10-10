"""preprocess.run renders with blocking libraries (poppler, PIL, OpenCV): that work must not run on the event loop.

The tests patch ``pdf2image.convert_from_bytes`` where they depend on rendering, so they do not need poppler. The one
test that renders the real Case C PDFs is skipped when poppler is not installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import shutil
import threading
import time
from typing import Any

import pytest
from PIL import Image

from app.services import preprocess
from tests.helpers import CASE_C_DIR


def page_image(seed: int, size: tuple[int, int] = (120, 160)) -> Image.Image:
    """A deterministic RGB 'scan' with some structure (so PNG output depends on every pixel)."""
    image = Image.new("RGB", size, "white")
    pixels = image.load()
    for x in range(size[0]):
        for y in range(size[1]):
            if (x * 3 + y * 5 + seed) % 17 < 3:
                pixels[x, y] = ((x + seed) % 256, (y * 2) % 256, (x + y + seed) % 256)
    return image


def old_path(images: list[Image.Image], document_id: str) -> list[dict[str, Any]]:
    """The pre-change per-page sequence, inline: grayscale, PNG, skew, orientation."""
    pages = []
    for index, image in enumerate(images, start=1):
        buffer = io.BytesIO()
        image.convert("L").save(buffer, format="PNG")
        payload = buffer.getvalue()
        pages.append({
            "page": index, "mime": "image/png", "width": image.width, "height": image.height,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "deskew_deg": preprocess.estimate_skew_angle(payload),
            "rotation": preprocess.detect_orientation_pass(payload),
        })
    return pages


def summarise(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "page": page["page"], "mime": page["mime"], "width": meta["width"], "height": meta["height"],
            "sha256": hashlib.sha256(page["payload"]).hexdigest(),
            "deskew_deg": meta["deskew_deg"], "rotation": meta["rotation"],
        }
        for page, meta in zip(result["processed_pages"], result["transform_meta"], strict=True)
    ]


@pytest.mark.asyncio
async def test_rendering_does_not_stall_the_event_loop(monkeypatch) -> None:
    def slow_render(_raw: bytes, **_kw: Any) -> list[Image.Image]:
        time.sleep(0.3)  # what poppler does for a big document: blocks whichever thread runs it
        return [page_image(1)]

    monkeypatch.setattr("pdf2image.convert_from_bytes", slow_render)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-1"})
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert len(result["processed_pages"]) == 1
    assert ticks > 20, f"the loop ticked only {ticks} times during a 0.3 s render"


@pytest.mark.asyncio
async def test_all_cpu_bound_work_runs_in_one_worker_thread(monkeypatch) -> None:
    seen: dict[str, set[int]] = {"render": set(), "skew": set(), "main": {threading.get_ident()}}
    monkeypatch.setattr(
        "pdf2image.convert_from_bytes",
        lambda _raw, **_kw: (seen["render"].add(threading.get_ident()), [page_image(1), page_image(2)])[1],
    )
    real_skew = preprocess.estimate_skew_angle
    monkeypatch.setattr(
        preprocess, "estimate_skew_angle", lambda data: (seen["skew"].add(threading.get_ident()), real_skew(data))[1]
    )

    await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-1"})

    assert len(seen["render"]) == 1 and seen["render"] == seen["skew"], "render and skew share ONE worker thread"
    assert seen["render"].isdisjoint(seen["main"]), "the work ran off the event-loop thread"


@pytest.mark.asyncio
async def test_output_is_identical_to_the_old_code_path_for_synthetic_pages(monkeypatch) -> None:
    images = [page_image(1), page_image(2, (200, 100)), page_image(3)]
    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda _raw, **_kw: images)

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-1"})

    assert summarise(result) == old_path(images, "doc-1")
    assert [m["document_id"] for m in result["transform_meta"]] == ["doc-1"] * 3
    assert all(m["split_offset"] == 0 for m in result["transform_meta"])


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler is not installed")
@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf", "mtc_pipe_test_cert.pdf"])
async def test_case_c_pdfs_render_byte_identically(name) -> None:
    from pdf2image import convert_from_bytes

    raw = (CASE_C_DIR / name).read_bytes()
    expected = old_path(convert_from_bytes(raw, dpi=preprocess.TARGET_DPI, fmt="png"), name)

    result = await preprocess.run({"raw_bytes": raw, "document_id": name})

    assert len(result["processed_pages"]) == len(expected) >= 1
    assert summarise(result) == expected


@pytest.mark.asyncio
async def test_a_render_failure_still_falls_back_to_the_raw_pdf(monkeypatch) -> None:
    def broken(_raw: bytes, **_kw: Any) -> list[Image.Image]:
        raise RuntimeError("poppler is not installed")

    monkeypatch.setattr("pdf2image.convert_from_bytes", broken)

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 raw", "document_id": "doc-1"})

    assert [(p["mime"], p["payload"]) for p in result["processed_pages"]] == [("application/pdf", b"%PDF-1.4 raw")]
    assert result["transform_meta"][0]["width"] == 1000


@pytest.mark.asyncio
async def test_a_large_document_is_still_split_into_offsets(monkeypatch) -> None:
    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda _raw, **_kw: [page_image(i, (20, 20)) for i in range(27)])

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-1"})

    assert [m["split_offset"] for m in result["transform_meta"]] == [i // 13 for i in range(27)]
