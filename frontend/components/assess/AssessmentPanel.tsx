"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import type { ExtractedDoc } from "@/lib/corrections";
import type { AppMode, AssessmentIteration, BBox, CorrectionRequest, CorrectionsResponse, DocumentRecord } from "@/lib/types";
import { CheckList } from "./CheckList";
import { CorrectionsCard } from "./CorrectionsCard";
import { PrefillCard } from "./PrefillCard";
import { ValuationCard } from "./ValuationCard";
import { MissingEvidenceCard } from "./MissingEvidenceCard";
import { useAnnounce } from "../a11y/LiveRegion";
import { WorkflowStepper } from "../shell/WorkflowStepper";
import { StatusPill } from "./StatusPill";

interface AssessmentPanelProps {
  /** null = the bundle has not been analysed yet */
  assessment: AssessmentIteration | null;
  bundleId: string;
  documents?: DocumentRecord[];
  onSelectDocument?: (documentId: string, page?: number, field?: string, bbox?: BBox | null) => void;
  onRun?: () => void;
  onAddDocuments?: () => void;
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
      <p className="leading-relaxed text-[var(--cc-text-muted)] text-xs font-mono break-words bg-[var(--cc-surface)]/60 p-2 rounded border border-[var(--cc-border)]">
        {error}
      </p>
    </div>
  );
}

/** Keeps the verdict and the next work item visible while evidence is reviewed. */
function DecisionSummary({ assessment, bundleId, pending, isRunning, onRecompute, onAddDocuments }: {
  assessment: AssessmentIteration;
  bundleId: string;
  pending: number;
  isRunning: boolean;
  onRecompute?: () => void;
  onAddDocuments?: () => void;
}) {
  const summaryRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const summary = summaryRef.current;
    if (!summary) return;
    const update = () => summary.parentElement?.style.setProperty("--cc-summary-height", `${summary.offsetHeight}px`);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(summary);
    return () => observer.disconnect();
  }, []);
  const material = assessment.checks.filter((check) => check.severity === "MATERIAL").length;
  const warnings = assessment.checks.filter((check) => check.severity === "WARN").length;
  const gaps = assessment.missing_evidence.length;
  const nextAction = pending > 0
    ? `${pending} saved ${pending === 1 ? "change is" : "changes are"} not included in this assessment. Recompute to update the decision.`
    : assessment.status === "COMPLIANT_FOR_SUBMISSION"
    ? "Review the declaration prefill and export the available outputs."
    : material > 0
      ? `Resolve ${material} material ${material === 1 ? "contradiction" : "contradictions"}, then reassess.`
      : gaps > 0
        ? `Upload ${gaps === 1 ? "the required document" : `${gaps} required documents`}, then reassess.`
        : "Review the warnings and any required specialist review before preparing the declaration.";
  const target = material > 0 ? "material-findings" : warnings > 0 ? "warning-findings" : "declaration-prefill";
  const actionLabel = pending > 0 ? "Apply saved changes" : material > 0 ? "Review material findings" : gaps > 0 ? "Add required evidence" : warnings > 0 ? "Review warnings" : "Review declaration prefill";
  const handleAction = () => {
    if (pending > 0 && onRecompute) onRecompute();
    else if (gaps > 0 && material === 0 && onAddDocuments) onAddDocuments();
    else {
      const element = document.getElementById(target);
      element?.scrollIntoView({ block: "start" });
      element?.focus({ preventScroll: true });
    }
  };

  return (
    <section ref={summaryRef} className="cc-decision-summary -mx-4 -mt-4 border-b border-[var(--cc-border)] bg-[var(--cc-surface)] px-4 pb-3 pt-4 shadow-[0_5px_12px_rgba(18,22,28,.05)]" aria-labelledby="decision-summary-heading">
      <div className="cc-decision-summary-content">
        <div>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p id="decision-summary-heading" className="text-xs font-bold uppercase tracking-[.12em] text-[var(--cc-text-subtle)]">Current decision</p>
              <div className="mt-1"><StatusPill status={assessment.status} testId="decision-status-pill" /></div>
            </div>
            <span className="rounded-md bg-[var(--cc-surface-2)] px-2 py-1 text-xs font-mono text-[var(--cc-text-muted)]">Iteration {assessment.iteration}</span>
          </div>
          <p className="mt-2 text-sm font-semibold leading-relaxed text-[var(--cc-text)]">{nextAction}</p>
          <p className="mt-1 text-xs text-[var(--cc-text-muted)]">{material} material · {warnings} warning{warnings === 1 ? "" : "s"} · {gaps} document gap{gaps === 1 ? "" : "s"}</p>
          <button type="button" className="cc-button cc-button-primary mt-3" data-testid="next-action" disabled={isRunning} onClick={handleAction}>{isRunning ? "Assessment in progress…" : actionLabel}</button>
          {isRunning && <p className="mt-1 text-xs text-[var(--cc-text-muted)]">The decision above is the last completed assessment.</p>}
        </div>
        <div id="declaration-prefill" tabIndex={-1} className="cc-decision-prefill">
          <PrefillCard bundleId={bundleId} assessment={assessment} pendingCorrections={pending} />
        </div>
      </div>
    </section>
  );
}

export function AssessmentPanel({
  assessment,
  bundleId,
  documents = [],
  onSelectDocument,
  isRunning = false,
  actionError = null,
  appMode,
  onDocumentUploaded,
  corrections = null,
  extractions = [],
  onCorrect,
  onRevertCorrection,
  onRecompute,
  onRun,
  onAddDocuments,
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
      announce("Assessment complete: Compliant for submission. Review the declaration prefill; the authorised CHA decides.", "polite");
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
        className="cc-assessment-content flex flex-col gap-3 p-4 h-full overflow-y-auto"
      >
        <WorkflowStepper
          documents={documents}
          assessment={null}
          status={null}
          isRunning={isRunning}
        />
        {actionError && <ActionErrorBanner error={actionError} />}
        <div className="cc-empty-state">
          <p className="cc-eyebrow">Next step</p>
          <h2 className="text-lg font-semibold text-[var(--cc-text)]">{documents.length ? "Your documents are ready for assessment" : "Add the trade documents to begin"}</h2>
          <p className="text-sm text-[var(--cc-text-muted)] leading-relaxed">{documents.length ? "Run analysis to identify contradictions, required evidence, and warnings. You can add more documents at any time." : "Upload the invoice, bill of lading, packing list, and any supporting certificates. You can classify each PDF before uploading."}</p>
          <button type="button" className="cc-button cc-button-primary" disabled={isRunning} onClick={documents.length ? onRun : onAddDocuments}>{isRunning ? "Assessment in progress…" : documents.length ? "Assess these documents" : "Add trade documents"}</button>
          <p className="text-xs text-[var(--cc-text-muted)]">Decision support only. The authorised CHA reviews the evidence and decides.</p>
        </div>
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
      className="cc-assessment-content flex flex-col gap-4 p-4 h-full overflow-y-auto"
    >
      <DecisionSummary assessment={assessment} bundleId={bundleId} pending={corrections?.pending ?? 0} isRunning={isRunning} onRecompute={onRecompute} onAddDocuments={onAddDocuments} />
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
              <span data-testid="recompute-badge" className="ml-1.5 rounded border border-[var(--cc-border-strong)] px-1 py-px text-xs font-semibold text-[var(--cc-text)]">
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

      {assessment.checks.some((check) => check.severity === "MATERIAL") && (
      <section id="material-findings" tabIndex={-1} className="cc-review-section flex flex-col gap-2" aria-labelledby="material-heading">
        <h3 id="material-heading" className="text-sm font-semibold text-[var(--cc-text)]">Resolve material findings</h3>
        <CheckList
          checks={assessment.checks.filter((check) => check.severity === "MATERIAL")}
          documents={documents}
          onSelectDocument={onSelectDocument}
          extractions={extractions}
          corrections={corrections}
          appliedCorrections={assessment.corrections ?? []}
          onCorrect={onCorrect}
          editingDisabled={isRunning}
        />
      </section>
      )}

      {/* Missing Evidence / Regulatory Grounding */}
      {assessment.missing_evidence.length > 0 && (
        <section id="missing-evidence" tabIndex={-1} className="cc-review-section flex flex-col gap-2 mt-1" aria-label="Required trade documents">
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
                <div role="alert" className="text-xs text-[var(--cc-err)] font-medium">
                  {sampleError}
                </div>
              )}
            </div>
          )}

        </section>
      )}

      {assessment.checks.some((check) => check.severity === "WARN") && (
        <section id="warning-findings" tabIndex={-1} className="cc-review-section flex flex-col gap-2" aria-labelledby="warning-heading">
          <h3 id="warning-heading" className="text-sm font-semibold text-[var(--cc-text)]">Review warnings</h3>
          <CheckList checks={assessment.checks.filter((check) => check.severity === "WARN")} documents={documents} onSelectDocument={onSelectDocument} extractions={extractions} corrections={corrections} appliedCorrections={assessment.corrections ?? []} onCorrect={onCorrect} editingDisabled={isRunning} />
        </section>
      )}

      {assessment.valuation && <ValuationCard valuation={assessment.valuation} />}
      <CheckList checks={assessment.checks.filter((check) => check.severity === "PASS")} documents={documents} onSelectDocument={onSelectDocument} extractions={extractions} corrections={corrections} appliedCorrections={assessment.corrections ?? []} onCorrect={onCorrect} editingDisabled={isRunning} />
    </div>
  );
}
