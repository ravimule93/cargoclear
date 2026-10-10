"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import type { AppMode, AssessmentIteration } from "@/lib/types";
import type { StreamRunState } from "@/lib/hooks/useBundleStream";
import { CheckList } from "./CheckList";
import { MissingEvidenceCard } from "./MissingEvidenceCard";
import { UploadDropzone } from "../upload/UploadDropzone";
import { useAnnounce } from "../a11y/LiveRegion";

interface AssessmentPanelProps {
  /** null = the bundle has not been analysed yet */
  assessment: AssessmentIteration | null;
  bundleId: string;
  run?: StreamRunState | null;
  /** True from the moment a run was requested until the stream reports it finished. */
  isRunning?: boolean;
  appMode?: AppMode;
  onDocumentUploaded?: () => void;
}

const MTC_MISSING_ID = "ME-MILL_TEST_CERTIFICATE";

function RunProgress({ run }: { run?: StreamRunState | null }) {
  const live = run?.state === "RUNNING" || run?.state === "QUEUED";
  const progress = live ? (run?.progress ?? 0) : 0;
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="run-progress"
      className="bg-[var(--cc-surface-2)] p-2.5 rounded-[var(--cc-radius)] border border-[var(--cc-focus)] text-xs flex flex-col gap-1.5"
    >
      <div className="flex justify-between font-semibold text-[var(--cc-text)]">
        <span className="capitalize">Stage: {(live && run?.stage) || "starting"}</span>
        <span>{Math.round(progress * 100)}%</span>
      </div>
      <div className="w-full bg-[var(--cc-border)] h-1.5 rounded-full overflow-hidden">
        <div
          className="bg-[var(--cc-focus)] h-full transition-all duration-300"
          style={{ width: `${progress * 100}%` }}
        />
      </div>
    </div>
  );
}

export function AssessmentPanel({
  assessment,
  bundleId,
  run,
  isRunning = false,
  appMode,
  onDocumentUploaded,
}: AssessmentPanelProps) {
  const announce = useAnnounce();
  const status = assessment?.status ?? null;
  const prevStatusRef = useRef<string | null>(status);
  const panelRef = useRef<HTMLDivElement>(null);
  const [sampleBusy, setSampleBusy] = useState(false);
  const [sampleError, setSampleError] = useState<string | null>(null);

  // WCAG 2.2 AA Focus management & ARIA announcements on status changes
  useEffect(() => {
    if (prevStatusRef.current === status) return;
    prevStatusRef.current = status;
    if (!assessment) return;

    if (assessment.status === "MATERIAL_CONTRADICTION") {
      announce(
        `Adjudication alert: Material contradiction detected. ${assessment.checks[0]?.message || ""}`,
        "assertive"
      );
    } else if (assessment.status === "COMPLIANT_FOR_SUBMISSION") {
      announce("Assessment complete: Trade bundle is fully compliant for submission.", "polite");
    } else if (assessment.status === "MISSING_EVIDENCE") {
      announce(
        `Assessment updated: Missing evidence required. ${assessment.missing_evidence[0]?.document_label || ""}`,
        "polite"
      );
    }
    panelRef.current?.focus({ preventScroll: true });
  }, [status, assessment, announce]);

  if (!assessment) {
    return (
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex flex-col gap-3 p-4 h-full overflow-y-auto focus:outline-none"
      >
        {isRunning && <RunProgress run={run} />}
        <h2 className="text-sm font-bold text-[var(--cc-text)]">No assessment yet</h2>
        <p className="text-xs text-[var(--cc-text-muted)] leading-relaxed">
          Run analysis to adjudicate this bundle.
        </p>
      </div>
    );
  }

  const needsMtc = assessment.missing_evidence.some((item) => item.id === MTC_MISSING_ID);
  const showSampleMtc = appMode === "demo" && needsMtc;

  const handleUseSampleMtc = async () => {
    setSampleBusy(true);
    setSampleError(null);
    try {
      const file = await api.fetchSampleMtc();
      await api.uploadDocument(bundleId, file);
      onDocumentUploaded?.();
    } catch (err: unknown) {
      setSampleError(toErrorEnvelope(err).message);
    } finally {
      setSampleBusy(false);
    }
  };

  return (
    <div
      ref={panelRef}
      tabIndex={-1}
      className="flex flex-col gap-4 p-4 h-full overflow-y-auto focus:outline-none"
    >
      <header className="pb-3 border-b border-[var(--cc-border)]">
        <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--cc-text-subtle)]">
          Compliance Assessment
        </h2>
        <div className="flex items-center justify-between text-xs text-[var(--cc-text-muted)] mt-1">
          <span>Iteration {assessment.iteration}</span>
          <span>
            Extraction Confidence:{" "}
            {assessment.confidence
              ? `${(assessment.confidence.min_field_confidence * 100).toFixed(0)}%`
              : "N/A"}
          </span>
        </div>
      </header>

      {/* Real-time SSE execution progress indicator */}
      {isRunning && <RunProgress run={run} />}

      {/* Deterministic Rules Checklist */}
      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-bold uppercase text-[var(--cc-text-subtle)]">
          Mathematical & Semantic Parity Checks
        </h3>
        <CheckList checks={assessment.checks} />
      </div>

      {/* Missing Evidence / Regulatory Grounding */}
      {assessment.missing_evidence.length > 0 && (
        <div className="flex flex-col gap-2 mt-1">
          <h3 className="text-xs font-bold uppercase text-[var(--cc-warn)] flex items-center gap-1.5">
            <span>Mandatory Trade Documents Required</span>
          </h3>
          <div className="flex flex-col gap-2">
            {assessment.missing_evidence.map((item, index) => (
              <MissingEvidenceCard key={`${item.id}:${index}`} item={item} />
            ))}

          </div>

          {showSampleMtc && (
            <div className="flex flex-col gap-1.5">
              <button
                type="button"
                data-testid="sample-mtc-button"
                disabled={sampleBusy || isRunning}
                onClick={handleUseSampleMtc}
                className="rounded-[var(--cc-radius)] border border-[var(--cc-focus)] px-3 py-2 text-xs font-semibold text-[var(--cc-focus)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 cursor-pointer"
              >
                {sampleBusy ? "Uploading sample MTC..." : "Use sample MTC (demo)"}
              </button>
              {sampleError && (
                <div role="alert" className="text-[11px] text-[var(--cc-err)] font-medium">
                  {sampleError}
                </div>
              )}
            </div>
          )}

          <div className="mt-2">
            <UploadDropzone
              bundleId={bundleId}
              label="Upload Missing Certificate (PDF)"
              onUploaded={onDocumentUploaded}
            />
          </div>
        </div>
      )}
    </div>
  );
}
