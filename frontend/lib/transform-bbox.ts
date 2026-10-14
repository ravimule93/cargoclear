import type { BBox, TransformMetadata } from "./types";

/**
 * Maps a normalized box emitted for a processed page back to the original PDF orientation.
 *
 * New metadata names the original page as `source_page`; older records use `page`. Artifact
 * identifiers and `split_offset` identify persisted split PDFs but never move source pages.
 * Normalized coordinates make raster dimensions irrelevant.
 *
 * A page that was only rotated (0/90/180/270) maps by exact corner swaps. A page that was also DESKEWED
 * (`deskew_applied`) maps through `processed_to_source_affine`, the reversible 3x3 the backend recorded (normalized 0-1000
 * coordinates, aspect-aware): the four corners of the box go through it and the result is their bounding box.
 * backend/tests/unit/test_deskew.py pins the same matrices and vectors as tests/transform-bbox.unit.spec.ts.
 */
type Affine = number[][];

function isAffine(value: unknown): value is Affine {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every((row) => Array.isArray(row) && row.length === 3 && row.every((n) => typeof n === "number" && Number.isFinite(n)))
  );
}

export function applyAffine(matrix: Affine, x: number, y: number): [number, number] {
  return [matrix[0][0] * x + matrix[0][1] * y + matrix[0][2], matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]];
}

const clamp = (value: number) => Math.min(1000, Math.max(0, value));

function mapThroughAffine(bbox: BBox, page: number, matrix: Affine): BBox {
  const corners = [
    applyAffine(matrix, bbox.xmin, bbox.ymin),
    applyAffine(matrix, bbox.xmax, bbox.ymin),
    applyAffine(matrix, bbox.xmin, bbox.ymax),
    applyAffine(matrix, bbox.xmax, bbox.ymax),
  ];
  const xs = corners.map(([x]) => x);
  const ys = corners.map(([, y]) => y);
  return {
    page,
    xmin: clamp(Math.min(...xs)),
    ymin: clamp(Math.min(...ys)),
    xmax: clamp(Math.max(...xs)),
    ymax: clamp(Math.max(...ys)),
  };
}

export function mapProcessedBBoxToOriginal(
  bbox: BBox,
  transform: TransformMetadata | undefined
): BBox {
  const page = transform?.source_page ?? bbox.page;
  if (transform?.deskew_applied && isAffine(transform.processed_to_source_affine)) {
    return mapThroughAffine(bbox, page, transform.processed_to_source_affine);
  }
  switch (transform?.rotation) {
    case 90:
      return {
        page,
        xmin: bbox.ymin,
        ymin: 1000 - bbox.xmax,
        xmax: bbox.ymax,
        ymax: 1000 - bbox.xmin,
      };
    case 180:
      return {
        page,
        xmin: 1000 - bbox.xmax,
        ymin: 1000 - bbox.ymax,
        xmax: 1000 - bbox.xmin,
        ymax: 1000 - bbox.ymin,
      };
    case 270:
      return {
        page,
        xmin: 1000 - bbox.ymax,
        ymin: bbox.xmin,
        xmax: 1000 - bbox.ymin,
        ymax: bbox.xmax,
      };
    default:
      return transform?.source_page ? { ...bbox, page } : bbox;
  }
}
