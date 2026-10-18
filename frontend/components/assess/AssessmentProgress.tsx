import type { StreamRunState } from "@/lib/hooks/useBundleStream";

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

/** The workbench header stays outside every independently scrolling panel. */
export function AssessmentProgress({ run }: {
  run?: StreamRunState | null;
}) {
  const live = run?.state === "RUNNING" || run?.state === "QUEUED";
  const progress = live && typeof run.progress === "number" && Number.isFinite(run.progress)
    ? Math.round(Math.min(1, Math.max(0, run.progress)) * 100)
    : null;
  // Do not show the preceding run's final stage/100% while a new request starts.
  const stage = live ? run.stage || "" : "";
  const stageLabel = STAGE_LABELS[stage] || (stage ? stage.charAt(0).toUpperCase() + stage.slice(1) : "Preparing assessment…");
  const label = `Assessment in progress — ${stageLabel}`;

  return (
    <div className="cc-run-feedback" data-testid="run-progress">
      <div className="cc-run-feedback-label" role="status" aria-live="polite" aria-atomic="true">
        <span>{label}</span>
        <span aria-hidden="true">{progress === null ? "Starting…" : `${progress}%`}</span>
      </div>
      <div role="progressbar" aria-label="Assessment progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress ?? undefined} aria-valuetext={progress === null ? label : `${progress}% — ${stageLabel}`} className="cc-run-feedback-track">
        <div className={`cc-run-feedback-fill${progress === null ? " cc-run-feedback-indeterminate" : ""}`} style={{ width: `${progress ?? 25}%` }} />
      </div>
    </div>
  );
}
