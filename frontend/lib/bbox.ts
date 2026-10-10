import { BBox } from "./types";

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

export function mapBBoxToCanvas(
  bbox: BBox,
  canvas: CanvasDimensions
): CanvasRect {
  const x = (bbox.xmin / 1000) * canvas.w;
  const y = (bbox.ymin / 1000) * canvas.h;
  const w = Math.max(0, ((bbox.xmax - bbox.xmin) / 1000) * canvas.w);
  const h = Math.max(0, ((bbox.ymax - bbox.ymin) / 1000) * canvas.h);
  return { x, y, w, h };
}
