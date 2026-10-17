"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckResult, CorrectionRequest, DocumentRecord } from "@/lib/types";
import { DECLARABLE_DOCUMENT_TYPES, DeclarableDocumentType } from "@/lib/documentTypes";

interface DocumentRailProps {
  documents: DocumentRecord[];
  checks?: CheckResult[];
  activeDocumentId?: string;
  onSelectDocument?: (id: string) => void;
  /** Takes a document out of the bundle. Without it the rail has no remove control. */
  onRemoveDocument?: (id: string) => void | Promise<void>;
  /** Submits a correction, e.g. reclassifying a document type. */
  onCorrect?: (request: CorrectionRequest) => Promise<string | null>;
  /** A run or an upload is in progress: removing is refused by the API (409) until it ends, so the control waits. */
  removeDisabled?: boolean;
}

export function DocumentRail({
  documents,
  checks = [],
  activeDocumentId,
  onSelectDocument,
  onRemoveDocument,
  onCorrect,
  removeDisabled = false,
}: DocumentRailProps) {
  // The document whose removal is waiting for a second click (removing is not undoable).
  const [confirming, setConfirming] = useState<string | null>(null);
  const [reclassifyingDocId, setReclassifyingDocId] = useState<string | null>(null);
  const [targetType, setTargetType] = useState<DeclarableDocumentType | "">("");
  const [reclassifySubmitting, setReclassifySubmitting] = useState(false);
  const [reclassifyError, setReclassifyError] = useState<string | null>(null);
  // A confirmation waits for the document it was asked about: showing another one (or none) withdraws it, so it is never found open later.
  const shownDocumentId = activeDocumentId || documents[0]?.document_id;
  useEffect(() => {
    setConfirming(null);
  }, [shownDocumentId]);

  // Compute health status per document from checks
  const docHealthMap = useMemo(() => {
    const map = new Map<string, { material: number; warn: number; pass: number }>();
    for (const doc of documents) {
      map.set(doc.document_id, { material: 0, warn: 0, pass: 0 });
    }

    for (const check of checks) {
      for (const ev of check.evidence ?? []) {
        if (!ev.doc) continue;
        const current = map.get(ev.doc) || { material: 0, warn: 0, pass: 0 };
        if (check.severity === "MATERIAL") current.material += 1;
        else if (check.severity === "WARN") current.warn += 1;
        else if (check.severity === "PASS") current.pass += 1;
        map.set(ev.doc, current);
      }
    }
    return map;
  }, [documents, checks]);

  return (
    <div className="p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between pb-2 border-b border-[var(--cc-border)]">
        <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--cc-text-subtle)]">
          Trade Bundle Files ({documents.length})
        </h2>
      </div>

      <nav aria-label="Documents in this bundle" className="flex flex-col gap-1.5 mt-1">
        {documents.map((doc) => {
          const isActive = doc.document_id === (activeDocumentId || documents[0]?.document_id);
          const health = docHealthMap.get(doc.document_id);

          return (
            <div key={doc.document_id} className="flex flex-col gap-1">
              <button
                type="button"
                data-testid="document-item"
                onClick={() => onSelectDocument?.(doc.document_id)}
                className={`text-left p-2.5 rounded-[var(--cc-radius)] border transition-all text-xs flex flex-col gap-1.5 cursor-pointer ${
                  isActive
                    ? "bg-[var(--cc-surface-2)] border-[var(--cc-focus)] shadow-xs"
                    : "border-transparent hover:border-[var(--cc-border)] hover:bg-[var(--cc-surface-2)]"
                }`}
              >
                <div className="flex items-start justify-between gap-1">
                  <span className="font-semibold text-[var(--cc-text)] truncate flex-1 min-w-0" title={doc.filename}>
                    {doc.filename}
                  </span>
                  {health && health.material > 0 && (
                    <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-[var(--cc-err-bg)] text-[var(--cc-err)] border border-[var(--cc-err-bd)] whitespace-nowrap">
                      ● {health.material} Conflict{health.material > 1 ? "s" : ""}
                    </span>
                  )}
                  {health && health.material === 0 && health.warn > 0 && (
                    <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-[var(--cc-warn-bg)] text-[var(--cc-warn)] border border-[var(--cc-warn-bd)] whitespace-nowrap">
                      ▲ {health.warn} Gap
                    </span>
                  )}
                  {health && health.material === 0 && health.warn === 0 && health.pass > 0 && (
                    <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border border-[var(--cc-ok-bd)] whitespace-nowrap">
                      ✓ Clean
                    </span>
                  )}
                </div>

                <div className="flex flex-col gap-1 text-[11px] text-[var(--cc-text-muted)]">
                  <div className="flex items-center justify-between gap-1">
                    <span className="font-mono uppercase text-[10px] bg-[var(--cc-surface)] px-1.5 py-0.5 rounded border border-[var(--cc-border)] font-semibold text-[var(--cc-text)]">
                      {doc.doc_type.replace(/_/g, " ")}
                    </span>
                    <span>{(doc.bytes / 1024).toFixed(0)} KB</span>
                  </div>

                  {doc.declared_type && (
                    <div className="flex items-center gap-1 text-[10px]">
                      <span className="text-[var(--cc-text-muted)]">Declared:</span>
                      <span className="font-semibold text-[var(--cc-text)]">{doc.declared_type.replace(/_/g, " ")}</span>
                      {doc.declared_type !== doc.doc_type && doc.doc_type !== "UNKNOWN" && (
                        <span
                          className="px-1 py-0.2 rounded text-[9px] font-bold bg-[var(--cc-warn-bg)] text-[var(--cc-warn)] border border-[var(--cc-warn-bd)]"
                          title="Declared type differs from AI model reading (T-001)"
                        >
                          ⚠️ Mismatch
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </button>

              {onCorrect && isActive && (
                <div className="px-1 flex flex-col gap-1">
                  {reclassifyingDocId === doc.document_id ? (
                    <div className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] p-2 text-xs space-y-1.5 animate-in fade-in">
                      <span className="font-semibold text-[10px] uppercase tracking-wider text-[var(--cc-text-subtle)]">
                        Reclassify Document Type
                      </span>
                      <select
                        value={targetType}
                        onChange={(e) => setTargetType(e.target.value as DeclarableDocumentType)}
                        disabled={reclassifySubmitting}
                        className="w-full rounded border border-[var(--cc-border)] bg-[var(--cc-surface)] p-1 text-xs text-[var(--cc-text)]"
                      >
                        <option value="">Select correct type...</option>
                        {DECLARABLE_DOCUMENT_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                      {reclassifyError && (
                        <p className="text-[10px] text-[var(--cc-err)]">{reclassifyError}</p>
                      )}
                      <div className="flex items-center justify-end gap-1.5 pt-0.5">
                        <button
                          type="button"
                          onClick={() => {
                            setReclassifyingDocId(null);
                            setTargetType("");
                            setReclassifyError(null);
                          }}
                          className="rounded border border-[var(--cc-border)] px-2 py-0.5 text-[10px] text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] cursor-pointer"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          disabled={!targetType || reclassifySubmitting}
                          onClick={async () => {
                            if (!targetType) return;
                            setReclassifySubmitting(true);
                            setReclassifyError(null);
                            try {
                              const err = await onCorrect({
                                document_id: doc.document_id,
                                path: "doc_type",
                                value: targetType,
                                reason: "Corrected document type classification",
                              });
                              if (err) setReclassifyError(err);
                              else {
                                setReclassifyingDocId(null);
                                setTargetType("");
                              }
                            } catch (e: unknown) {
                              setReclassifyError(e instanceof Error ? e.message : "Correction failed");
                            } finally {
                              setReclassifySubmitting(false);
                            }
                          }}
                          className="rounded bg-[var(--cc-focus)] px-2 py-0.5 text-[10px] font-semibold text-white hover:brightness-90 disabled:opacity-50 cursor-pointer"
                        >
                          {reclassifySubmitting ? "Saving..." : "Apply Type"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setReclassifyingDocId(doc.document_id);
                        setTargetType((doc.doc_type as DeclarableDocumentType) || "");
                      }}
                      className="self-start min-h-[24px] inline-flex items-center text-[10px] text-[var(--cc-focus)] hover:underline cursor-pointer py-1"
                    >
                      ✎ Reclassify Type
                    </button>
                  )}
                </div>
              )}
              {onRemoveDocument && isActive && (
                confirming === doc.document_id ? (
                  <div
                    role="group"
                    aria-label={`Confirm removing ${doc.filename}`}
                    className="flex flex-col gap-1.5 rounded-[var(--cc-radius)] border border-[var(--cc-err-bd)] bg-[var(--cc-err-bg)]/30 p-2 text-[11px] text-[var(--cc-text)]"
                  >
                    <p>
                      Remove <strong className="break-all">{doc.filename}</strong> from this bundle? The file and what was read from it are
                      deleted. The audit trail keeps a record, and earlier assessments still describe it.
                    </p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        data-testid="confirm-remove-document"
                        disabled={removeDisabled}
                        onClick={() => {
                          setConfirming(null);
                          void onRemoveDocument(doc.document_id);
                        }}
                        className="rounded-[var(--cc-radius)] bg-[var(--cc-err)] px-2 py-1 font-semibold text-white hover:brightness-90 disabled:opacity-50 cursor-pointer"
                      >
                        Remove file
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirming(null)}
                        className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-2 py-1 font-medium hover:bg-[var(--cc-surface-2)] cursor-pointer"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    data-testid="remove-document"
                    aria-label={`Remove ${doc.filename} from this bundle`}
                    disabled={removeDisabled}
                    title={removeDisabled ? "Wait for the running analysis or upload to finish." : "Take this file out of the bundle"}
                    onClick={() => setConfirming(doc.document_id)}
                    className="self-end px-1 text-[11px] text-[var(--cc-text-muted)] underline hover:text-[var(--cc-err)] disabled:opacity-50 disabled:no-underline cursor-pointer"
                  >
                    Remove
                  </button>
                )
              )}
            </div>
          );
        })}
      </nav>
    </div>
  );
}
