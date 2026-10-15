import { useMemo, useState } from "react";
import { evidencePath, pathLabel, readCell, type ExtractedDoc } from "@/lib/corrections";
import type { AppliedCorrection, CheckResult, CorrectionRequest, CorrectionsResponse, DocumentRecord } from "@/lib/types";
import { CorrectionEditor } from "./CorrectionEditor";

interface CheckListProps {
  checks: CheckResult[];
  documents?: DocumentRecord[];
  onSelectDocument?: (documentId: string) => void;
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
    return (
      <div className="text-xs text-[var(--cc-text-muted)] p-2">
        No validation checks executed yet.
      </div>
    );
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

    const friendlyTitle =
      CHECK_TITLES[check.check_id] ||
      (check.check_id.startsWith("H-003")
        ? `Certificate HS Verification (${check.check_id.replace("H-003-", "").replace(/_/g, " ")})`
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
            <span className="font-mono text-[10px] text-[var(--cc-text-subtle)]">
              {check.check_id}
            </span>
          </div>
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-bold border tracking-wider uppercase whitespace-nowrap ${badgeColor}`}
          >
            {check.severity}
          </span>
        </div>

        <p className="text-[var(--cc-text-muted)] leading-relaxed text-[11px]">
          {check.message}
        </p>

        {assumptions.length > 0 && (
          <div className="text-[11px] text-[var(--cc-text-muted)]">
            <span className="font-semibold text-[var(--cc-text)]">Assumed:</span>
            <ul className="list-disc pl-4 mt-0.5">
              {assumptions.map((assumption, i) => (
                <li key={`${check.check_id}:assumption:${i}`}>{assumption}</li>
              ))}
            </ul>
          </div>
        )}

        {check.rule_set && (
          <details className="text-[10px] text-[var(--cc-text-subtle)]">
            <summary className="cursor-pointer">
              Rule set: <span className="font-mono font-semibold">{check.rule_set}</span> (not an official source unless stated)
            </summary>
            {check.regulation_ref && <p className="mt-1 leading-relaxed">{check.regulation_ref}</p>}
          </details>
        )}

        {/* Structured Evidence Comparison Breakdown */}
        {evidenceList.length > 0 && (
          <div className="mt-1 pt-2 border-t border-[var(--cc-border)]/60 flex flex-col gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--cc-text-subtle)]">
              Compared Documents & Stated Evidence:
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
                    onClick={() => ev.doc && onSelectDocument?.(ev.doc)}
                    className={`p-1.5 rounded border text-[11px] flex items-center justify-between gap-2 transition-all ${
                      ev.doc
                        ? "cursor-pointer hover:border-[var(--cc-focus)] hover:bg-[var(--cc-surface)]"
                        : ""
                    } ${
                      isGap
                        ? "border-[var(--cc-warn-bd)]/60 bg-[var(--cc-warn-bg)]/30 text-[var(--cc-warn)]"
                        : "border-[var(--cc-border)] bg-[var(--cc-surface)] text-[var(--cc-text)]"
                    }`}
                    title={ev.doc ? `Click to view ${docName}` : undefined}
                  >
                    <div className="flex items-center gap-1.5 truncate flex-1">
                      <span aria-hidden="true" className="text-xs">
                        {isGap ? "⚠️" : "📄"}
                      </span>
                      <span className="font-semibold truncate">
                        {docName}
                      </span>
                      {docType && (
                        <span className="text-[9px] uppercase px-1 rounded bg-[var(--cc-surface-2)] text-[var(--cc-text-muted)] border border-[var(--cc-border)]">
                          {docType}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2 whitespace-nowrap text-right">
                      {isGap ? (
                        <span className="font-medium text-[10px] text-[var(--cc-warn)] italic">
                          Field Omitted / Absent (Gap)
                        </span>
                      ) : (
                        <span className="font-mono text-[11px] font-semibold text-[var(--cc-text)] bg-[var(--cc-surface-2)] px-1.5 py-0.5 rounded border border-[var(--cc-border)]">
                          {String(ev.raw_value)}
                        </span>
                      )}
                      {ev.unit && !isGap && <span className="text-[10px] text-[var(--cc-text-muted)]">{ev.unit}</span>}
                      {ev.page && (
                        <span className="text-[10px] text-[var(--cc-text-subtle)]">
                          p.{ev.page}
                        </span>
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
                          className="rounded border border-[var(--cc-border-strong)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--cc-focus)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 cursor-pointer"
                        >
                          Edit
                        </button>
                      )}
                    </div>
                  </div>
                  {state && (
                    <span
                      data-testid="correction-state"
                      className={`self-start text-[10px] font-bold ${state.kind === "used" ? "text-[var(--cc-ok)]" : "text-[var(--cc-warn)]"}`}
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
                  className="self-start text-[10px] font-semibold text-[var(--cc-focus)] hover:underline cursor-pointer"
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
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-[var(--cc-err)] uppercase tracking-wider flex items-center gap-1.5">
              <span>⚠️ Discrepancies & Warnings ({issues.length})</span>
            </span>
          </div>
          <ul className="flex flex-col gap-2" aria-label="Discrepancies and warnings">
            {issues.map((check, i) => renderCheckItem(check, i, "issue"))}
          </ul>
        </div>
      )}

      {/* Passed Checks (Accordion) */}
      {passed.length > 0 && (
        <div className="flex flex-col gap-2 mt-1">
          <button
            type="button"
            onClick={() => setShowAllPass(!showAllPass)}
            className="flex items-center justify-between text-xs font-semibold text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] p-1.5 rounded hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer"
          >
            <span className="flex items-center gap-1.5 text-[var(--cc-ok)]">
              <span>✓ Verified Rules ({passed.length})</span>
            </span>
            <span className="text-[10px]">
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
