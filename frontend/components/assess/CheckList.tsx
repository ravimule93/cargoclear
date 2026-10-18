import { useMemo, useState } from "react";
import { evidencePath, pathLabel, readCell, type ExtractedDoc } from "@/lib/corrections";
import type { AppliedCorrection, BBox, CheckResult, CorrectionRequest, CorrectionsResponse, DocumentRecord } from "@/lib/types";
import { CorrectionEditor } from "./CorrectionEditor";

interface CheckListProps {
  checks: CheckResult[];
  documents?: DocumentRecord[];
  onSelectDocument?: (documentId: string, page?: number, field?: string, bbox?: BBox | null) => void;
  /** With these, an evidence row that shows one extracted value can be corrected in place. */
  extractions?: ExtractedDoc[];
  corrections?: CorrectionsResponse | null;
  /** corrections the assessment on screen used */
  appliedCorrections?: AppliedCorrection[];
  onCorrect?: (request: CorrectionRequest) => Promise<string | null>;
  /** no editing while a run is in progress */
  editingDisabled?: boolean;
}

const CHECK_TITLES: Record<string, string> = {
  "W-001": "Weight Balance (BoL Gross vs Packing List Net+Tare)",
  "W-002": "Packing List Internal Weight Parity",
  "H-002": "Cross-Document HS Code Alignment",
  "E-consignee": "Consignee Entity Alignment",
  "E-consignor": "Consignor Entity Alignment",
  "E-vessel": "Vessel / Voyage Identification",
  "G-001": "Tariff Classification Grounding (AHTN)",
  "E-origin": "Country of Origin Consistency",
  "I-001": "Invoice Line Arithmetic (Quantity × Unit Price)",
  "I-002": "Invoice Total vs Line Totals",
  "I-003": "Invoice Currency Consistency",
  "M-001": "Alloy Status vs Declared HS Code (HS Note 1)",
  "M-002": "Carbon Equivalent vs Specification",
  "M-003": "Chemistry & Strength vs Specification",
  "M-004": "Heat-Number Traceability (Packing List ↔ Certificate)",
  "M-005": "Conflicting Values for One Certificate Cell",
  "SEC-001": "Alloy-Threshold Proximity (Circumvention Heuristic)",
  "SEC-002": "Anti-Dumping Exposure",
};

/** Evidence entries shown before "Show all": a certificate's table can cite dozens of cells. */
const EVIDENCE_PREVIEW = 5;

export function CheckList({
  checks,
  documents = [],
  onSelectDocument,
  extractions = [],
  corrections = null,
  appliedCorrections = [],
  onCorrect,
  editingDisabled = false,
}: CheckListProps) {
  const [showAllPass, setShowAllPass] = useState(false);
  const [allEvidence, setAllEvidence] = useState<Record<string, boolean>>({});
  const [editing, setEditing] = useState<string | null>(null);

  // Quick lookup from document_id to DocumentRecord
  const docMap = useMemo(() => {
    const map = new Map<string, DocumentRecord>();
    for (const d of documents) {
      map.set(d.document_id, d);
    }
    return map;
  }, [documents]);

  // Which correction (if any) stands on an address: in force now, and whether the assessment on screen used it.
  const stateOf = (documentId: string, path: string) => {
    const inForce = corrections?.effective.find((c) => c.document_id === documentId && c.path === path);
    const used = appliedCorrections.find((c) => c.document_id === documentId && c.path === path && c.status === "applied");
    if (inForce && used?.correction_id === inForce.correction_id) return { kind: "used" as const, entry: used };
    if (inForce) return { kind: "pending" as const, entry: inForce };
    if (used) return { kind: "undone" as const, entry: used };
    return null;
  };

  if (checks.length === 0) {
    return null;
  }

  // Group checks into issues (MATERIAL/WARN) vs clean (PASS)
  const issues = checks.filter((c) => c.severity !== "PASS");
  const passed = checks.filter((c) => c.severity === "PASS");

  const renderCheckItem = (check: CheckResult, index: number, group: "issue" | "pass") => {
    const isPass = check.severity === "PASS";
    const isMaterial = check.severity === "MATERIAL";

    const badgeColor = isPass
      ? "text-[var(--cc-ok)] bg-[var(--cc-ok-bg)] border-[var(--cc-ok-bd)]"
      : isMaterial
      ? "text-[var(--cc-err)] bg-[var(--cc-err-bg)] border-[var(--cc-err-bd)]"
      : "text-[var(--cc-warn)] bg-[var(--cc-warn-bg)] border-[var(--cc-warn-bd)]";

    // P-001 / P-002 / T-001 / L-001 end in the document id (one per document), like H-003 ends in the certificate type
    const friendlyTitle =
      CHECK_TITLES[check.check_id] ||
      (check.check_id.startsWith("H-003")
        ? `Certificate HS Verification (${check.check_id.replace("H-003-", "").replace(/_/g, " ")})`
        : check.check_id.startsWith("P-001-")
        ? "Pages Not Read"
        : check.check_id.startsWith("P-002-")
        ? "Pages Skipped (Terms and Conditions)"
        : check.check_id.startsWith("T-001-")
        ? "Document Type Differs From the Upload"
        : check.check_id.startsWith("L-001-")
        ? "Values Not in Latin Script"
        : check.check_id);

    const evidenceList = check.evidence ?? [];
    const evidenceExpanded = allEvidence[check.check_id] === true;
    const visibleEvidence = evidenceExpanded ? evidenceList : evidenceList.slice(0, EVIDENCE_PREVIEW);
    const hiddenEvidence = evidenceList.length - visibleEvidence.length;
    const assumptions = check.assumptions ?? [];

    return (
      <li
        key={`${check.check_id}:${index}`}
        className={`p-3 rounded-[var(--cc-radius)] border flex flex-col gap-2 text-xs transition-colors ${
          isMaterial
            ? "border-[var(--cc-err-bd)]/60 bg-[var(--cc-err-bg)]/20"
            : !isPass
            ? "border-[var(--cc-warn-bd)]/60 bg-[var(--cc-warn-bg)]/20"
            : "border-[var(--cc-border)] bg-[var(--cc-surface-2)]"
        }`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <span className="font-bold text-[var(--cc-text)] text-[12px]">
              {friendlyTitle}
            </span>
            <span className="font-mono text-xs text-[var(--cc-text-subtle)]">
              {check.check_id}
            </span>
          </div>
          <span
            className={`px-2 py-0.5 rounded text-xs font-bold border tracking-wider uppercase whitespace-nowrap ${badgeColor}`}
          >
            {check.severity}
          </span>
        </div>

        <p className="text-[var(--cc-text-muted)] leading-relaxed text-xs">
          {check.message}
        </p>

        {assumptions.length > 0 && (
          <div className="text-xs text-[var(--cc-text-muted)]">
            <span className="font-semibold text-[var(--cc-text)]">Assumed:</span>
            <ul className="list-disc pl-4 mt-0.5">
              {assumptions.map((assumption, i) => (
                <li key={`${check.check_id}:assumption:${i}`}>{assumption}</li>
              ))}
            </ul>
          </div>
        )}

        {check.rule_set && (
          <details className="text-xs text-[var(--cc-text-subtle)]">
            <summary className="cursor-pointer">
              Rule set: <span className="font-mono font-semibold">{check.rule_set}</span> (not an official source unless stated)
            </summary>
            {check.regulation_ref && <p className="mt-1 leading-relaxed">{check.regulation_ref}</p>}
          </details>
        )}

        {/* Side-by-Side Comparison Box for multi-document discrepancy */}
        {!isPass && evidenceList.length >= 2 && (
          <div className="mt-1 rounded-md border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] p-2.5 flex flex-col gap-2 shadow-2xs">
            <div className="flex items-center justify-between text-xs font-bold text-[var(--cc-text)]">
              <span className="flex items-center gap-1.5">
                <span>⚖️</span>
                <span>Compared Documents:</span>
              </span>
              {check.delta !== null && check.delta !== undefined && (
                <span className="font-mono text-xs text-[var(--cc-err)] bg-[var(--cc-err-bg)] px-1.5 py-0.5 rounded border border-[var(--cc-err-bd)] font-semibold">
                  Discrepancy / Delta: {check.delta}
                </span>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {visibleEvidence.slice(0, 2).map((ev, evIdx) => {
                const docRecord = ev.doc ? docMap.get(ev.doc) : null;
                const docName = docRecord?.filename || ev.doc || "Document";
                const docType = docRecord?.doc_type?.replace(/_/g, " ") || "";
                const hasVal = ev.raw_value !== undefined && ev.raw_value !== null && String(ev.raw_value).trim() !== "";

                return (
                  <button
                    type="button"
                    key={`comp-card-${ev.doc}-${evIdx}`}
                    disabled={!ev.doc}
                    onClick={() => ev.doc && onSelectDocument?.(ev.doc, ev.page ?? undefined, ev.field, ev.bbox)}
                    aria-label={ev.doc ? `Open ${docName}${ev.page ? `, page ${ev.page}` : ""}` : undefined}
                    className={`p-2 rounded border text-xs flex flex-col gap-1 transition-all ${
                      ev.doc ? "cursor-pointer text-left hover:border-[var(--cc-focus)] hover:shadow-xs" : "cursor-default text-left"
                    } ${
                      !hasVal
                        ? "bg-[var(--cc-warn-bg)]/40 border-[var(--cc-warn-bd)]"
                        : "bg-[var(--cc-surface-2)] border-[var(--cc-border)]"
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs text-[var(--cc-text-muted)]">
                      <span className="font-bold text-[var(--cc-text)] truncate max-w-[130px] sm:max-w-[150px]">{docName}</span>
                      {docType && <span className="uppercase text-xs px-1 bg-[var(--cc-surface)] rounded border border-[var(--cc-border)] shrink-0">{docType}</span>}
                    </div>
                    <div className="text-xs font-mono font-bold text-[var(--cc-text)]">
                      {hasVal ? (
                        <span>
                          {String(ev.raw_value)} {ev.unit && !String(ev.raw_value).trim().endsWith(ev.unit.trim()) ? ev.unit : ""}
                        </span>
                      ) : (
                        <span className="text-[var(--cc-warn)] italic">Field Omitted (Gap in {docName})</span>
                      )}
                    </div>
                    <div className="flex items-center justify-between text-xs text-[var(--cc-text-subtle)] mt-0.5">
                      <span>{ev.field.replace(/_/g, " ")}</span>
                      {ev.page && <span className="text-[var(--cc-focus)] font-medium">Page {ev.page} →</span>}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Structured Evidence Breakdown */}
        {evidenceList.length > 0 && (
          <div className="mt-1 pt-2 border-t border-[var(--cc-border)]/60 flex flex-col gap-1.5">
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--cc-text-subtle)]">
              All Cited Evidence & Grounding:
            </span>
            <div className="flex flex-col gap-1.5">
              {visibleEvidence.map((ev, evIdx) => {
                const docRecord = ev.doc ? docMap.get(ev.doc) : null;
                const docName = docRecord?.filename || ev.doc || "Unknown Document";
                const docType = docRecord?.doc_type?.replace(/_/g, " ") || "";
                const hasValue = ev.raw_value !== undefined && ev.raw_value !== null && String(ev.raw_value).trim() !== "";
                const isGap = !hasValue;
                const path = onCorrect && ev.doc ? evidencePath(ev) : null;
                const editKey = `${group}:${index}:${evIdx}`;
                const state = path ? stateOf(ev.doc, path) : null;

                return (
                  <div key={`${ev.doc}:${ev.field}:${evIdx}`} className="flex flex-col gap-1">
                  <div
                    className={`p-1.5 rounded border text-xs flex flex-wrap sm:flex-nowrap items-center justify-between gap-1.5 sm:gap-2 transition-all ${
                      ev.doc
                        ? "cursor-pointer hover:border-[var(--cc-focus)] hover:bg-[var(--cc-surface)]"
                        : ""
                    } ${
                      isGap
                        ? "border-[var(--cc-warn-bd)]/60 bg-[var(--cc-warn-bg)]/30 text-[var(--cc-warn)]"
                        : "border-[var(--cc-border)] bg-[var(--cc-surface)] text-[var(--cc-text)]"
                    }`}
                  >
                    <div className="flex items-center gap-1.5 truncate min-w-0 flex-1">
                      <span aria-hidden="true" className="text-xs shrink-0">
                        {isGap ? "⚠️" : "📄"}
                      </span>
                      {ev.doc ? (
                        <button
                          type="button"
                          onClick={() => onSelectDocument?.(ev.doc, ev.page ?? undefined, ev.field, ev.bbox)}
                          className="font-semibold truncate text-left hover:underline"
                          aria-label={`Open ${docName}${ev.page ? `, page ${ev.page}` : ""}`}
                        >
                          {docName}
                        </button>
                      ) : (
                        <span className="font-semibold truncate">{docName}</span>
                      )}
                      {docType && (
                        <span className="text-xs uppercase px-1 rounded bg-[var(--cc-surface-2)] text-[var(--cc-text-muted)] border border-[var(--cc-border)] shrink-0">
                          {docType}
                        </span>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center justify-end gap-1.5 text-right shrink-0">
                      {isGap ? (
                        <span className="font-medium text-xs text-[var(--cc-warn)] italic">
                          Omitted in {docName} (Gap)
                        </span>
                      ) : (
                        <span className="font-mono text-xs font-semibold text-[var(--cc-text)] bg-[var(--cc-surface-2)] px-1.5 py-0.5 rounded border border-[var(--cc-border)] max-w-[12rem] truncate" title={String(ev.raw_value)}>
                          {String(ev.raw_value)}
                        </span>
                      )}
                      {ev.unit && !isGap && !String(ev.raw_value).trim().endsWith(ev.unit.trim()) && <span className="text-xs text-[var(--cc-text-muted)]">{ev.unit}</span>}
                      {ev.page && (
                        <button
                          type="button"
                          onClick={() => ev.doc && onSelectDocument?.(ev.doc, ev.page ?? undefined, ev.field, ev.bbox)}
                          disabled={!ev.doc}
                          className="text-xs text-[var(--cc-focus)] underline disabled:no-underline disabled:text-[var(--cc-text-subtle)]"
                          aria-label={ev.doc ? `Open ${docName}, page ${ev.page}` : undefined}
                        >
                          p.{ev.page}
                        </button>
                      )}
                      {path && (
                        <button
                          type="button"
                          data-testid="correct-evidence"
                          disabled={editingDisabled}
                          aria-label={`Correct ${pathLabel(path)} in ${docName}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditing(editing === editKey ? null : editKey);
                          }}
                          className="rounded border border-[var(--cc-border-strong)] px-1.5 py-0.5 text-xs font-semibold text-[var(--cc-focus)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 cursor-pointer"
                        >
                          Edit
                        </button>
                      )}
                    </div>
                  </div>
                  {state && (
                    <span
                      data-testid="correction-state"
                      className={`self-start text-xs font-bold ${state.kind === "used" ? "text-[var(--cc-ok)]" : "text-[var(--cc-warn)]"}`}
                    >
                      {state.kind === "used" && `Corrected by the agent (model read ${state.entry.original_value ?? "nothing"})`}
                      {state.kind === "pending" && `Correction pending: ${state.entry.value ?? "(cleared)"}. Recompute to apply it.`}
                      {state.kind === "undone" && "Correction undone. Recompute to restore the model's reading."}
                    </span>
                  )}
                  {path && onCorrect && editing === editKey && (
                    <CorrectionEditor
                      documentId={ev.doc}
                      documentName={docName}
                      path={path}
                      current={readCell(extractions, ev.doc, path)}
                      onSubmit={onCorrect}
                      onClose={() => setEditing(null)}
                    />
                  )}
                  </div>
                );
              })}
              {(hiddenEvidence > 0 || evidenceExpanded) && evidenceList.length > EVIDENCE_PREVIEW && (
                <button
                  type="button"
                  onClick={() => setAllEvidence((prev) => ({ ...prev, [check.check_id]: !evidenceExpanded }))}
                  className="self-start min-h-[24px] inline-flex items-center text-xs font-semibold text-[var(--cc-focus)] hover:underline cursor-pointer py-1"
                >
                  {evidenceExpanded ? "Show fewer" : `Show all ${evidenceList.length} (${hiddenEvidence} more)`}
                </button>
              )}
            </div>
          </div>
        )}
      </li>
    );
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Issues Requiring Action (Material Contradictions & Warnings) */}
      {issues.length > 0 && (
        <details open className="group rounded-[var(--cc-radius)] border border-[var(--cc-border)] bg-[var(--cc-surface)]">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-2.5 text-xs font-bold text-[var(--cc-err)] uppercase tracking-wider">
            <span>⚠️ Findings requiring attention ({issues.length})</span>
            <span className="text-xs text-[var(--cc-text-muted)] group-open:hidden">Show</span>
            <span className="hidden text-xs text-[var(--cc-text-muted)] group-open:inline">Hide</span>
          </summary>
          <div className="border-t border-[var(--cc-border)] p-2">
            <ul className="flex flex-col gap-2" aria-label="Discrepancies and warnings">{issues.map((check, i) => renderCheckItem(check, i, "issue"))}</ul>
          </div>
        </details>
      )}

      {/* Passed Checks (Accordion) */}
      {passed.length > 0 && (
        <div className="flex flex-col gap-2 mt-1">
          <button
            type="button"
            onClick={() => setShowAllPass(!showAllPass)}
            aria-expanded={showAllPass}
            className="flex items-center justify-between text-xs font-semibold text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] p-1.5 rounded hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer"
          >
            <span className="flex items-center gap-1.5 text-[var(--cc-ok)]">
              <span>✓ Verified Rules ({passed.length})</span>
            </span>
            <span className="text-xs">
              {showAllPass ? "▲ Hide verified" : `▼ Show (${passed.length} passed)`}
            </span>
          </button>

          {showAllPass && (
            <ul className="flex flex-col gap-2" aria-label="Passed checks">
              {passed.map((check, i) => renderCheckItem(check, i, "pass"))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
