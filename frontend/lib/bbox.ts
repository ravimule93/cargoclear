import type { BBox } from "./types";

export interface CanvasDimensions {
  w: number;
  h: number;
}

export interface CanvasRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface TransformMeta {
  deskew_deg: number;
  rotation: 0 | 90 | 180 | 270;
  split_offset: number;
}

/**
 * Maps normalized [0..1000] bounding box coordinates to viewport pixel space.
 */
export function mapBBoxToCanvas(b: BBox, canvas: CanvasDimensions): CanvasRect {
  const x = (b.xmin / 1000) * canvas.w;
  const y = (b.ymin / 1000) * canvas.h;
  const w = ((b.xmax - b.xmin) / 1000) * canvas.w;
  const h = ((b.ymax - b.ymin) / 1000) * canvas.h;

  return { x, y, w, h };
}

/**
 * Maps a bounding box on a preprocessed/rotated page back to the original PDF page.
 */
export function toOriginalPage(b: BBox, transform: TransformMeta): BBox {
  const rot = transform.rotation;
  let { ymin, xmin, ymax, xmax } = b;

  if (rot === 90) {
    [ymin, xmin, ymax, xmax] = [1000 - xmax, ymin, 1000 - xmin, ymax];
  } else if (rot === 180) {
    [ymin, xmin, ymax, xmax] = [1000 - ymax, 1000 - xmax, 1000 - ymin, 1000 - xmin];
  } else if (rot === 270) {
    [ymin, xmin, ymax, xmax] = [xmin, 1000 - ymax, xmax, 1000 - ymin];
  }

  return {
    ...b,
    ymin,
    xmin,
    ymax,
    xmax,
    page: b.page + transform.split_offset,
  };
}
