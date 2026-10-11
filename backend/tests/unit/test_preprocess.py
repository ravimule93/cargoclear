"""Unit tests for the preprocessing service."""

import pytest
from PIL import Image, ImageDraw
from app.services.preprocess import run, estimate_skew_angle, detect_orientation_pass


@pytest.mark.asyncio
async def test_preprocess_empty_payload():
    ctx = {"raw_bytes": b"", "document_id": "doc-empty"}
    res = await run(ctx)
    assert res["processed_pages"] == []
    assert res["transform_meta"] == []


@pytest.mark.asyncio
async def test_preprocess_with_bytes():
    fake_pdf = b"%PDF-1.4 Mock Invoice Stream with trade items and headers"
    ctx = {"raw_bytes": fake_pdf, "document_id": "doc-inv-01"}
    res = await run(ctx)

    assert len(res["processed_pages"]) >= 1
    assert len(res["transform_meta"]) >= 1

    meta = res["transform_meta"][0]
    assert meta["document_id"] == "doc-inv-01"
    assert "deskew_deg" in meta
    assert "rotation" in meta
    assert "split_offset" in meta


def test_skew_angle_and_orientation_defaults():
    empty_bytes = b""
    assert estimate_skew_angle(empty_bytes) == 0.0
    assert detect_orientation_pass(empty_bytes) == 0


def test_orientation_heuristic_corrects_a_confidently_sideways_text_layout() -> None:
    upright = Image.new("L", (160, 240), "white")
    draw = ImageDraw.Draw(upright)
    for y in range(20, 110, 14):
        draw.line((16, y, 144, y), fill="black", width=3)
    sideways = upright.transpose(Image.Transpose.ROTATE_270)  # source is clockwise 90; normalizer must rotate 270.
    import io

    encoded = io.BytesIO()
    sideways.save(encoded, format="PNG")

    assert detect_orientation_pass(encoded.getvalue()) == 270
