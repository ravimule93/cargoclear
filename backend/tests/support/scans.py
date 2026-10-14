"""A deterministic corpus of synthetic scanned pages and the ways a real scan goes wrong.

Every page is drawn from a seed (no randomness the test cannot repeat), so a failure reproduces exactly. The page has
text-like lines (rows of small ink blocks, the structure skew and orientation heuristics read), a heading block, and ONE solid
MARKER block in the right margin where nothing else is drawn: the geometry tests find the marker in the processed page and
check that the affine carries it back to where it was on the original page.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

A4_150DPI = (1240, 1754)  # a realistic, non-square page: an aspect-blind affine would show


@dataclass(frozen=True)
class Marker:
    """The marker block's box in the page it was drawn on, as fractions of the page (so any size reuses it)."""

    x0: float = 0.84
    y0: float = 0.30
    x1: float = 0.93
    y1: float = 0.36

    def pixels(self, size: tuple[int, int]) -> tuple[int, int, int, int]:
        w, h = size
        return round(self.x0 * w), round(self.y0 * h), round(self.x1 * w), round(self.y1 * h)

    def center_normalized(self) -> tuple[float, float]:
        """Centre in the 0-1000 coordinates the model and the affine use."""
        return (self.x0 + self.x1) * 500.0, (self.y0 + self.y1) * 500.0


MARKER = Marker()


def make_page(size: tuple[int, int] = A4_150DPI, seed: int = 7, *, marker: Marker | None = MARKER) -> Image.Image:
    """An upright page: ~40 lines of word-like blocks, a heading, and the marker. White background, black ink, mode L."""
    rng = random.Random(seed)
    width, height = size
    page = Image.new("L", size, 255)
    draw = ImageDraw.Draw(page)
    left, right = round(0.08 * width), round(0.78 * width)  # the right margin stays empty (the marker lives there)
    draw.rectangle((left, round(0.05 * height), left + round(0.4 * width), round(0.05 * height) + 34), fill=0)  # heading
    line_height = max(18, round(height / 62))
    y = round(0.12 * height)
    while y < round(0.92 * height):
        x = left
        while x < right - 40:
            word = rng.randint(30, 110)
            draw.rectangle((x, y, min(x + word, right), y + line_height // 2), fill=0)
            x += word + rng.randint(10, 22)
        y += line_height + rng.randint(6, 12)
    if marker is not None:
        draw.rectangle(marker.pixels(size), fill=0)
    return page


def skew(page: Image.Image, degrees: float) -> Image.Image:
    """Scan the page with its text tilted DOWNWARD to the right by ``degrees`` (positive), on a canvas of the same size.

    PIL rotates counter-clockwise for a positive angle, so the clockwise tilt of a positive skew is a negative rotation.
    """
    return page.rotate(-degrees, resample=Image.Resampling.BICUBIC, fillcolor=255)


def rotate_sideways(page: Image.Image, clockwise_degrees: int) -> Image.Image:
    """The page as a scanner that was fed it sideways delivered it (90, 180 or 270 degrees clockwise)."""
    transpose = {
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }[clockwise_degrees]
    return page.transpose(transpose)


def noisy(page: Image.Image, sigma: float = 18.0, seed: int = 3) -> Image.Image:
    rng = np.random.default_rng(seed)
    grain = rng.normal(0.0, sigma, size=(page.height, page.width))
    return Image.fromarray(np.clip(np.asarray(page, dtype=np.float32) + grain, 0, 255).astype(np.uint8), "L")


def blurred(page: Image.Image, radius: float = 1.6) -> Image.Image:
    return page.filter(ImageFilter.GaussianBlur(radius))


def faded(page: Image.Image, floor: int = 110) -> Image.Image:
    """Low contrast: black ink printed as mid-grey, paper not quite white."""
    return page.point(lambda value: floor + value * (235 - floor) // 255)


def jpeg(page: Image.Image, quality: int = 22) -> Image.Image:
    buffer = io.BytesIO()
    page.save(buffer, format="JPEG", quality=quality)
    return Image.open(io.BytesIO(buffer.getvalue())).convert("L")


def unevenly_lit(page: Image.Image, strength: float = 0.45) -> Image.Image:
    """A lighting gradient across the page: the left edge darker than the right (a phone photo, a curled page)."""
    gradient = np.linspace(1.0 - strength, 1.0, page.width, dtype=np.float32)[None, :]
    return Image.fromarray(np.clip(np.asarray(page, dtype=np.float32) * gradient, 0, 255).astype(np.uint8), "L")


DEGRADATIONS = {
    "clean": lambda page: page,
    "noise": noisy,
    "blur": blurred,
    "faded": faded,
    "jpeg": jpeg,
    "uneven light": unevenly_lit,
}


def png(page: Image.Image) -> bytes:
    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    return buffer.getvalue()


def pdf(page: Image.Image, dpi: int = 200) -> bytes:
    """A one-page image-only PDF of the page (what a scanner delivers)."""
    buffer = io.BytesIO()
    page.convert("RGB").save(buffer, format="PDF", resolution=dpi)
    return buffer.getvalue()


def find_marker(processed: Image.Image, expected: Marker = MARKER, margin: float = 0.10) -> tuple[float, float]:
    """The centre (normalized 0-1000) of the marker block in ``processed``: the largest solid dark blob in a window around
    where the marker should be (text blocks are small and thin beside it, so a tilted page's stray text cannot be mistaken
    for it)."""
    import cv2

    width, height = processed.size
    x0, y0, x1, y1 = expected.pixels(processed.size)
    left, top = max(0, x0 - round(margin * width)), max(0, y0 - round(margin * height))
    right, bottom = min(width, x1 + round(margin * width)), min(height, y1 + round(margin * height))
    window = (np.asarray(processed.convert("L").crop((left, top, right, bottom))) < 128).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(window, connectivity=8)
    if count < 2:
        raise AssertionError("the marker is not in the processed page where it was expected")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    bx, by, bw, bh = (int(stats[biggest, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    return (left + bx + bw / 2.0) / width * 1000.0, (top + by + bh / 2.0) / height * 1000.0
