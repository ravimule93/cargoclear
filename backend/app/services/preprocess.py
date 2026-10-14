"""Preprocessing service — automated e-SANCHIT compliance, deskew, and split engine.

Per v4.0 Specification (US 1.1, US 1.2):
  - Ingests raw PDF documents.
  - Generates transform metadata so bounding box coordinates can be remapped
    accurately to the original PDF pages in the UI canvas layer.
  - Applies 0/90/180/270 rotation normalization and (PREPROCESS_DESKEW) a continuous deskew. Every geometric change
    is recorded as a REVERSIBLE affine (``processed_to_source_affine``, normalized 0-1000 coordinates, aspect-aware), so
    a box the model reports on the processed page maps back exactly onto the original page.
  - Page count and size limits:
      Threshold: >1 MB or >13 pages triggers sequential sub-document splitting.
  - Provides graceful fallback handling when external image processing libraries
    (poppler/OpenCV) are unavailable in the runtime environment.
"""

from __future__ import annotations

import asyncio
import io
import math
from typing import TYPE_CHECKING, Any

import structlog

from app.core.config import settings
from app.gateway.errors import PipelineError

if TYPE_CHECKING:  # the image libraries are imported lazily, inside the functions that use them
    import numpy as np
    from PIL import Image

logger = structlog.get_logger(__name__)

TARGET_DPI = 200
MAX_BYTES_PER_SPLIT = 1_000_000  # 1 MB threshold per e-SANCHIT constraints
MAX_PAGES_PER_SPLIT = 13


class PreprocessError(PipelineError):
    """A required compliant preprocessing artifact could not be produced."""


_SKEW_SEARCH_DEG = 15.0   # the estimator looks this far either way
_SKEW_WIDTH = 800         # pages are reduced to this width first: the angle does not need 200 DPI
_SKEW_MIN_GAIN = 1.02     # the best angle must straighten the text lines at least this much more than 0 degrees does


def estimate_skew_angle(image_bytes: bytes) -> float:
    """The skew of a page in degrees: positive when its text lines slope DOWNWARD to the right (the page was scanned
    clockwise-tilted). Rotating the page COUNTER-CLOCKWISE by this angle straightens it (``deskew_image``).

    Projection profile: the page is rotated through candidate angles and the angle at which its ink rows are most
    unevenly filled (text lines horizontal: dense rows between empty ones) wins; a coarse 1-degree sweep, then 0.1 degree.
    Deterministic, needs no OpenCV, searches a 0.1 degree grid (at most 0.05 degree off on the synthetic test pages; not measured on real scans). Returns 0.0 for a blank page, an unreadable
    image, or a page where no angle straightens the lines clearly better than none does (photographs, stamps, noise).
    """
    try:
        import numpy as np
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(image_bytes)) as source:
            gray = source.convert("L")
        if gray.width > _SKEW_WIDTH:
            gray = gray.resize((_SKEW_WIDTH, max(1, round(gray.height * _SKEW_WIDTH / gray.width))), Image.Resampling.BILINEAR)
        ink = ImageOps.autocontrast(gray, cutoff=1).point(lambda value: 255 if value < 128 else 0)
        ink_fraction = float(np.asarray(ink, dtype=np.float32).mean()) / 255.0
        if not 0.0005 < ink_fraction < 0.5:  # a blank page, or one that is mostly ink (black, a dark photograph): no text lines
            return 0.0

        def score(angle: float) -> float:
            rotated = ink.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=0)
            return float(np.var(np.asarray(rotated, dtype=np.float32).sum(axis=1)))

        coarse = max(np.arange(-_SKEW_SEARCH_DEG, _SKEW_SEARCH_DEG + 0.01, 1.0), key=score)
        best = max(np.arange(coarse - 1.0, coarse + 1.01, 0.1), key=score)
        if score(best) < score(0.0) * _SKEW_MIN_GAIN:
            return 0.0
        return round(float(best), 1)
    except Exception as exc:
        logger.debug("skew_estimate_skipped", reason=type(exc).__name__)
        return 0.0


def _pixel_affine(angle_deg: float, width: int, height: int) -> tuple[float, float, float, float, float, float]:
    """PIL's AFFINE data (a, b, c, d, e, f) for the deskew of ``angle_deg``: each OUTPUT pixel (x, y) is read from the INPUT
    at (a x + b y + c, d x + e y + f). That is exactly the processed -> source mapping of this step, in pixel coordinates:
    a rotation by ``angle_deg`` counter-clockwise about the page centre (y points down)."""
    phi = math.radians(angle_deg)
    cos, sin = math.cos(phi), math.sin(phi)
    cx, cy = width / 2.0, height / 2.0
    a, b, d, e = cos, -sin, sin, cos
    return a, b, cx - (a * cx + b * cy), d, e, cy - (d * cx + e * cy)


def deskew_image(image: Image.Image, angle_deg: float) -> Image.Image:
    """The page rotated COUNTER-CLOCKWISE by ``angle_deg`` about its centre, on a canvas of the same size (the corners that
    swing out are cropped, the ones that swing in are white). Reversible with ``deskew_to_source_affine``."""
    from PIL import Image

    return image.transform(
        image.size, Image.Transform.AFFINE, _pixel_affine(angle_deg, image.width, image.height),
        resample=Image.Resampling.BICUBIC, fillcolor=255,
    )


def deskew_to_source_affine(angle_deg: float, width: int, height: int) -> list[list[float]]:
    """The deskew as a 3x3 affine in NORMALIZED coordinates (0-1000 on both axes, origin top-left): a point of the processed
    page -> the same point of the page before the deskew. Aspect-aware: the pixel affine is conjugated with the page's
    width and height, so a rectangular page does not turn into a shear."""
    a, b, c, d, e, f = _pixel_affine(angle_deg, width, height)
    return [
        [a, b * height / width, c * 1000.0 / width],
        [d * width / height, e, f * 1000.0 / height],
        [0.0, 0.0, 1.0],
    ]


def compose_affines(outer: list[list[float]], inner: list[list[float]]) -> list[list[float]]:
    """``outer`` after ``inner`` (3x3 matrix product), rounded to 9 places so that the stored matrix is stable and readable."""
    product = [[sum(outer[i][k] * inner[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return [[round(value, 9) + 0.0 for value in row] for row in product]  # + 0.0: no negative zero


def apply_affine(matrix: list[list[float]], x: float, y: float) -> tuple[float, float]:
    """A normalized point through a normalized affine."""
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2],
    )


# Orientation is judged on a small copy of the page. First the AXIS: text lines make the ink rows uneven (dense lines between
# empty gaps), so the rotation pair (0/180 or 90/270) at which the row profile is most uneven holds the horizontal lines. That is
# measured at every small tilt in the range below, because a page scanned a few degrees crooked has its rows smeared at its true
# orientation and must not lose to a wrong one for that reason. Then the POLARITY within the axis: pages carry more ink in their
# top half than their bottom (headings, letterheads), a weak signal, so an upside-down page is only turned when it is clearly
# bottom-heavy, and a sideways page is turned to the candidate that is more top-heavy.
_ORIENTATION_TILTS = tuple(float(angle) for angle in range(-12, 13))
_ORIENTATION_SAMPLE = (256, 360)
_AXIS_RATIO = 1.6          # one axis must be this much stronger than the other ...
_AXIS_MIN_GAP = 0.1        # ... and by at least this much, or the page is left as it is
_FLIP_BIAS_MARGIN = 0.6    # how much more top-heavy the 180-degree turn must be to be trusted


def _ink_sample(image: Image.Image) -> np.ndarray:
    """The page as a small array of ink (0..1, text darker than its LOCAL background, so uneven lighting and a tinted page
    do not read as ink), in the page's own orientation."""
    import numpy as np
    from PIL import ImageFilter

    gray = image.convert("L").resize(_ORIENTATION_SAMPLE)
    background = np.asarray(gray.filter(ImageFilter.BoxBlur(24)), dtype=np.float32)
    ink = np.clip(1.0 - np.asarray(gray, dtype=np.float32) / np.maximum(background, 1.0), 0.0, 1.0)
    return np.where(ink < 0.12, 0.0, ink)  # sensor noise and paper texture are not text


def _line_strength(ink: np.ndarray) -> float:
    """How strongly the rows of ``ink`` look like lines of text, at the best small tilt: the squared coefficient of variation
    of the row sums (about 1 for a text page, a third of that or less for vertical lines, whatever the contrast)."""
    import numpy as np
    from PIL import Image

    picture = Image.fromarray((ink * 255.0).astype(np.uint8), "L")
    best = 0.0
    for tilt in _ORIENTATION_TILTS:
        tilted = picture if tilt == 0.0 else picture.rotate(tilt, resample=Image.Resampling.BILINEAR, fillcolor=0)
        rows = np.asarray(tilted, dtype=np.float32).sum(axis=1)
        mean = float(rows.mean())
        if mean > 0:
            best = max(best, float(rows.var()) / (mean * mean))
    return best


def _top_bias(ink: np.ndarray) -> float:
    """+1: all the ink is in the top half; -1: all in the bottom half."""
    rows = ink.sum(axis=1)
    total = float(rows.sum())
    if total == 0:
        return 0.0
    half = len(rows) // 2
    return (float(rows[:half].sum()) - float(rows[half:].sum())) / total


def detect_orientation_pass(image_bytes: bytes) -> int:
    """Return the clockwise normalization rotation (0/90/180/270), or identity when uncertain.

    Axis first (which rotation pair makes the text lines horizontal, at the best small tilt), then polarity (a weak top-heavy
    bias). It rotates only on clear evidence: for symmetric, photographic or otherwise ambiguous pages the source orientation
    is kept, and an upside-down page is turned only when it is clearly bottom-heavy (without OCR the two are hard to tell apart).
    """
    import numpy as np
    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            ink = _ink_sample(image)
    except Exception:
        return 0
    if not float(ink.sum()):
        return 0

    horizontal = _line_strength(ink)
    vertical = _line_strength(np.rot90(ink, -1))
    if vertical >= horizontal * _AXIS_RATIO and vertical - horizontal >= _AXIS_MIN_GAP:
        upright_when_turned = {rotation: _top_bias(np.rot90(ink, -(rotation // 90))) for rotation in (90, 270)}
        return max(upright_when_turned, key=upright_when_turned.__getitem__)
    if horizontal >= vertical * _AXIS_RATIO and horizontal - vertical >= _AXIS_MIN_GAP:
        if _top_bias(np.rot90(ink, 2)) - _top_bias(ink) >= _FLIP_BIAS_MARGIN:
            return 180
    return 0


def _rotate_clockwise(image: Image.Image, rotation: int) -> Image.Image:
    from PIL import Image

    transpose = {
        0: None,
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }.get(rotation)
    return image if transpose is None else image.transpose(transpose)


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

    mode = settings.page_image_mode
    for idx, img in enumerate(images, start=1):
        buf = io.BytesIO()
        source_gray = img.convert("L")
        source_buffer = io.BytesIO()
        source_gray.save(source_buffer, format="PNG")
        rotation = detect_orientation_pass(source_buffer.getvalue())
        normalized = _rotate_clockwise(source_gray, rotation)

        # The skew is measured on the UPRIGHT page (on a sideways one the text lines are vertical).
        upright = io.BytesIO()
        normalized.save(upright, format="PNG")
        detected_skew = estimate_skew_angle(upright.getvalue())
        affine: list[list[float]] | list[list[int]] = _processed_to_source_affine(rotation)
        applied_skew, skipped = 0.0, None
        if not settings.preprocess_deskew:
            skipped = "disabled"
        elif abs(detected_skew) < settings.deskew_min_degrees:
            skipped = "below_threshold"
        elif abs(detected_skew) > settings.deskew_max_degrees:
            skipped = "above_limit"  # a skew this large is more likely a misreading than a scan: leave the page alone
        else:
            normalized = deskew_image(normalized, detected_skew)
            applied_skew = detected_skew
            affine = compose_affines(
                [[float(v) for v in row] for row in affine],
                deskew_to_source_affine(applied_skew, normalized.width, normalized.height),
            )

        shown = normalized if mode == "gray" else normalized.point(lambda value: 0 if value < 200 else 255, mode="1")
        shown.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        transforms.append({
            "page": idx,
            "source_page": idx,
            "processed_page": idx,
            "document_id": document_id,
            "deskew_deg": applied_skew,
            "deskew_detected_deg": detected_skew,
            "deskew_applied": applied_skew != 0.0,
            "deskew_skipped": skipped,
            "rotation": rotation,
            "rotation_applied": rotation != 0,
            "processed_to_source_affine": affine,
            "crop": None,
            "split_offset": 0,
            "artifact_index": 0,
            "artifact_page": idx,
            "artifact_id": None,
            "image_mode": mode,
            "width": shown.width,
            "height": shown.height,
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
