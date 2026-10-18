import { MissingEvidence } from "@/lib/types";

interface MissingEvidenceCardProps {
  item: MissingEvidence;
}

export function MissingEvidenceCard({ item }: MissingEvidenceCardProps) {
  return (
    <article
      className="rounded-[var(--cc-radius)] p-3 text-xs leading-relaxed"
      style={{
        background: "var(--cc-warn-bg)",
        border: "1px solid var(--cc-warn-bd)",
        color: "var(--cc-warn)",
      }}
    >
      <div className="flex items-center gap-1.5 font-bold mb-1">
        <span aria-hidden="true">⚠️</span>
        <h3>Missing: {item.document_label}</h3>
      </div>
      <p className="text-[var(--cc-text)]">
        Required for HS <code className="font-mono font-semibold">{item.hs_code}</code> — {item.reason}
      </p>
      {item.regulation_ref && (
        <div className="mt-2 text-xs opacity-75 font-mono">
          Ref: {item.regulation_ref}
        </div>
      )}
    </article>
  );
}
