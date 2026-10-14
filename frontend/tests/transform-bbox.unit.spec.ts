import { expect, test } from "@playwright/test";
import { applyAffine, mapProcessedBBoxToOriginal } from "../lib/transform-bbox";
import type { BBox, TransformMetadata } from "../lib/types";

/**
 * Evidence boxes come back from the model in the coordinates of the PROCESSED page; the viewer draws them on the ORIGINAL
 * page. These vectors are the same numbers as backend/tests/unit/test_deskew.py (GOLDEN_*): if the backend's geometry
 * changes, both fail together.
 */
const GOLDEN_DESKEW_5 = [
  [0.996194698, -0.123283204, 63.544252881],
  [0.061615234, 0.996194698, -28.904966209],
  [0, 0, 1],
];
const GOLDEN_ROTATED_270_DESKEW_4 = [
  [-0.049314725, -0.99756405, 1023.439387571],
  [0.99756405, -0.098671657, 50.553803478],
  [0, 0, 1],
];

const meta = (extra: Partial<TransformMetadata>): TransformMetadata =>
  ({ page: 1, source_page: 1, document_id: "d", deskew_deg: 0, rotation: 0, split_offset: 0, width: 1240, height: 1754, ...extra }) as TransformMetadata;
const box = (xmin: number, ymin: number, xmax: number, ymax: number): BBox => ({ page: 1, xmin, ymin, xmax, ymax });

test.describe("applyAffine", () => {
  test("matches the backend's vectors", () => {
    const [x, y] = applyAffine(GOLDEN_DESKEW_5, 100, 200);
    expect(x).toBeCloseTo(138.507082, 4);
    expect(y).toBeCloseTo(176.495497, 4);
    const [rx, ry] = applyAffine(GOLDEN_ROTATED_270_DESKEW_4, 900, 50);
    expect(rx).toBeCloseTo(929.177933, 4);
    expect(ry).toBeCloseTo(943.427866, 4);
    expect(applyAffine(GOLDEN_DESKEW_5, 500, 500)[0]).toBeCloseTo(500, 4); // the page centre stays put
  });
});

test.describe("mapProcessedBBoxToOriginal", () => {
  test("a page that was only rotated maps by exact corner swaps (unchanged behaviour)", () => {
    const b = box(100, 200, 300, 260);
    expect(mapProcessedBBoxToOriginal(b, meta({ rotation: 0 }))).toEqual(b);
    expect(mapProcessedBBoxToOriginal(b, meta({ rotation: 90 }))).toEqual({ page: 1, xmin: 200, ymin: 700, xmax: 260, ymax: 900 });
    expect(mapProcessedBBoxToOriginal(b, meta({ rotation: 180 }))).toEqual({ page: 1, xmin: 700, ymin: 740, xmax: 900, ymax: 800 });
    expect(mapProcessedBBoxToOriginal(b, meta({ rotation: 270 }))).toEqual({ page: 1, xmin: 740, ymin: 100, xmax: 800, ymax: 300 });
    expect(mapProcessedBBoxToOriginal(b, undefined)).toEqual(b);
  });

  test("the recorded affine of a rotation-only page agrees with the corner swaps", () => {
    const rotation270 = [
      [0, -1, 1000],
      [1, 0, 0],
      [0, 0, 1],
    ];
    const b = box(100, 200, 300, 260);
    const swapped = mapProcessedBBoxToOriginal(b, meta({ rotation: 270 }));
    const viaAffine = mapProcessedBBoxToOriginal(b, meta({ rotation: 270, deskew_applied: true, processed_to_source_affine: rotation270 }));
    expect(viaAffine).toEqual(swapped);
  });

  test("a deskewed page maps its box through the recorded affine: the bounding box of the four corners", () => {
    const mapped = mapProcessedBBoxToOriginal(
      box(100, 200, 300, 260),
      meta({ deskew_applied: true, deskew_deg: 5, processed_to_source_affine: GOLDEN_DESKEW_5 })
    );
    // corners (100,200) (300,200) (100,260) (300,260) -> min/max of their images
    const corners = [
      [100, 200],
      [300, 200],
      [100, 260],
      [300, 260],
    ].map(([x, y]) => applyAffine(GOLDEN_DESKEW_5, x, y));
    expect(mapped.xmin).toBeCloseTo(Math.min(...corners.map((c) => c[0])), 6);
    expect(mapped.xmax).toBeCloseTo(Math.max(...corners.map((c) => c[0])), 6);
    expect(mapped.ymin).toBeCloseTo(Math.min(...corners.map((c) => c[1])), 6);
    expect(mapped.ymax).toBeCloseTo(Math.max(...corners.map((c) => c[1])), 6);
    expect(mapped.page).toBe(1);
  });

  test("a rotated AND deskewed page composes both", () => {
    const mapped = mapProcessedBBoxToOriginal(
      box(880, 40, 920, 60),
      meta({ rotation: 270, deskew_applied: true, deskew_deg: 4, processed_to_source_affine: GOLDEN_ROTATED_270_DESKEW_4 })
    );
    const [cx, cy] = applyAffine(GOLDEN_ROTATED_270_DESKEW_4, 900, 50); // the box centre
    expect((mapped.xmin + mapped.xmax) / 2).toBeCloseTo(cx, 1);
    expect((mapped.ymin + mapped.ymax) / 2).toBeCloseTo(cy, 1);
  });

  test("the result stays on the page", () => {
    const mapped = mapProcessedBBoxToOriginal(
      box(950, 950, 1000, 1000),
      meta({ deskew_applied: true, processed_to_source_affine: GOLDEN_DESKEW_5 })
    );
    for (const value of [mapped.xmin, mapped.ymin, mapped.xmax, mapped.ymax]) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1000);
    }
  });

  test("a record with no usable affine falls back to the rotation: older metadata keeps working", () => {
    const b = box(100, 200, 300, 260);
    expect(mapProcessedBBoxToOriginal(b, meta({ deskew_applied: true, rotation: 90, processed_to_source_affine: undefined }))).toEqual(
      mapProcessedBBoxToOriginal(b, meta({ rotation: 90 }))
    );
    expect(mapProcessedBBoxToOriginal(b, meta({ deskew_applied: true, rotation: 0, processed_to_source_affine: [[1, 0], [0, 1]] }))).toEqual(b);
    expect(mapProcessedBBoxToOriginal(b, meta({ deskew_applied: true, rotation: 0, processed_to_source_affine: [[NaN, 0, 0], [0, 1, 0], [0, 0, 1]] }))).toEqual(b);
  });

  test("a page whose deskew was not applied ignores the affine (identity or not)", () => {
    const b = box(100, 200, 300, 260);
    expect(mapProcessedBBoxToOriginal(b, meta({ deskew_applied: false, deskew_detected_deg: 3, processed_to_source_affine: GOLDEN_DESKEW_5 }))).toEqual(b);
  });
});
