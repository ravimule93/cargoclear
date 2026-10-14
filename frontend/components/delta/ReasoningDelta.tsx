import { attributeLabel, plainValue } from "@/lib/delta-labels";
import { ReasoningDelta as ReasoningDeltaType, type ReasoningDeltaChange } from "@/lib/types";

interface ReasoningDeltaProps {
  delta?: ReasoningDeltaType | null;
}

export function ReasoningDelta({ delta }: ReasoningDeltaProps) {
  if (!delta) {
    return (
      <div className="text-xs text-[var(--cc-text-muted)] italic">
        No assessment iterations available for comparison.
      </div>
    );
  }

  if (delta.kind === "INITIAL") {
    return (
      <div className="text-xs text-[var(--cc-text-muted)]">
        <p className="font-semibold text-[var(--cc-text)] mb-1">Baseline Assessment</p>
        <p>{delta.narrative}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs bg-[var(--cc-surface-2)] p-2 rounded-[var(--cc-radius)] border border-[var(--cc-border)] font-medium text-[var(--cc-text)]">
        {delta.narrative}
      </div>

      {delta.changes && delta.changes.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-[var(--cc-border)] text-[var(--cc-text-subtle)] font-bold uppercase text-[10px]">
                <th className="py-1 px-2">Attribute</th>
                <th className="py-1 px-2">Previous State</th>
                <th className="py-1 px-2">Current State</th>
                <th className="py-1 px-2">Reasoning Delta</th>
              </tr>
            </thead>
            <tbody>
              {delta.changes.map((change: ReasoningDeltaChange, idx: number) => (

                <tr key={idx} className="border-b border-[var(--cc-border)] hover:bg-[var(--cc-surface-2)]">
                  <td className="py-1.5 px-2 text-[var(--cc-text)]" title={change.field || undefined}>
                    {attributeLabel(change.field || "")}
                  </td>
                  <td className="py-1.5 px-2 text-[var(--cc-err)] font-semibold">{plainValue(change.from)}</td>
                  <td className="py-1.5 px-2 text-[var(--cc-ok)] font-semibold">{plainValue(change.to)}</td>
                  <td className="py-1.5 px-2 text-[var(--cc-text-muted)]">{String(change.because ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
