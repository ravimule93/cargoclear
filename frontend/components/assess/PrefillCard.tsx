import { api } from "@/lib/api";
import type { AssessmentIteration } from "@/lib/types";

interface PrefillCardProps {
  bundleId: string;
  assessment: AssessmentIteration;
  /** corrections made that this assessment does not include yet */
  pendingCorrections: number;
}

/**
 * Declaration pre-fill: the values of this assessment, with where each came from, for the person who keys the declaration.
 * It is CargoClear's own documented format (not a government one) and never says a declaration is ready to file.
 */
export function PrefillCard({ bundleId, assessment, pendingCorrections }: PrefillCardProps) {
  const cleared = assessment.status === "COMPLIANT_FOR_SUBMISSION";
  const caveat = !cleared
    ? "Not cleared: the pack leads with what blocks it, and flags every value an open finding cites."
    : pendingCorrections > 0
      ? `${pendingCorrections} correction change(s) are not in this assessment yet: recompute first.`
      : "Cleared, and it includes every correction made so far.";

  return (
    <section
      aria-label="Declaration pre-fill"
      data-testid="prefill-card"
      className="flex flex-col gap-2 rounded-[var(--cc-radius)] border border-[var(--cc-border)] bg-[var(--cc-surface-2)] p-3 text-xs"
    >
      <h3 className="text-xs font-bold uppercase text-[var(--cc-text-subtle)]">Declaration pre-fill</h3>
      <p className="leading-relaxed text-[var(--cc-text-muted)] text-[11px]">
        The values read from your documents (with your corrections), where each came from, what the other documents say, and what you
        must still supply. Not a filed declaration.
      </p>
      <p data-testid="prefill-caveat" className={`text-[11px] font-semibold ${cleared && pendingCorrections === 0 ? "text-[var(--cc-ok)]" : "text-[var(--cc-warn)]"}`}>
        {caveat}
      </p>
      <div className="flex gap-2">
        <a
          data-testid="prefill-json"
          href={api.prefillUrl(bundleId, "json", assessment.iteration)}
          download
          className="rounded border border-[var(--cc-border-strong)] px-2.5 py-1 font-semibold text-[var(--cc-focus)] hover:bg-[var(--cc-surface)]"
        >
          Download JSON
        </a>
        <a
          data-testid="prefill-pdf"
          href={api.prefillUrl(bundleId, "pdf", assessment.iteration)}
          download
          className="rounded border border-[var(--cc-border-strong)] px-2.5 py-1 font-semibold text-[var(--cc-focus)] hover:bg-[var(--cc-surface)]"
        >
          Download PDF summary
        </a>
      </div>
    </section>
  );
}
