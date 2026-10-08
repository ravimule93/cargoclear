"use client";

import { useState } from "react";

export interface HighlightBox {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  severity: "PASS" | "WARN" | "MATERIAL" | "INFO";
  label?: string;
}

interface BBoxLayerProps {
  width: number;
  height: number;
  boxes: HighlightBox[];
}

const SEVERITY_TOKEN: Record<HighlightBox["severity"], string> = {
  PASS: "var(--cc-ok-bd)",
  WARN: "var(--cc-warn-bd)",
  MATERIAL: "var(--cc-err-bd)",
  INFO: "var(--cc-info-bd)",
};

export function BBoxLayer({ width, height, boxes }: BBoxLayerProps) {
  const [hovered, setHovered] = useState<string | null>(null);

  if (width === 0 || height === 0) return null;

  return (
    <div
      className="pointer-events-none absolute inset-0"
      role="group"
      aria-label={`${boxes.length} evidence highlights on this page`}
    >
      {boxes.map((b) => {
        const color = SEVERITY_TOKEN[b.severity] || "var(--cc-info-bd)";
        const active = hovered === b.id;

        return (
          <button
            key={b.id}
            type="button"
            className="pointer-events-auto absolute transition-opacity cursor-pointer focus:outline-none"
            style={{
              left: `${b.x}px`,
              top: `${b.y}px`,
              width: `${b.w}px`,
              height: `${b.h}px`,
              outline: `${active ? 3 : 2}px solid ${color}`,
              outlineOffset: 1,
              background: active ? `color-mix(in srgb, ${color} 12%, transparent)` : "transparent",
              borderRadius: 4,
            }}
            onMouseEnter={() => setHovered(b.id)}
            onMouseLeave={() => setHovered(null)}
            onFocus={() => setHovered(b.id)}
            onBlur={() => setHovered(null)}
            aria-label={`Evidence highlight: ${b.label ?? b.id}`}
          />
        );
      })}
    </div>
  );
}
