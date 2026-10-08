"use client";

import { AssessmentIteration } from "@/lib/types";
import { useBundleStream } from "@/lib/hooks/useBundleStream";
import { CheckList } from "./CheckList";
import { MissingEvidenceCard } from "./MissingEvidenceCard";
import { UploadDropzone } from "../upload/UploadDropzone";

interface AssessmentPanelProps {
  assessment: AssessmentIteration;
  bundleId: string;
}

export function AssessmentPanel({
  assessment: initial,
  bundleId,
}: AssessmentPanelProps) {
  const { assessment: liveAssessment, run } = useBundleStream(bundleId, initial);
  const current = liveAssessment || initial;

  const isRunning = run.state === "RUNNING";

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      <header className="pb-3 border-b border-[var(--cc-border)]">
        <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--cc-text-subtle)]">
          Compliance Assessment
        </h2>
        <div className="flex items-center justify-between text-xs text-[var(--cc-text-muted)] mt-1">
          <span>Iteration {current.iteration}</span>
          <span>
            Confidence:{" "}
            {current.confidence
              ? `${(current.confidence.min_field_confidence * 100).toFixed(0)}%`
              : "N/A"}
          </span>
        </div>
      </header>

      {isRunning && (
        <div className="bg-[var(--cc-surface-2)] p-2.5 rounded-[var(--cc-radius)] border border-[var(--cc-focus)] text-xs flex flex-col gap-1.5">
          <div className="flex justify-between font-semibold">
            <span>Evaluating stage: {run.stage || "initializing"}</span>
            <span>{Math.round(run.progress * 100)}%</span>
          </div>
          <div className="w-full bg-[var(--cc-border)] h-1.5 rounded-full overflow-hidden">
            <div
              className="bg-[var(--cc-focus)] h-full transition-all duration-300"
              style={{ width: `${run.progress * 100}%` }}
            />
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-bold uppercase text-[var(--cc-text-subtle)]">
          Deterministic Rule Checks
        </h3>
        <CheckList checks={current.checks} />
      </div>

      {current.missing_evidence && current.missing_evidence.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-bold uppercase text-[var(--cc-warn)]">
            Required Documents
          </h3>
          <div className="flex flex-col gap-2">
            {current.missing_evidence.map((item) => (
              <MissingEvidenceCard key={item.id} item={item} />
            ))}
          </div>

          <div className="mt-2">
            <UploadDropzone bundleId={bundleId} />
          </div>
        </div>
      )}
    </div>
  );
}
