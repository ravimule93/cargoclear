import type { BBox, TransformMetadata } from "./types";

/**
 * Maps a normalized box emitted for a processed page back to the original PDF orientation.
 *
 * New metadata names the original page as `source_page`; older records use `page`. Artifact
 * identifiers and `split_offset` identify persisted split PDFs but never move source pages.
 * Normalized coordinates make raster dimensions irrelevant. Deskew remains a no-op until the
 * backend persists a reversible deskew matrix/crop geometry.
 */
export function mapProcessedBBoxToOriginal(
  bbox: BBox,
  transform: TransformMetadata | undefined
): BBox {
  const page = transform?.source_page ?? bbox.page;
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
