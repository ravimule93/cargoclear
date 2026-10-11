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
async def test_output_is_deterministic_one_bit_normalized_pages_with_source_provenance(monkeypatch) -> None:
    images = [page_image(1), page_image(2, (200, 100)), page_image(3)]
    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda _raw, **_kw: images)

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-1"})

    assert [entry["page"] for entry in summarise(result)] == [1, 2, 3]
    assert [m["source_page"] for m in result["transform_meta"]] == [1, 2, 3]
    assert [m["document_id"] for m in result["transform_meta"]] == ["doc-1"] * 3
    assert all(m["split_offset"] == 0 and m["deskew_applied"] is False for m in result["transform_meta"])
    for page in result["processed_pages"]:
        with Image.open(io.BytesIO(page["payload"])) as normalized:
            assert normalized.mode == "1"


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler is not installed")
@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf", "mtc_pipe_test_cert.pdf"])
async def test_case_c_pdfs_render_as_one_bit_source_pages(name) -> None:
    from pdf2image import convert_from_bytes

    raw = (CASE_C_DIR / name).read_bytes()
    expected_count = len(convert_from_bytes(raw, dpi=preprocess.TARGET_DPI, fmt="png"))

    result = await preprocess.run({"raw_bytes": raw, "document_id": name})

    assert len(result["processed_pages"]) == expected_count >= 1
    assert [m["source_page"] for m in result["transform_meta"]] == list(range(1, expected_count + 1))
    for page in result["processed_pages"]:
        with Image.open(io.BytesIO(page["payload"])) as normalized:
            assert normalized.mode == "1"


@pytest.mark.asyncio
async def test_a_render_failure_still_falls_back_to_the_raw_pdf(monkeypatch) -> None:
    def broken(_raw: bytes, **_kw: Any) -> list[Image.Image]:
        raise RuntimeError("poppler is not installed")

    monkeypatch.setattr("pdf2image.convert_from_bytes", broken)

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 raw", "document_id": "doc-1"})

    assert [(p["mime"], p["payload"]) for p in result["processed_pages"]] == [("application/pdf", b"%PDF-1.4 raw")]
    assert result["transform_meta"][0]["width"] == 1000


@pytest.mark.asyncio
async def test_rotation_is_applied_to_the_extraction_payload_and_has_an_inverse_affine(monkeypatch) -> None:
    image = page_image(1, (120, 160))
    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda _raw, **_kw: [image])
    monkeypatch.setattr(preprocess, "detect_orientation_pass", lambda _data: 90)

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-1"})

    with Image.open(io.BytesIO(result["processed_pages"][0]["payload"])) as normalized:
        assert normalized.size == (160, 120)
    meta = result["transform_meta"][0]
    assert meta["rotation"] == 90 and meta["rotation_applied"] is True
    assert meta["processed_to_source_affine"] == [[0, 1, 0], [-1, 0, 1000], [0, 0, 1]]


@pytest.mark.asyncio
async def test_detected_deskew_is_not_claimed_as_applied_without_reversible_geometry(monkeypatch) -> None:
    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda _raw, **_kw: [page_image(1)])
    monkeypatch.setattr(preprocess, "estimate_skew_angle", lambda _data: 3.5)

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-1"})

    meta = result["transform_meta"][0]
    assert meta["deskew_detected_deg"] == 3.5
    assert meta["deskew_deg"] == 0.0 and meta["deskew_applied"] is False and meta["crop"] is None


@pytest.mark.asyncio
async def test_a_large_document_materializes_sequential_compliant_split_artifacts(monkeypatch) -> None:
    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda _raw, **_kw: [page_image(i, (20, 20)) for i in range(27)])

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-1"})

    artifacts = result["processed_artifacts"]
    assert [artifact["artifact_id"] for artifact in artifacts] == ["part-001", "part-002", "part-003"]
    assert [artifact["source_pages"] for artifact in artifacts] == [list(range(1, 14)), list(range(14, 27)), [27]]
    assert all(len(artifact["payload"]) <= preprocess.MAX_BYTES_PER_SPLIT for artifact in artifacts)
    assert [m["artifact_index"] for m in result["transform_meta"]] == [i // 13 + 1 for i in range(27)]
