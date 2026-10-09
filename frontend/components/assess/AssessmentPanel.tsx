"use client";

import { useEffect, useRef } from "react";
import { AssessmentIteration, MissingEvidence, StatusEvent } from "@/lib/types";

import { CheckList } from "./CheckList";
import { MissingEvidenceCard } from "./MissingEvidenceCard";
import { UploadDropzone } from "../upload/UploadDropzone";
import { useAnnounce } from "../a11y/LiveRegion";

interface AssessmentPanelProps {
  assessment: AssessmentIteration;
  bundleId: string;
  runState?: StatusEvent;
  onDocumentUploaded?: () => void;
}

export function AssessmentPanel({
  assessment,
  bundleId,
  runState,
  onDocumentUploaded,
}: AssessmentPanelProps) {
  const announce = useAnnounce();
  const prevStatusRef = useRef<string>(assessment.status);
  const panelRef = useRef<HTMLDivElement>(null);

  const isRunning = runState?.state === "RUNNING";

  // WCAG 2.2 AA Focus management & ARIA announcements on status changes
  useEffect(() => {
    if (prevStatusRef.current !== assessment.status) {
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

      prevStatusRef.current = assessment.status;
      panelRef.current?.focus({ preventScroll: true });
    }
  }, [assessment.status, assessment.checks, assessment.missing_evidence, announce]);

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
      {isRunning && runState && (
        <div
          role="status"
          aria-live="polite"
          className="bg-[var(--cc-surface-2)] p-2.5 rounded-[var(--cc-radius)] border border-[var(--cc-focus)] text-xs flex flex-col gap-1.5"
        >
          <div className="flex justify-between font-semibold text-[var(--cc-text)]">
            <span className="capitalize">Stage: {runState.stage || "processing"}</span>
            <span>{Math.round(runState.progress * 100)}%</span>
          </div>
          <div className="w-full bg-[var(--cc-border)] h-1.5 rounded-full overflow-hidden">
            <div
              className="bg-[var(--cc-focus)] h-full transition-all duration-300"
              style={{ width: `${runState.progress * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Deterministic Rules Checklist */}
      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-bold uppercase text-[var(--cc-text-subtle)]">
          Mathematical & Semantic Parity Checks
        </h3>
        <CheckList checks={assessment.checks} />
      </div>

      {/* Missing Evidence / Regulatory Grounding */}
      {assessment.missing_evidence && assessment.missing_evidence.length > 0 && (
        <div className="flex flex-col gap-2 mt-1">
          <h3 className="text-xs font-bold uppercase text-[var(--cc-warn)] flex items-center gap-1.5">
            <span>Mandatory Trade Documents Required</span>
          </h3>
          <div className="flex flex-col gap-2">
            {assessment.missing_evidence.map((item: MissingEvidence) => (
              <MissingEvidenceCard key={item.id} item={item} />
            ))}

          </div>

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
