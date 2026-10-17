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
  /** The assessment on screen: "What the model saw" is the page image THAT assessment's extraction was shown (latest when absent). */
  iteration?: number | null;
  /** Whether the viewer tab is active in compact mode */
  isVisible?: boolean;
}

type LoadState = "idle" | "loading" | "ready" | "error";
type TransformMetadataState =
  | { status: "idle" | "loading" | "missing" | "error" }
  | { status: "ready"; data: TransformMetadataResponse };

type ZoomMode = "fit-width" | "fit-page" | "custom";

const WORKER_SRC = "/pdf.worker.min.mjs";

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : "Unknown error";
}

function isCancellation(err: unknown): boolean {
  return (
    err instanceof Error &&
    (err.name === "RenderingCancelledException" || err.message.includes("cancelled"))
  );
}

export function DocumentViewer({
  bundleId,
  documents,
  activeDocumentId,
  highlights = [],
  iteration = null,
  isVisible = true,
}: DocumentViewerProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 });
  const [zoomMode, setZoomMode] = useState<ZoomMode>("fit-width");
  const [customScale, setCustomScale] = useState(1.0);
  const [appliedScale, setAppliedScale] = useState(1.0);

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

    if (!activeDocument?.transform_meta_uri) {
      setTransformMetadata({ status: "missing" });
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
  }, [bundleId, activeDocumentId, activeDocument?.transform_meta_uri]);

  // Robust container measurement: updates on mount, resize, and tab visibility changes
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;

    let rafId: number;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      const w = Math.floor(rect.width);
      const h = Math.floor(rect.height);
      if (w > 0) {
        setContainerSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
      } else {
        rafId = requestAnimationFrame(measure);
      }
    };

    measure();

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        const w = Math.floor(entry.contentRect.width);
        const h = Math.floor(entry.contentRect.height);
        if (w > 0) {
          setContainerSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
        }
      }
    });
    observer.observe(el);

    window.addEventListener("resize", measure);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      cancelAnimationFrame(rafId);
    };
  }, [isVisible]);

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
      void loading.task?.destroy();
    };
  }, [bundleId, activeDocumentId]);

  // Render current page: computes scale, applies devicePixelRatio, and renders onto canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!pdf || !canvas || containerSize.w <= 0) return;

    let cancelled = false;
    const rendering: { task: RenderTask | null } = { task: null };

    // Debounce rendering slightly to avoid thrashing during smooth window resizes
    const timer = setTimeout(async () => {
      try {
        const pdfPage = await pdf.getPage(page);
        if (cancelled) return;

        const baseViewport = pdfPage.getViewport({ scale: 1 });
        const padX = 24;
        const padY = 24;
        const availW = Math.max(260, containerSize.w - padX);
        const availH = containerSize.h > 100 ? Math.max(260, containerSize.h - padY) : 800;

        let scale: number;
        if (zoomMode === "fit-page") {
          scale = Math.max(0.3, Math.min(availW / baseViewport.width, availH / baseViewport.height));
        } else if (zoomMode === "custom") {
          scale = customScale;
        } else {
          // "fit-width" (default)
          scale = Math.max(0.3, availW / baseViewport.width);
        }

        setAppliedScale(scale);

        const viewport = pdfPage.getViewport({ scale });
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
    }, 40);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      rendering.task?.cancel();
    };
  }, [pdf, page, containerSize.w, containerSize.h, zoomMode, customScale]);

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

  // What the model was shown for this page (when the page image was kept), and whether the page was straightened for it
  const pageTransform =
    transformMetadata.status === "ready"
      ? transformMetadata.data.transform_meta.find((t) => (t.source_page ?? t.page) === page)
      : undefined;
  const modelView = pageTransform?.processed_uri
    ? `/api/proxy/bundles/${encodeURIComponent(bundleId)}/documents/${encodeURIComponent(activeDocumentId ?? "")}/pages/${page}${
        iteration ? `?iteration=${iteration}` : ""
      }`
    : null;

  const handleZoomIn = () => {
    setZoomMode("custom");
    setCustomScale(Math.min(3.0, Number((appliedScale + 0.15).toFixed(2))));
  };

  const handleZoomOut = () => {
    setZoomMode("custom");
    setCustomScale(Math.max(0.4, Number((appliedScale - 0.15).toFixed(2))));
  };

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-[var(--cc-surface-2)]">
      {/* Sticky Controls Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-1.5 sm:gap-2 px-3 py-1.5 bg-[var(--cc-surface)] border-b border-[var(--cc-border)] text-xs text-[var(--cc-text-muted)] shrink-0 z-10 w-full shadow-2xs">
        {/* Left: Pagination & Document Title */}
        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
          {hasDocument ? (
            <>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={loadState !== "ready" || page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="px-2 py-0.5 rounded border border-[var(--cc-border)] disabled:opacity-40 hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer"
                  title="Previous page"
                >
                  ◀
                </button>
                <span aria-live="polite" className="font-medium font-mono text-[11px] px-1">
                  {loadState === "ready" ? `${page} / ${numPages}` : "- / -"}
                </span>
                <button
                  type="button"
                  disabled={loadState !== "ready" || page >= numPages}
                  onClick={() => setPage((p) => Math.min(numPages, p + 1))}
                  className="px-2 py-0.5 rounded border border-[var(--cc-border)] disabled:opacity-40 hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer"
                  title="Next page"
                >
                  ▶
                </button>
              </div>

              <span
                className="pl-2 border-l border-[var(--cc-border)] font-mono font-medium text-[var(--cc-text)] truncate max-w-[8rem] sm:max-w-[12rem] md:max-w-[16rem]"
                title={filename}
              >
                {filename}
              </span>
            </>
          ) : (
            <span className="italic text-[11px] text-[var(--cc-text-muted)]">
              No document selected
            </span>
          )}
        </div>

        {/* Right: Responsive Zoom & View Mode Controls */}
        {hasDocument && (
          <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
            {/* Zoom Controls Cluster */}
            <div className="flex items-center bg-[var(--cc-surface-2)] p-0.5 rounded border border-[var(--cc-border)]">
              <button
                type="button"
                onClick={handleZoomOut}
                disabled={loadState !== "ready"}
                className="min-w-[24px] min-h-[24px] inline-flex items-center justify-center px-1.5 py-0.5 text-xs font-bold rounded hover:bg-[var(--cc-surface)] text-[var(--cc-text)] disabled:opacity-40 cursor-pointer"
                title="Zoom Out (−)"
              >
                −
              </button>
              <button
                type="button"
                onClick={() => setZoomMode("fit-width")}
                className="min-h-[24px] inline-flex items-center justify-center px-1.5 py-0.5 font-mono text-[10px] text-[var(--cc-text-muted)] min-w-[3.2rem] text-center hover:text-[var(--cc-text)] cursor-pointer"
                title="Click to reset to Fit Width"
              >
                {zoomMode === "fit-width"
                  ? "Fit W"
                  : zoomMode === "fit-page"
                  ? "Fit P"
                  : `${Math.round(appliedScale * 100)}%`}
              </button>
              <button
                type="button"
                onClick={handleZoomIn}
                disabled={loadState !== "ready"}
                className="min-w-[24px] min-h-[24px] inline-flex items-center justify-center px-1.5 py-0.5 text-xs font-bold rounded hover:bg-[var(--cc-surface)] text-[var(--cc-text)] disabled:opacity-40 cursor-pointer"
                title="Zoom In (+)"
              >
                +
              </button>
            </div>

            {/* Quick Fit Mode Buttons */}
            <div className="hidden sm:flex items-center gap-1">
              <button
                type="button"
                onClick={() => setZoomMode("fit-width")}
                className={`px-1.5 py-0.5 text-[10px] font-medium rounded border transition-colors cursor-pointer ${
                  zoomMode === "fit-width"
                    ? "bg-[var(--cc-focus)] text-white border-[var(--cc-focus)] font-semibold"
                    : "border-[var(--cc-border)] hover:bg-[var(--cc-surface-2)] text-[var(--cc-text-muted)]"
                }`}
                title="Fit to width of viewer"
              >
                Fit Width
              </button>
              <button
                type="button"
                onClick={() => setZoomMode("fit-page")}
                className={`px-1.5 py-0.5 text-[10px] font-medium rounded border transition-colors cursor-pointer ${
                  zoomMode === "fit-page"
                    ? "bg-[var(--cc-focus)] text-white border-[var(--cc-focus)] font-semibold"
                    : "border-[var(--cc-border)] hover:bg-[var(--cc-surface-2)] text-[var(--cc-text-muted)]"
                }`}
                title="Fit entire page in view"
              >
                Fit Page
              </button>
            </div>

            {pageTransform?.deskew_applied && (
              <span
                data-testid="deskew-note"
                className="pl-2 border-l border-[var(--cc-border)] text-[10px] hidden sm:inline"
                title="The page was straightened before the model read it; evidence boxes are mapped back onto this original page."
              >
                straightened {pageTransform.deskew_deg?.toFixed(1)}°
              </span>
            )}

            {modelView && (
              <a
                data-testid="model-view-link"
                href={modelView}
                target="_blank"
                rel="noopener noreferrer"
                className="pl-2 border-l border-[var(--cc-border)] font-semibold text-[11px] text-[var(--cc-focus)] hover:underline whitespace-nowrap"
                title="The page image exactly as the extraction saw it (after orientation, straightening and the image mode)"
              >
                What the model saw
              </a>
            )}
          </div>
        )}
      </div>

      {/* Main Document Stage with 2D Scrollability */}
      <div
        ref={stageRef}
        className="w-full flex-1 overflow-auto flex justify-center items-start p-2 sm:p-4"
        tabIndex={0}
        aria-label={`Document viewer for ${filename}`}
      >
        {!hasDocument && (
          <div className="p-4 text-xs text-[var(--cc-text-muted)] italic text-center my-auto">
            No documents in this bundle yet. Use <strong>+ Add Document</strong> above to upload trade PDFs.
          </div>
        )}

        {hasDocument && loadState === "loading" && (
          <div role="status" className="text-xs text-[var(--cc-text-muted)] flex items-center gap-2 my-auto">
            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--cc-focus)] border-t-transparent" />
            <span>Rendering {filename}...</span>
          </div>
        )}

        {hasDocument && loadState === "error" && (
          <div role="alert" className="text-xs text-[var(--cc-err)] my-auto p-4 text-center">
            Could not display {filename}: {error}
          </div>
        )}

        {/* Scaled PDF Page Canvas Wrapper with BBox Overlay */}
        <div
          className="relative shadow-md rounded-[var(--cc-radius)] bg-white shrink-0 my-auto sm:my-0 transition-opacity duration-150"
          style={{
            width: `${cssSize.w}px`,
            height: `${cssSize.h}px`,
            display: hasDocument && loadState === "ready" ? "block" : "none",
          }}
        >
          <canvas
            ref={canvasRef}
            role="img"
            aria-label={`Page ${page} of ${numPages}: ${filename}`}
            className="block bg-white"
            style={{
              width: `${cssSize.w}px`,
              height: `${cssSize.h}px`,
            }}
          />
          <BBoxLayer width={cssSize.w} height={cssSize.h} boxes={boxes} />
        </div>
      </div>
    </div>
  );
}
