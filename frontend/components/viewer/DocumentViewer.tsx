"use client";

import { useEffect, useMemo, useRef, useState } from "react";
// Type-only imports are erased at compile time, so nothing from pdfjs-dist is evaluated during SSR.
// The library itself is imported lazily inside the effects below.
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import type { DocumentRecord, TransformMetadataResponse } from "@/lib/types";
import type { Highlight } from "@/lib/highlights";
import { api } from "@/lib/api";
import { mapBBoxToCanvas } from "@/lib/bbox";
import { mapProcessedBBoxToOriginal } from "@/lib/transform-bbox";
import { BBoxLayer, HighlightBox } from "./BBoxLayer";

interface DocumentViewerProps {
  bundleId: string;
  documents: DocumentRecord[];
  /** Controlled by the page: the DocumentRail selection drives which PDF is shown. */
  activeDocumentId: string | null;
  highlights?: Highlight[];
}

type LoadState = "idle" | "loading" | "ready" | "error";
type TransformMetadataState =
  | { status: "idle" | "loading" | "missing" | "error" }
  | { status: "ready"; data: TransformMetadataResponse };

const WORKER_SRC = "/pdf.worker.min.mjs";

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Unknown error";
}

function isCancellation(err: unknown): boolean {
  return err instanceof Error && err.name === "RenderingCancelledException";
}

export function DocumentViewer({
  bundleId,
  documents,
  activeDocumentId,
  highlights = [],
}: DocumentViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  const [containerWidth, setContainerWidth] = useState(0);
  // CSS-pixel size of the rendered page; the bbox overlay is laid out in these units.
  const [cssSize, setCssSize] = useState({ w: 0, h: 0 });
  const [transformMetadata, setTransformMetadata] = useState<TransformMetadataState>({ status: "idle" });

  const activeDocument = documents.find((d) => d.document_id === activeDocumentId) ?? null;

  // Transform metadata is optional: missing or unavailable metadata preserves the existing overlay coordinates.
  useEffect(() => {
    if (!activeDocumentId) {
      setTransformMetadata({ status: "idle" });
      return;
    }

    let cancelled = false;
    setTransformMetadata({ status: "loading" });

    api.getDocumentTransformMetadata(bundleId, activeDocumentId).then(
      (data) => {
        if (!cancelled) setTransformMetadata({ status: "ready", data });
      },
      (err: unknown) => {
        if (cancelled) return;
        const code = typeof err === "object" && err !== null && "code" in err ? err.code : undefined;
        setTransformMetadata({ status: code === "NOT_FOUND" ? "missing" : "error" });
      }
    );

    return () => {
      cancelled = true;
    };
  }, [bundleId, activeDocumentId]);

  // Fit-to-container width.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // Measure synchronously too: observer callbacks are only delivered while the page is rendering.
    setContainerWidth(Math.floor(el.getBoundingClientRect().width));
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      setContainerWidth(Math.floor(width));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Load the PDF whenever the active document changes.
  useEffect(() => {
    setPdf(null);
    setNumPages(0);
    setPage(1);
    setCssSize({ w: 0, h: 0 });
    setError(null);

    if (!activeDocumentId) {
      setLoadState("idle");
      return;
    }

    let cancelled = false;
    const loading: { task: PDFDocumentLoadingTask | null } = { task: null };
    setLoadState("loading");

    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = WORKER_SRC;
        if (cancelled) return;

        const url = `/api/proxy/bundles/${encodeURIComponent(bundleId)}/documents/${encodeURIComponent(activeDocumentId)}/file`;
        loading.task = pdfjs.getDocument({ url });
        const loaded = await loading.task.promise;
        if (cancelled) {
          void loaded.destroy();
          return;
        }
        setPdf(loaded);
        setNumPages(loaded.numPages);
        setLoadState("ready");
      } catch (err: unknown) {
        if (cancelled) return;
        setError(errorText(err));
        setLoadState("error");
      }
    })();

    return () => {
      cancelled = true;
      // Destroying the loading task also tears down the document and its worker transport.
      void loading.task?.destroy();
    };
  }, [bundleId, activeDocumentId]);

  // Render the current page at devicePixelRatio, fit to the container width.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!pdf || !canvas || containerWidth <= 0) return;

    let cancelled = false;
    const rendering: { task: RenderTask | null } = { task: null };

    (async () => {
      try {
        const pdfPage = await pdf.getPage(page);
        if (cancelled) return;

        const baseViewport = pdfPage.getViewport({ scale: 1 });
        const viewport = pdfPage.getViewport({ scale: containerWidth / baseViewport.width });
        const dpr = window.devicePixelRatio || 1;

        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        setCssSize({ w: viewport.width, h: viewport.height });

        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas 2D context is unavailable");

        rendering.task = pdfPage.render({
          canvasContext: context,
          viewport,
          transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
        });
        await rendering.task.promise;
      } catch (err: unknown) {
        if (cancelled || isCancellation(err)) return;
        setError(errorText(err));
        setLoadState("error");
      }
    })();

    return () => {
      cancelled = true;
      rendering.task?.cancel();
    };
  }, [pdf, page, containerWidth]);

  const boxes: HighlightBox[] = useMemo(
    () => {
      const transforms = transformMetadata.status === "ready" ? transformMetadata.data.transform_meta : [];
      return highlights
        .filter((h) => h.document_id === activeDocumentId && h.page === page)
        .map((h) => ({
          ...mapBBoxToCanvas(
            mapProcessedBBoxToOriginal(
              h.bbox,
              transforms.find((transform) => (transform.source_page ?? transform.page) === h.page)
            ),
            { w: cssSize.w, h: cssSize.h }
          ),
          id: h.id,
          severity: h.severity,
          label: h.label,
        }));
    },
    [highlights, activeDocumentId, page, cssSize, transformMetadata]
  );

  const hasDocument = documents.length > 0 && activeDocumentId !== null;
  const filename = activeDocument?.filename ?? activeDocumentId ?? "";

  return (
    <div className="flex flex-col items-center justify-start p-4 h-full">
      {!hasDocument && (
        <div className="p-2 text-xs text-[var(--cc-text-muted)] italic">
          No documents in this bundle yet. Use Add Document to upload a PDF.
        </div>
      )}

      {hasDocument && (
        <div className="flex items-center gap-2 mb-3 bg-[var(--cc-surface)] px-3 py-1.5 rounded-[var(--cc-radius)] border border-[var(--cc-border)] text-xs text-[var(--cc-text-muted)]">
          <button
            type="button"
            disabled={loadState !== "ready" || page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="px-2 py-0.5 rounded border border-[var(--cc-border)] disabled:opacity-40 cursor-pointer"
          >
            Previous
          </button>
          <span aria-live="polite">
            {loadState === "ready" ? `Page ${page} of ${numPages}` : "Page - of -"}
          </span>
          <button
            type="button"
            disabled={loadState !== "ready" || page >= numPages}
            onClick={() => setPage((p) => Math.min(numPages, p + 1))}
            className="px-2 py-0.5 rounded border border-[var(--cc-border)] disabled:opacity-40 cursor-pointer"
          >
            Next
          </button>
          <span
            className="pl-2 ml-1 border-l border-[var(--cc-border)] font-mono truncate max-w-[16rem]"
            title={filename}
          >
            {filename}
          </span>
        </div>
      )}

      {hasDocument && loadState === "loading" && (
        <div role="status" className="text-xs text-[var(--cc-text-muted)] mb-2">
          Loading document...
        </div>
      )}
      {hasDocument && loadState === "error" && (
        <div role="alert" className="text-xs text-[var(--cc-err)] mb-2">
          Could not display {filename}: {error}
        </div>
      )}

      {/* Always mounted: this container is measured for fit-to-width; the canvas sizes the page wrapper. */}
      <div ref={containerRef} className="w-full flex justify-center">
        <div
          className="relative shadow-[var(--cc-shadow-1)] rounded-[var(--cc-radius)] overflow-hidden"
          style={{ display: hasDocument && loadState === "ready" ? "block" : "none" }}
        >
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={`Page ${page} of ${numPages}: ${filename}`}
            className="block bg-white"
          />
          <BBoxLayer width={cssSize.w} height={cssSize.h} boxes={boxes} />
        </div>
      </div>
    </div>
  );
}
