"use client";

import { useState } from "react";
import { pathLabel } from "@/lib/corrections";
import type { AssessmentIteration, CorrectionRecord, CorrectionsResponse, DocumentRecord } from "@/lib/types";

interface CorrectionsCardProps {
  corrections: CorrectionsResponse;
  /** the assessment on screen: which corrections it used */
  assessment: AssessmentIteration;
  documents: DocumentRecord[];
  isRunning: boolean;
  onRevert: (correctionId: string) => Promise<string | null>;
  onRecompute: () => void;
}

function shown(value?: string | null, unit?: string | null): string {
  if (value === null || value === undefined || value === "") return "(not stated)";
  return unit && !value.toUpperCase().endsWith(unit.toUpperCase()) ? `${value} ${unit}` : value;
}

/**
 * The corrections made by the authorised agent, what each replaced, and whether the assessment on screen already includes
 * it. A correction changes nothing by itself: "Recompute" re-runs the checks on the stored extraction (no document is read
 * again, no model is called).
 */
export function CorrectionsCard({ corrections, assessment, documents, isRunning, onRevert, onRecompute }: CorrectionsCardProps) {
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  if (corrections.effective.length === 0 && corrections.pending === 0) return null;

  const docName = (id: string) => documents.find((d) => d.document_id === id)?.filename ?? id;
  const used = new Map((assessment.corrections ?? []).map((c) => [c.correction_id, c]));

  const statusOf = (entry: CorrectionRecord): { text: string; tone: "ok" | "warn" } => {
    const stored = used.get(entry.correction_id);
    if (stored?.status === "applied") return { text: "In this assessment", tone: "ok" };
    if (stored?.status === "skipped") return { text: `Not used: ${stored.note ?? "could not be placed"}`, tone: "warn" };
    return { text: "Pending recompute", tone: "warn" };
  };

  const revert = async (entry: CorrectionRecord) => {
    setBusyId(entry.correction_id);
    setError(null);
    const message = await onRevert(entry.correction_id);
    setBusyId(null);
    if (message) setError(message);
  };

  return (
    <section
      aria-label="Corrections by the authorised agent"
      data-testid="corrections-card"
      className="flex flex-col gap-2 rounded-[var(--cc-radius)] border border-[var(--cc-border)] bg-[var(--cc-surface-2)] p-3 text-xs"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-xs font-bold uppercase text-[var(--cc-text-subtle)]">Corrections ({corrections.effective.length})</h3>
        {corrections.pending > 0 && (
          <span data-testid="corrections-pending" className="rounded border border-[var(--cc-warn-bd)] bg-[var(--cc-warn-bg)] px-1.5 py-0.5 text-[10px] font-bold uppercase text-[var(--cc-warn)]">
            {corrections.pending} not in this assessment yet
          </span>
        )}
      </div>

      <ul className="flex flex-col gap-1.5">
        {corrections.effective.map((entry) => {
          const status = statusOf(entry);
          return (
            <li key={entry.correction_id} className="rounded border border-[var(--cc-border)] bg-[var(--cc-surface)] p-2 flex flex-col gap-1">
              <div className="flex items-start justify-between gap-2">
                <span className="font-semibold text-[var(--cc-text)]">
                  {pathLabel(entry.path)} <span className="font-normal text-[var(--cc-text-muted)]">· {docName(entry.document_id)}</span>
                </span>
                <button
                  type="button"
                  data-testid="correction-undo"
                  disabled={isRunning || busyId === entry.correction_id}
                  onClick={() => void revert(entry)}
                  className="text-[10px] font-semibold text-[var(--cc-focus)] hover:underline disabled:opacity-50 cursor-pointer"
                  aria-label={`Undo the ${entry.kind} of ${pathLabel(entry.path)} in ${docName(entry.document_id)}`}
                >
                  Undo
                </button>
              </div>
              <div className="font-mono text-[11px] text-[var(--cc-text)]">
                {entry.kind === "confirmation" ? (
                  <>Confirmed: {shown(entry.value, entry.unit ?? entry.original_unit)}</>
                ) : (
                  <>
                    <span className="text-[var(--cc-text-muted)] line-through">{shown(entry.original_value, entry.original_unit)}</span>
                    {" → "}
                    <span className="font-semibold">{shown(entry.value, entry.unit ?? entry.original_unit)}</span>
                  </>
                )}
              </div>
              {entry.reason && <div className="text-[11px] text-[var(--cc-text-muted)]">“{entry.reason}”</div>}
              <span
                className={`self-start text-[10px] font-bold ${status.tone === "ok" ? "text-[var(--cc-ok)]" : "text-[var(--cc-warn)]"}`}
              >
                {status.text}
              </span>
            </li>
          );
        })}
      </ul>

      {error && (
        <div role="alert" className="text-[11px] font-medium text-[var(--cc-err)]">
          {error}
        </div>
      )}

      {corrections.pending > 0 && (
        <div className="flex flex-col gap-1">
          <button
            type="button"
            data-testid="recompute-button"
            disabled={isRunning}
            onClick={onRecompute}
            className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-90 disabled:opacity-50 cursor-pointer"
          >
            {isRunning ? "Recomputing..." : "Recompute with corrections"}
          </button>
          <span className="text-[10px] text-[var(--cc-text-muted)]">
            Re-runs every check on the stored extraction. No document is read again and no model is called.
          </span>
        </div>
      )}
    </section>
  );
}
