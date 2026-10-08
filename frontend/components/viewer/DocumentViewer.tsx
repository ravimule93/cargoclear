"use client";

import { useEffect, useRef, useState } from "react";
import { DocumentRecord, BBox } from "@/lib/types";
import { BBoxLayer, HighlightBox } from "./BBoxLayer";
import { mapBBoxToCanvas } from "@/lib/bbox";

interface EvidenceRef {
  id: string;
  document_id: string;
  page: number;
  bbox: BBox;
  severity: "PASS" | "WARN" | "MATERIAL" | "INFO";
  label?: string;
}

interface DocumentViewerProps {
  documents: DocumentRecord[];
  highlights?: EvidenceRef[];
}

export function DocumentViewer({ documents, highlights = [] }: DocumentViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [page, setPage] = useState(1);
  const [dims, setDims] = useState({ w: 600, h: 800 });
  const [activeDoc, setActiveDoc] = useState(documents[0]?.document_id || "");

  useEffect(() => {
    if (documents[0] && !activeDoc) {
      setActiveDoc(documents[0].document_id);
    }
  }, [documents, activeDoc]);

  // Canvas drawing placeholder for skeleton until pdfjs-dist worker is mounted
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = dims.w;
    canvas.height = dims.h;

    // Draw document page placeholder
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, dims.w, dims.h);

    ctx.strokeStyle = "#e2e8f0";
    ctx.lineWidth = 1;
    ctx.strokeRect(0, 0, dims.w, dims.h);

    ctx.fillStyle = "#64748b";
    ctx.font = "14px monospace";
    ctx.fillText(`[Document Viewer Preview]`, 40, 50);
    ctx.fillText(`File: ${documents.find((d) => d.document_id === activeDoc)?.filename || activeDoc}`, 40, 80);
    ctx.fillText(`Page: ${page} of 1`, 40, 110);
    ctx.fillText(`Status: Ready for PDF worker mount`, 40, 140);
  }, [activeDoc, page, dims, documents]);

  const activeBoxes: HighlightBox[] = highlights
    .filter((h) => h.document_id === activeDoc && h.page === page)
    .map((h) => ({
      ...mapBBoxToCanvas(h.bbox, dims),
      id: h.id,
      severity: h.severity,
      label: h.label,
    }));

  return (
    <div className="flex flex-col items-center justify-start p-4 h-full">
      <div className="flex items-center gap-2 mb-3 bg-[var(--cc-surface)] px-3 py-1.5 rounded-[var(--cc-radius)] border border-[var(--cc-border)] text-xs text-[var(--cc-text-muted)]">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          className="px-2 py-0.5 rounded border border-[var(--cc-border)] disabled:opacity-40 cursor-pointer"
        >
          Previous
        </button>
        <span>Page {page}</span>
        <button
          type="button"
          onClick={() => setPage((p) => p + 1)}
          className="px-2 py-0.5 rounded border border-[var(--cc-border)] cursor-pointer"
        >
          Next
        </button>
      </div>

      <div className="relative mx-auto w-fit shadow-[var(--cc-shadow-1)] rounded-[var(--cc-radius)] overflow-hidden">
        <canvas
          ref={canvasRef}
          aria-label={`Page ${page} of document ${activeDoc}`}
          className="block bg-white"
        />
        <BBoxLayer width={dims.w} height={dims.h} boxes={activeBoxes} />
      </div>
    </div>
  );
}
