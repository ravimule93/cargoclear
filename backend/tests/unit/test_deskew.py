"""Deskew, orientation and image modes on a deterministic corpus of degraded scans (tests/support/scans.py).

What must hold: the skew estimator finds the tilt through noise, blur, fading, JPEG artifacts and uneven light; the deskew
straightens the page; and the affine the preprocessing records carries a point of the PROCESSED page back to where it is on
the ORIGINAL page, including on a non-square page and on a page that was also scanned sideways. That last property is what
lets the viewer draw the model's evidence boxes on the original document after the page was straightened.
"""

from __future__ import annotations

import io
import math
import shutil

import numpy as np
import pytest
from PIL import Image

from app.core.config import settings
from app.services import preprocess
from tests.support import scans

needs_poppler = pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler is not installed")

ANGLES = (-8.0, -3.0, -0.8, 0.8, 3.0, 8.0)


def upright(page_seed: int = 7) -> Image.Image:
    return scans.make_page(seed=page_seed)


# ---------------------------------------------------------------------------
# estimating the skew
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("degradation", ["clean", "noise", "blur", "jpeg", "uneven light", "faded"])
def test_the_skew_is_found_through_every_degradation(degradation) -> None:
    errors = []
    for angle in (-6.0, -2.0, 1.5, 5.0):
        page = scans.DEGRADATIONS[degradation](scans.skew(upright(), angle))
        errors.append(abs(preprocess.estimate_skew_angle(scans.png(page)) - angle))
    assert max(errors) <= 0.35, f"{degradation}: worst error {max(errors):.2f} degrees ({errors})"


def test_the_skew_is_found_to_the_nearest_tenth_of_a_degree_on_the_synthetic_corpus() -> None:
    """The precision the docs may state: the search ends on a 0.1 degree grid, so the error is at most 0.05 degrees (plus slack).

    Angles are OFF the grid on purpose (a sweep on multiples of 0.5 would score a perfect zero). Synthetic pages only: how close
    it is on a real scan is not measured.
    """
    worst = 0.0
    for degradation, make in scans.DEGRADATIONS.items():
        for angle in (-7.43, -2.17, 0.62, 3.91, 9.26):
            estimate = preprocess.estimate_skew_angle(scans.png(make(scans.skew(upright(), angle))))
            worst = max(worst, abs(estimate - angle))
            assert abs(estimate - angle) <= 0.06, f"{degradation} at {angle}: estimated {estimate}"
    assert worst > 0.0, "an off-grid angle cannot be matched exactly: a zero error would mean the sweep landed on the grid"


def test_a_positive_skew_means_text_sloping_downward_to_the_right() -> None:
    page = scans.skew(upright(), 4.0)
    assert preprocess.estimate_skew_angle(scans.png(page)) == pytest.approx(4.0, abs=0.3)
    assert preprocess.estimate_skew_angle(scans.png(scans.skew(upright(), -4.0))) == pytest.approx(-4.0, abs=0.3)


def test_a_straight_blank_or_unreadable_page_has_no_skew() -> None:
    assert abs(preprocess.estimate_skew_angle(scans.png(upright()))) <= 0.2
    assert preprocess.estimate_skew_angle(scans.png(Image.new("L", (800, 1000), 255))) == 0.0, "nothing to measure"
    assert preprocess.estimate_skew_angle(scans.png(Image.new("L", (800, 1000), 0))) == 0.0, "a black page has no lines either"
    assert preprocess.estimate_skew_angle(b"not an image") == 0.0
    assert preprocess.estimate_skew_angle(b"") == 0.0


def test_a_page_with_no_line_structure_is_left_alone() -> None:
    rng = np.random.default_rng(5)
    noise = Image.fromarray(rng.integers(0, 255, size=(900, 700), dtype=np.uint8), "L")
    assert preprocess.estimate_skew_angle(scans.png(noise)) == 0.0, "no angle straightens noise better than another"


# ---------------------------------------------------------------------------
# orientation: sideways pages are turned, crooked ones are not mistaken for sideways ones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("degradation", list(scans.DEGRADATIONS))
def test_orientation_through_every_degradation_and_with_a_crooked_scan(degradation) -> None:
    degrade = scans.DEGRADATIONS[degradation]
    cases = [
        (0, 0.0, 0), (0, 5.0, 0), (0, -9.0, 0),          # upright, crooked either way: left as it is
        (90, 4.0, 270), (270, -6.0, 90), (90, 0.0, 270),  # fed sideways, with and without a tilt: turned back
    ]
    results = {}
    for sideways, tilt, expected in cases:
        scan = scans.skew(upright(), tilt)
        scan = scans.rotate_sideways(scan, sideways) if sideways else scan
        results[(sideways, tilt)] = (preprocess.detect_orientation_pass(scans.png(degrade(scan))), expected)
    wrong = {case: got for case, (got, expected) in results.items() if got != expected}
    assert not wrong, f"{degradation}: {wrong}"


def test_a_page_upside_down_is_only_turned_when_it_is_clearly_bottom_heavy() -> None:
    """Without OCR, 'upright' and 'upside down' differ only in where the ink sits. A page that is top-heavy either way is
    left as scanned (a wrong turn costs more than none); a clearly bottom-heavy one, upside down, is turned."""
    assert preprocess.detect_orientation_pass(scans.png(scans.rotate_sideways(upright(), 180))) == 0

    letterhead = Image.new("L", (900, 1200), 255)
    from PIL import ImageDraw

    draw = ImageDraw.Draw(letterhead)
    for y in range(80, 260, 18):  # all the text in the top fifth: a letter with a short body
        draw.rectangle((60, y, 840, y + 8), fill=0)
    assert preprocess.detect_orientation_pass(scans.png(letterhead)) == 0
    assert preprocess.detect_orientation_pass(scans.png(scans.rotate_sideways(letterhead, 180))) == 180


# ---------------------------------------------------------------------------
# deskewing, and the affine that undoes it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("angle", ANGLES)
def test_deskew_straightens_the_page(angle) -> None:
    skewed = scans.skew(upright(), angle)
    detected = preprocess.estimate_skew_angle(scans.png(skewed))
    straightened = preprocess.deskew_image(skewed, detected)

    assert straightened.size == skewed.size, "the canvas does not change"
    residual = preprocess.estimate_skew_angle(scans.png(straightened))
    assert abs(residual) <= 0.3, f"{angle}: {detected} detected, {residual} left"


def test_deskew_is_the_counter_clockwise_rotation_it_says_it_is() -> None:
    page = upright()
    ours = np.asarray(preprocess.deskew_image(page, 3.0), dtype=np.float32)
    reference = np.asarray(page.rotate(3.0, resample=Image.Resampling.BICUBIC, fillcolor=255), dtype=np.float32)
    assert float(np.abs(ours - reference).mean()) < 1.0


def test_the_deskew_affine_is_aspect_aware_and_maps_the_page_centre_to_itself() -> None:
    matrix = preprocess.deskew_to_source_affine(5.0, 1240, 1754)
    assert preprocess.apply_affine(matrix, 500.0, 500.0) == pytest.approx((500.0, 500.0), abs=1e-6), "rotation about the centre"
    # on a square page the matrix is a plain rotation; on a rectangular one it is not (the shear terms carry H/W and W/H)
    square = preprocess.deskew_to_source_affine(5.0, 1000, 1000)
    assert square[0][1] == pytest.approx(-square[1][0], abs=1e-9)
    assert matrix[0][1] != pytest.approx(-matrix[1][0], abs=1e-3)
    assert matrix[0][1] * matrix[1][0] == pytest.approx(-math.sin(math.radians(5.0)) ** 2, abs=1e-9), "still a rotation, conjugated by the page's aspect"
    assert matrix[2] == [0.0, 0.0, 1.0]


def test_composing_affines_is_matrix_multiplication() -> None:
    rotation = preprocess._processed_to_source_affine(90)
    deskew = preprocess.deskew_to_source_affine(4.0, 1754, 1240)
    composed = preprocess.compose_affines([[float(v) for v in row] for row in rotation], deskew)
    for point in ((100.0, 200.0), (900.0, 50.0), (500.0, 500.0)):
        stepwise = preprocess.apply_affine([[float(v) for v in row] for row in rotation], *preprocess.apply_affine(deskew, *point))
        assert preprocess.apply_affine(composed, *point) == pytest.approx(stepwise, abs=1e-6)
    assert all(value == 0.0 or str(value)[0] != "-" or value != 0 for row in composed for value in row), "no negative zeros"


# ---------------------------------------------------------------------------
# the round trip: a point of the processed page lands where it was on the original page
# ---------------------------------------------------------------------------


def expected_marker_on_skewed_source(angle: float) -> tuple[float, float]:
    """Where the marker's centre is on the page AFTER it was scanned with a tilt of ``angle`` (analytic: PIL rotates the
    content counter-clockwise by -angle about the centre, y down)."""
    width, height = scans.A4_150DPI
    mx, my = scans.MARKER.center_normalized()
    px, py = mx / 1000 * width, my / 1000 * height
    cx, cy = width / 2, height / 2
    phi = math.radians(-angle)
    x = cx + math.cos(phi) * (px - cx) + math.sin(phi) * (py - cy)
    y = cy - math.sin(phi) * (px - cx) + math.cos(phi) * (py - cy)
    return x / width * 1000, y / height * 1000


@pytest.mark.parametrize("angle", ANGLES)
@pytest.mark.parametrize("degradation", ["clean", "noise", "uneven light"])
def test_a_marker_found_on_the_straightened_page_maps_back_onto_the_skewed_original(angle, degradation) -> None:
    skewed = scans.DEGRADATIONS[degradation](scans.skew(upright(), angle))
    detected = preprocess.estimate_skew_angle(scans.png(skewed))
    processed = preprocess.deskew_image(skewed, detected)

    on_processed = scans.find_marker(processed)
    matrix = preprocess.deskew_to_source_affine(detected, *processed.size)
    mapped = preprocess.apply_affine(matrix, *on_processed)

    expected = expected_marker_on_skewed_source(angle)
    assert mapped == pytest.approx(expected, abs=4.0), f"{angle} deg, {degradation}: {mapped} vs {expected} (normalized units; 4 = 0.4 % of the page)"


def test_without_the_aspect_term_the_map_back_would_be_wrong_on_a_rectangular_page() -> None:
    """Why the affine is conjugated with the page size: the naive 'rotate in normalized units' misses by a wide margin."""
    angle = 8.0
    skewed = scans.skew(upright(), angle)
    processed = preprocess.deskew_image(skewed, preprocess.estimate_skew_angle(scans.png(skewed)))
    on_processed = scans.find_marker(processed)
    phi = math.radians(angle)
    naive = (
        500 + math.cos(phi) * (on_processed[0] - 500) - math.sin(phi) * (on_processed[1] - 500),
        500 + math.sin(phi) * (on_processed[0] - 500) + math.cos(phi) * (on_processed[1] - 500),
    )
    expected = expected_marker_on_skewed_source(angle)
    assert math.dist(naive, expected) > 12, "the aspect-blind map misses by three times the tolerance: the term is not decoration"


# ---------------------------------------------------------------------------
# through the real preprocessing (PDF in, pages and transform metadata out)
# ---------------------------------------------------------------------------


def run_pdf(page: Image.Image, **settings_overrides) -> dict:
    import asyncio

    monkey = pytest.MonkeyPatch()
    for name, value in settings_overrides.items():
        monkey.setattr(settings, name, value)
    try:
        return asyncio.run(preprocess.run({"raw_bytes": scans.pdf(page), "document_id": "doc-1"}))
    finally:
        monkey.undo()


def processed_image(result: dict) -> Image.Image:
    return Image.open(io.BytesIO(result["processed_pages"][0]["payload"]))


@needs_poppler
def test_with_deskew_on_the_recorded_affine_carries_a_processed_point_back_to_the_scan() -> None:
    angle = 5.0
    skewed = scans.skew(upright(), angle)
    result = run_pdf(skewed, preprocess_deskew=True)
    [meta] = result["transform_meta"]

    assert meta["deskew_applied"] is True and meta["deskew_deg"] == pytest.approx(angle, abs=0.3) and meta["deskew_skipped"] is None
    assert meta["rotation"] == 0 and meta["image_mode"] == "bw"
    on_processed = scans.find_marker(processed_image(result))
    mapped = preprocess.apply_affine(meta["processed_to_source_affine"], *on_processed)
    assert mapped == pytest.approx(expected_marker_on_skewed_source(angle), abs=5.0)


@needs_poppler
def test_with_deskew_off_the_page_is_untouched_and_the_skew_is_only_reported() -> None:
    result = run_pdf(scans.skew(upright(), 5.0), preprocess_deskew=False)
    [meta] = result["transform_meta"]
    assert (meta["deskew_applied"], meta["deskew_deg"], meta["deskew_skipped"]) == (False, 0.0, "disabled")
    assert meta["deskew_detected_deg"] == pytest.approx(5.0, abs=0.3), "measured and recorded, not applied"
    assert meta["processed_to_source_affine"] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert scans.find_marker(processed_image(result)) == pytest.approx(
        preprocess.apply_affine([[1, 0, 0], [0, 1, 0], [0, 0, 1]], *expected_marker_on_skewed_source(5.0)), abs=5.0
    ), "the model sees the page exactly as scanned"


@needs_poppler
@pytest.mark.parametrize(
    ("angle", "skipped"),
    [(0.1, "below_threshold"), (14.0, "above_limit")],
)
def test_a_skew_outside_the_trusted_range_is_not_corrected(angle, skipped) -> None:
    result = run_pdf(scans.skew(upright(), angle), preprocess_deskew=True)
    [meta] = result["transform_meta"]
    assert meta["deskew_applied"] is False and meta["deskew_skipped"] == skipped and meta["deskew_deg"] == 0.0
    assert meta["processed_to_source_affine"] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


@needs_poppler
@pytest.mark.parametrize("sideways", [90, 270])
def test_a_page_scanned_sideways_and_tilted_is_normalized_straightened_and_mapped_back(sideways) -> None:
    angle = 4.0
    scan = scans.rotate_sideways(scans.skew(upright(), angle), sideways)
    result = run_pdf(scan, preprocess_deskew=True)
    [meta] = result["transform_meta"]

    assert meta["rotation"] == (360 - sideways) % 360 and meta["deskew_applied"] is True
    on_processed = scans.find_marker(processed_image(result))
    mapped = preprocess.apply_affine(meta["processed_to_source_affine"], *on_processed)

    ex, ey = expected_marker_on_skewed_source(angle)
    expected = {90: (1000 - ey, ex), 270: (ey, 1000 - ex)}[sideways]  # the scanner's rotation, by hand
    assert mapped == pytest.approx(expected, abs=6.0), f"{sideways}: {mapped} vs {expected}"


# ---------------------------------------------------------------------------
# what the model is shown: 1-bit or grayscale
# ---------------------------------------------------------------------------


@needs_poppler
def test_the_image_mode_decides_what_the_model_sees_and_is_recorded() -> None:
    page = scans.blurred(upright())  # blur leaves intermediate greys: the difference between the modes
    bw = run_pdf(page, page_image_mode="bw")
    gray = run_pdf(page, page_image_mode="gray")

    bw_image, gray_image = processed_image(bw), processed_image(gray)
    assert bw_image.mode == "1" and set(np.unique(np.asarray(bw_image.convert("L")))) <= {0, 255}
    assert gray_image.mode == "L" and len(np.unique(np.asarray(gray_image))) > 20, "real greys survive in the grayscale input"
    assert (bw["transform_meta"][0]["image_mode"], gray["transform_meta"][0]["image_mode"]) == ("bw", "gray")
    assert gray_image.size == bw_image.size, "same geometry either way: the boxes mean the same"


def test_defaults_keep_the_original_behaviour() -> None:
    assert settings.page_image_mode == "bw" and settings.preprocess_deskew is False
    assert settings.deskew_min_degrees == 0.3 and settings.deskew_max_degrees == 10.0 and settings.persist_processed_pages is True


# ---------------------------------------------------------------------------
# the contract with the frontend: these vectors are the same numbers as in frontend/tests/transform-bbox.unit.spec.ts
# ---------------------------------------------------------------------------

GOLDEN_DESKEW_5 = [[0.996194698, -0.123283204, 63.544252881], [0.061615234, 0.996194698, -28.904966209], [0.0, 0.0, 1.0]]
GOLDEN_ROTATED_270_DESKEW_4 = [[-0.049314725, -0.99756405, 1023.439387571], [0.99756405, -0.098671657, 50.553803478], [0.0, 0.0, 1.0]]


def test_the_recorded_matrices_are_the_ones_the_frontend_is_tested_against() -> None:
    deskew = preprocess.deskew_to_source_affine(5.0, 1240, 1754)
    assert [[round(v, 9) for v in row] for row in deskew] == GOLDEN_DESKEW_5

    rotation = [[float(v) for v in row] for row in preprocess._processed_to_source_affine(270)]
    composed = preprocess.compose_affines(rotation, preprocess.deskew_to_source_affine(4.0, 1240, 1754))
    assert composed == GOLDEN_ROTATED_270_DESKEW_4

    assert preprocess.apply_affine(GOLDEN_DESKEW_5, 100.0, 200.0) == pytest.approx((138.507082, 176.495497), abs=1e-5)
    assert preprocess.apply_affine(GOLDEN_ROTATED_270_DESKEW_4, 900.0, 50.0) == pytest.approx((929.177933, 943.427866), abs=1e-5)
