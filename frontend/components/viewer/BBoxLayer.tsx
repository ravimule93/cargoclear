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
  selected?: boolean;
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
        const emphasized = active || b.selected;

        return (
          <div
            key={b.id}
            data-selected-evidence={b.selected ? "true" : undefined}
            className="pointer-events-auto absolute"
            style={{
              left: `${b.x}px`,
              top: `${b.y}px`,
              width: `${b.w}px`,
              height: `${b.h}px`,
              zIndex: active ? 5 : b.selected ? 4 : b.severity === "MATERIAL" ? 3 : b.severity === "WARN" ? 2 : 1,
            }}
          >
            <button
              type="button"
              className="cc-highlight w-full h-full transition-opacity cursor-pointer focus:outline-none"
              style={{
                outline: `${emphasized ? 3 : 2}px solid ${color}`,
                outlineOffset: 1,
                background: emphasized ? `color-mix(in srgb, ${color} 15%, transparent)` : "transparent",
                borderRadius: 4,
              }}
              onMouseEnter={() => setHovered(b.id)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(b.id)}
              onBlur={() => setHovered(null)}
              aria-label={`Evidence highlight: ${b.label ?? b.id}`}
            />

            {/* Visual tooltip on hover/focus */}
            {active && b.label && (
              <div
                role="tooltip"
                className="absolute left-1/2 -translate-x-1/2 bottom-[calc(100%+6px)] z-50 whitespace-normal max-w-xs bg-[var(--cc-surface)] text-[var(--cc-text)] text-[11px] p-2 rounded shadow-lg border border-[var(--cc-border)] pointer-events-none"
                style={{
                  borderLeft: `4px solid ${color}`,
                }}
              >
                <div className="font-bold flex items-center gap-1.5 mb-0.5">
                  <span className="uppercase text-[9px] tracking-wider px-1 py-0.2 rounded font-mono" style={{ backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)` }}>
                    {b.severity}
                  </span>
                  <span className="text-[10px] text-[var(--cc-text-muted)]">CITED EVIDENCE</span>
                </div>
                <p className="leading-tight text-[11px] font-medium text-[var(--cc-text)]">
                  {b.label}
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
