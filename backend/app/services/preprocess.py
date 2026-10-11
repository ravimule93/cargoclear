"""Preprocessing service — automated e-SANCHIT compliance, deskew, and split engine.

Per v4.0 Specification (US 1.1, US 1.2):
  - Ingests raw PDF documents.
  - Generates transform metadata so bounding box coordinates can be remapped
    accurately to the original PDF pages in the UI canvas layer.
  - Applies 0/90/180/270 rotation normalization and deskew heuristics.
  - Page count and size limits:
      Threshold: >1 MB or >13 pages triggers sequential sub-document splitting.
  - Provides graceful fallback handling when external image processing libraries
    (poppler/OpenCV) are unavailable in the runtime environment.
"""

from __future__ import annotations

import asyncio
import io
import math
from typing import Any

import structlog

from app.gateway.errors import PipelineError

logger = structlog.get_logger(__name__)

TARGET_DPI = 200
MAX_BYTES_PER_SPLIT = 1_000_000  # 1 MB threshold per e-SANCHIT constraints
MAX_PAGES_PER_SPLIT = 13


class PreprocessError(PipelineError):
    """A required compliant preprocessing artifact could not be produced."""


def estimate_skew_angle(image_bytes: bytes) -> float:
    """Estimate document skew angle in degrees.

    Uses OpenCV Hough transform if available, otherwise returns 0.0.
    """
    try:
        import cv2
        import numpy as np

        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0

        # Edge detection
        edges = cv2.Canny(img, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, math.pi / 180, threshold=100, minLineLength=100, maxLineGap=10)
        if lines is None:
            return 0.0

        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 - x1 != 0:
                angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
                if -45 < angle < 45:
                    angles.append(angle)

        if not angles:
            return 0.0

        # Return median angle
        angles.sort()
        return round(angles[len(angles) // 2], 2)
    except Exception as exc:
        logger.debug("opencv_skew_skipped", reason=str(exc))
        return 0.0


def detect_orientation_pass(image_bytes: bytes) -> int:
    """Return the clockwise normalization rotation (0/90/180/270), or identity when uncertain.

    The heuristic first prefers horizontal text-line structure, then uses a deliberately small
    top-versus-bottom ink bias to distinguish an upright page from its 180-degree inverse.
    It only rotates when a non-identity candidate is materially better than identity, avoiding
    unsupported guesses for symmetric, photographic, or otherwise ambiguous pages.
    """
    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            base = image.convert("L")
            scores = {rotation: _orientation_score(_rotate_clockwise(base, rotation)) for rotation in (0, 90, 180, 270)}
    except Exception:
        return 0

    best = max(scores, key=scores.__getitem__)
    # A weak preference is not evidence: retain the source orientation in that case.
    return best if best != 0 and scores[best] >= scores[0] + 0.12 else 0


def _rotate_clockwise(image, rotation: int):
    from PIL import Image

    transpose = {
        0: None,
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }.get(rotation)
    return image if transpose is None else image.transpose(transpose)


def _orientation_score(image) -> float:
    """A compact document-layout score; positive values favour upright horizontal text."""
    sample = image.resize((128, 180)).convert("L")
    pixels = list(sample.get_flattened_data())
    rows = [0.0] * sample.height
    columns = [0.0] * sample.width
    for index, value in enumerate(pixels):
        ink = (255 - value) / 255
        rows[index // sample.width] += ink
        columns[index % sample.width] += ink
    row_mean = sum(rows) / len(rows)
    col_mean = sum(columns) / len(columns)
    row_variance = sum((value - row_mean) ** 2 for value in rows) / len(rows)
    col_variance = sum((value - col_mean) ** 2 for value in columns) / len(columns)
    total = sum(rows)
    if total == 0:
        return 0.0
    top_bias = (sum(rows[: len(rows) // 2]) - sum(rows[len(rows) // 2 :])) / total
    return (row_variance - col_variance) / (row_variance + col_variance + 1e-9) + (top_bias * 0.2)


def _processed_to_source_affine(rotation: int) -> list[list[int]]:
    """Normalized 0–1000 affine transform from rotated extraction coordinates to source coordinates."""
    return {
        90: [[0, 1, 0], [-1, 0, 1000], [0, 0, 1]],
        180: [[-1, 0, 1000], [0, -1, 1000], [0, 0, 1]],
        270: [[0, -1, 1000], [1, 0, 0], [0, 0, 1]],
    }.get(rotation, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])


def _render_pages(
    raw: bytes, document_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Render ``raw`` to grayscale PNG pages (blocking: run it with ``asyncio.to_thread``).

    Returns ``(processed_pages, transforms, artifacts)``. Raises when the document cannot be rendered (poppler missing, broken
    PDF); the caller falls back to passing the raw PDF through.
    """
    from pdf2image import convert_from_bytes

    transforms: list[dict[str, Any]] = []
    processed_pages: list[dict[str, Any]] = []

    images = convert_from_bytes(raw, dpi=TARGET_DPI, fmt="png")

    for idx, img in enumerate(images, start=1):
        buf = io.BytesIO()
        source_gray = img.convert("L")
        source_buffer = io.BytesIO()
        source_gray.save(source_buffer, format="PNG")
        rotation = detect_orientation_pass(source_buffer.getvalue())
        normalized = _rotate_clockwise(source_gray, rotation)
        # Exact deskew inversion needs crop/translation geometry that the current pipeline does not create.
        # Keep it as a no-op rather than claiming a transform that was never applied.
        detected_skew = estimate_skew_angle(source_buffer.getvalue())
        bw_img = normalized.point(lambda value: 0 if value < 200 else 255, mode="1")
        bw_img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        transforms.append({
            "page": idx,
            "source_page": idx,
            "processed_page": idx,
            "document_id": document_id,
            "deskew_deg": 0.0,
            "deskew_detected_deg": detected_skew,
            "deskew_applied": False,
            "rotation": rotation,
            "rotation_applied": rotation != 0,
            "processed_to_source_affine": _processed_to_source_affine(rotation),
            "crop": None,
            "split_offset": 0,
            "artifact_index": 0,
            "artifact_page": idx,
            "artifact_id": None,
            "width": bw_img.width,
            "height": bw_img.height,
        })
        processed_pages.append({
            "page": idx,
            "source_page": idx,
            "document_id": document_id,
            "payload": img_bytes,
            "mime": "image/png",
        })

    artifacts = _split_artifacts(processed_pages, transforms, raw_size=len(raw), document_id=document_id)
    return processed_pages, transforms, artifacts


def _artifact_pdf(pages: list[dict[str, Any]]) -> bytes:
    from PIL import Image

    images = []
    for page in pages:
        with Image.open(io.BytesIO(page["payload"])) as image:
            images.append(image.convert("RGB"))
    output = io.BytesIO()
    images[0].save(output, format="PDF", resolution=TARGET_DPI, save_all=True, append_images=images[1:])
    return output.getvalue()


def _split_artifacts(
    pages: list[dict[str, Any]], transforms: list[dict[str, Any]], *, raw_size: int, document_id: str
) -> list[dict[str, Any]]:
    """Materialize sequential <=13-page, <=1MB processed PDFs when e-SANCHIT thresholds require it."""
    if raw_size <= MAX_BYTES_PER_SPLIT and len(pages) <= MAX_PAGES_PER_SPLIT:
        return []

    artifacts: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for page in pages:
        candidate = current + [page]
        candidate_pdf = _artifact_pdf(candidate)
        started_new_artifact = False
        if current and (len(candidate) > MAX_PAGES_PER_SPLIT or len(candidate_pdf) > MAX_BYTES_PER_SPLIT):
            artifacts.append({"payload": _artifact_pdf(current), "pages": current})
            current = [page]
            candidate_pdf = _artifact_pdf(current)
            started_new_artifact = True
        if len(candidate_pdf) > MAX_BYTES_PER_SPLIT:
            raise PreprocessError(
                f"Unable to create a compliant processed artifact for document {document_id}: source page "
                f"{page['source_page']} exceeds the 1 MB limit by itself."
            )
        current = current if started_new_artifact else candidate
    if current:
        artifacts.append({"payload": _artifact_pdf(current), "pages": current})

    for artifact_index, artifact in enumerate(artifacts, start=1):
        artifact_id = f"part-{artifact_index:03d}"
        for artifact_page, page in enumerate(artifact["pages"], start=1):
            index = page["source_page"] - 1
            transforms[index].update({
                "artifact_index": artifact_index,
                "artifact_page": artifact_page,
                "artifact_id": artifact_id,
                "split_offset": artifact_index - 1,
            })
        artifact.update({
            "artifact_index": artifact_index,
            "artifact_id": artifact_id,
            "source_pages": [page["source_page"] for page in artifact["pages"]],
            "mime": "application/pdf",
        })
        del artifact["pages"]
    return artifacts


async def run(ctx: dict[str, Any]) -> dict[str, Any]:
    """Execute preprocessing on document pages in the context.

    Reads:
      - ctx["raw_bytes"] (bytes) or document payloads
      - ctx["bundle_id"] (str)
      - ctx["document_id"] (str)

    Writes:
      - ctx["processed_pages"] (list[dict]): preprocessed page buffers
      - ctx["transform_meta"] (list[dict]): deskew angle, rotation, and split offsets
    """
    raw: bytes = ctx.get("raw_bytes", b"")
    document_id: str = ctx.get("document_id", "doc-default")

    if not raw:
        ctx["processed_pages"] = []
        ctx["transform_meta"] = []
        return ctx

    try:
        # ONE worker-thread call: poppler, PIL and OpenCV block, and the event loop carries the heartbeat, the SSE
        # streams and every other request
        processed_pages, transforms, artifacts = await asyncio.to_thread(_render_pages, raw, document_id)

    except Exception as exc:
        logger.info("pdf2image_processing_fallback", note="Using raw stream passthrough", error=str(exc))
        # Lightweight fallback: wrap raw PDF directly
        if len(raw) > MAX_BYTES_PER_SPLIT:
            raise PreprocessError("Unable to create compliant split artifacts because PDF rendering is unavailable.") from exc
        transforms = [{
            "page": 1,
            "source_page": 1,
            "processed_page": 1,
            "document_id": document_id,
            "deskew_deg": 0.0,
            "deskew_detected_deg": 0.0,
            "deskew_applied": False,
            "rotation": 0,
            "rotation_applied": False,
            "processed_to_source_affine": _processed_to_source_affine(0),
            "crop": None,
            "split_offset": 0,
            "artifact_index": 0,
            "artifact_page": 1,
            "artifact_id": None,
            "width": 1000,
            "height": 1000,
        }]
        processed_pages = [{
            "page": 1,
            "document_id": document_id,
            "payload": raw,
            "mime": "application/pdf",
        }]
        artifacts = []

    if artifacts:
        logger.info("auto_split_materialized", document_id=document_id, artifacts=len(artifacts), page_count=len(processed_pages))

    ctx["processed_pages"] = processed_pages
    ctx["transform_meta"] = transforms
    ctx["processed_artifacts"] = artifacts
    return ctx
