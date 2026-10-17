"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import type { ExtractedDoc } from "@/lib/corrections";
import type { AppMode, AssessmentIteration, CorrectionRequest, CorrectionsResponse, DocumentRecord } from "@/lib/types";
import type { StreamRunState } from "@/lib/hooks/useBundleStream";
import { CheckList } from "./CheckList";
import { CorrectionsCard } from "./CorrectionsCard";
import { PrefillCard } from "./PrefillCard";
import { ValuationCard } from "./ValuationCard";
import { MissingEvidenceCard } from "./MissingEvidenceCard";
import { UploadDropzone } from "../upload/UploadDropzone";
import { useAnnounce } from "../a11y/LiveRegion";
import { WorkflowStepper } from "../shell/WorkflowStepper";
import { StatusPill } from "./StatusPill";

interface AssessmentPanelProps {
  /** null = the bundle has not been analysed yet */
  assessment: AssessmentIteration | null;
  bundleId: string;
  documents?: DocumentRecord[];
  onSelectDocument?: (documentId: string) => void;
  run?: StreamRunState | null;
  /** True from the moment a run was requested until the stream reports it finished. */
  isRunning?: boolean;
  actionError?: string | null;
  appMode?: AppMode;
  onDocumentUploaded?: () => void;
  /** Corrections by the authorised agent: the list, the extraction behind this assessment, and the actions. */
  corrections?: CorrectionsResponse | null;
  extractions?: ExtractedDoc[];
  onCorrect?: (request: CorrectionRequest) => Promise<string | null>;
  onRevertCorrection?: (correctionId: string) => Promise<string | null>;
  onRecompute?: () => void;
}

const MTC_MISSING_ID = "ME-MILL_TEST_CERTIFICATE";

const STAGE_LABELS: Record<string, string> = {
  initializing: "Initializing Pipeline...",
  preprocess: "Preprocessing & PDF Normalization",
  extract: "Multimodal Gemini Extraction",
  discrepancy: "Cross-Document Discrepancy Checks",
  ground: "Evidence Grounding & Bounding Boxes",
  confidence: "Confidence Scoring & Threshold Evaluation",
  synthesize: "Tariff & Regulatory Synthesis",
  finalize: "Finalizing Cryptographic Audit Ledger",
};

function RunProgress({ run }: { run?: StreamRunState | null }) {
  const live = run?.state === "RUNNING" || run?.state === "QUEUED";
  const progress = live ? (run?.progress ?? 0) : 0;
  const rawStage = run?.stage || "";
  const stageDisplay = STAGE_LABELS[rawStage] || (rawStage ? rawStage.charAt(0).toUpperCase() + rawStage.slice(1) : "Starting Analysis...");

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="run-progress"
      className="bg-[var(--cc-surface-2)] p-3 rounded-[var(--cc-radius)] border border-[var(--cc-focus)] text-xs flex flex-col gap-2 shadow-xs"
    >
      <div className="flex justify-between items-center font-semibold text-[var(--cc-text)]">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-[var(--cc-focus)] border-t-transparent" />
          <span>{stageDisplay}</span>
        </div>
        <span className="font-mono text-[11px] text-[var(--cc-focus)]">{Math.round(progress * 100)}%</span>
      </div>
      <div className="w-full bg-[var(--cc-border)] h-2 rounded-full overflow-hidden">
        <div
          className="bg-[var(--cc-focus)] h-full transition-all duration-300 rounded-full"
          style={{ width: `${Math.max(5, Math.round(progress * 100))}%` }}
        />
      </div>
    </div>
  );
}

function ActionErrorBanner({ error }: { error: string }) {
  return (
    <div
      role="alert"
      className="rounded-[var(--cc-radius)] border border-[var(--cc-err)]/50 bg-[var(--cc-err)]/10 p-3 text-xs flex flex-col gap-1.5 text-[var(--cc-text)] animate-in fade-in"
    >
      <div className="flex items-center gap-1.5 font-bold text-[var(--cc-err)]">
        <span aria-hidden="true">⚠️</span>
        <span>Analysis Issue Detected</span>
      </div>
      <p className="leading-relaxed text-[var(--cc-text-muted)] text-[11px] font-mono break-words bg-[var(--cc-surface)]/60 p-2 rounded border border-[var(--cc-border)]">
        {error}
      </p>
    </div>
  );
}

/** Keeps the verdict and the next work item visible while evidence is reviewed. */
function DecisionSummary({ assessment }: { assessment: AssessmentIteration }) {
  const material = assessment.checks.filter((check) => check.severity === "MATERIAL").length;
  const warnings = assessment.checks.filter((check) => check.severity === "WARN").length;
  const gaps = assessment.missing_evidence.length;
  const nextAction = assessment.status === "COMPLIANT_FOR_SUBMISSION"
    ? "Review the declaration prefill and export the available outputs."
    : material > 0
      ? `Resolve ${material} material ${material === 1 ? "contradiction" : "contradictions"}, then reassess.`
      : gaps > 0
        ? `Upload ${gaps === 1 ? "the required document" : `${gaps} required documents`}, then reassess.`
        : "Review the warnings before preparing the declaration.";

  return (
    <section className="cc-decision-summary -mx-4 -mt-4 border-b border-[var(--cc-border)] bg-[var(--cc-surface)] px-4 pb-3 pt-4 shadow-[0_5px_12px_rgba(18,22,28,.05)]" aria-labelledby="decision-summary-heading">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p id="decision-summary-heading" className="text-[10px] font-bold uppercase tracking-[.12em] text-[var(--cc-text-subtle)]">Current decision</p>
          <div className="mt-1"><StatusPill status={assessment.status} testId="decision-status-pill" /></div>
        </div>
        <span className="rounded-md bg-[var(--cc-surface-2)] px-2 py-1 text-[10px] font-mono text-[var(--cc-text-muted)]">Iteration {assessment.iteration}</span>
      </div>
      <p className="mt-2 text-xs font-semibold leading-relaxed text-[var(--cc-text)]">{nextAction}</p>
      <p className="mt-1 text-[11px] text-[var(--cc-text-muted)]">{material} material · {warnings} warning{warnings === 1 ? "" : "s"} · {gaps} document gap{gaps === 1 ? "" : "s"}</p>
    </section>
  );
}

export function AssessmentPanel({
  assessment,
  bundleId,
  documents = [],
  onSelectDocument,
  run,
  isRunning = false,
  actionError = null,
  appMode,
  onDocumentUploaded,
  corrections = null,
  extractions = [],
  onCorrect,
  onRevertCorrection,
  onRecompute,
}: AssessmentPanelProps) {
  const announce = useAnnounce();
  const status = assessment?.status ?? null;
  const prevStatusRef = useRef<string | null>(status);
  const panelRef = useRef<HTMLDivElement>(null);
  const [sampleBusy, setSampleBusy] = useState(false);
  const [sampleError, setSampleError] = useState<string | null>(null);

  // Announce a changed decision without taking a reviewer away from the
  // correction, upload, or evidence control they are actively using.
  useEffect(() => {
    if (prevStatusRef.current === status) return;
    prevStatusRef.current = status;
    if (!assessment) return;

    if (assessment.status === "MATERIAL_CONTRADICTION") {
      announce(
        `Assessment alert: Material contradiction detected. ${
          assessment.checks.find((check) => check.severity === "MATERIAL")?.message || ""
        }`,
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
  }, [status, assessment, announce]);

  if (!assessment) {
    return (
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex flex-col gap-3 p-4 h-full overflow-y-auto focus:outline-none"
      >
        <WorkflowStepper
          documents={documents}
          assessment={null}
          status={null}
          isRunning={isRunning}
        />
        {actionError && <ActionErrorBanner error={actionError} />}
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
      <DecisionSummary assessment={assessment} />
      <WorkflowStepper
        documents={documents}
        assessment={assessment}
        status={assessment.status}
        isRunning={isRunning}
      />
      <header className="pb-3 border-b border-[var(--cc-border)]">
        <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--cc-text-subtle)]">
          Compliance Assessment
        </h2>
        <div className="flex items-center justify-between text-xs text-[var(--cc-text-muted)] mt-1">
          <span>
            Iteration {assessment.iteration}
            {assessment.run_mode === "recompute" && (
              <span data-testid="recompute-badge" className="ml-1.5 rounded border border-[var(--cc-border-strong)] px-1 py-px text-[10px] font-semibold text-[var(--cc-text)]">
                recomputed
              </span>
            )}
          </span>
          <span
            data-testid="extraction-confidence"
            title="The lowest confidence the extraction model reported for the values these checks rest on. A self-reported score, not a measured accuracy."
          >
            Lowest reported confidence:{" "}
            {assessment.confidence
              ? `${(assessment.confidence.min_field_confidence * 100).toFixed(0)}%`
              : "N/A"}
          </span>
        </div>
      </header>

      {/* Prominent Action Error Banner (e.g. Gemini token limits or validation failures) */}
      {actionError && <ActionErrorBanner error={actionError} />}

      {/* Live progress of the run, from the SSE status events */}
      {isRunning && <RunProgress run={run} />}

      {/* Corrections by the authorised agent: what they replaced, and whether this assessment includes them */}
      {corrections && onRevertCorrection && onRecompute && (
        <CorrectionsCard
          corrections={corrections}
          assessment={assessment}
          documents={documents}
          isRunning={isRunning}
          onRevert={onRevertCorrection}
          onRecompute={onRecompute}
        />
      )}

      {/* Deterministic Rules Checklist */}
      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-bold uppercase text-[var(--cc-text-subtle)]">
          Mathematical & Semantic Parity Checks
        </h3>
        <CheckList
          checks={assessment.checks}
          documents={documents}
          onSelectDocument={onSelectDocument}
          extractions={extractions}
          corrections={corrections}
          appliedCorrections={assessment.corrections ?? []}
          onCorrect={onCorrect}
          editingDisabled={isRunning}
        />
      </div>

      {/* Indicative duty exposure: information only, it never changes the status above */}
      {assessment.valuation && <ValuationCard valuation={assessment.valuation} />}

      {/* The values of this assessment for the person who keys the declaration */}
      <PrefillCard bundleId={bundleId} assessment={assessment} pendingCorrections={corrections?.pending ?? 0} />

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
