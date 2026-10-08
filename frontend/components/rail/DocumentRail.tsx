"use client";

import { DocumentRecord } from "@/lib/types";

interface DocumentRailProps {
  documents: DocumentRecord[];
  activeDocumentId?: string;
  onSelectDocument?: (id: string) => void;
}

export function DocumentRail({
  documents,
  activeDocumentId,
  onSelectDocument,
}: DocumentRailProps) {
  return (
    <div className="p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between pb-2 border-b border-[var(--cc-border)]">
        <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--cc-text-subtle)]">
          Trade Bundle Files ({documents.length})
        </h2>
      </div>

      <nav aria-label="Documents list" className="flex flex-col gap-1.5 mt-1">
        {documents.map((doc) => {
          const isActive = doc.document_id === (activeDocumentId || documents[0]?.document_id);
          return (
            <button
              key={doc.document_id}
              type="button"
              onClick={() => onSelectDocument?.(doc.document_id)}
              className={`text-left p-2.5 rounded-[var(--cc-radius)] border transition-all text-xs flex flex-col gap-1 cursor-pointer ${
                isActive
                  ? "bg-[var(--cc-surface-2)] border-[var(--cc-focus)] shadow-xs"
                  : "border-transparent hover:border-[var(--cc-border)] hover:bg-[var(--cc-surface-2)]"
              }`}
            >
              <div className="font-semibold text-[var(--cc-text)] truncate">
                {doc.filename}
              </div>
              <div className="flex items-center justify-between text-[11px] text-[var(--cc-text-muted)]">
                <span className="font-mono uppercase">{doc.doc_type.replace(/_/g, " ")}</span>
                <span>{(doc.bytes / 1024).toFixed(0)} KB</span>
              </div>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
