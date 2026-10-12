import { useMemo, useState } from "react";
import { CheckResult, DocumentRecord } from "@/lib/types";

interface CheckListProps {
  checks: CheckResult[];
  documents?: DocumentRecord[];
  onSelectDocument?: (documentId: string) => void;
}

const CHECK_TITLES: Record<string, string> = {
  "W-001": "Weight Balance (BoL Gross vs Packing List Net+Tare)",
  "W-002": "Packing List Internal Weight Parity",
  "H-002": "Cross-Document HS Code Alignment",
  "E-consignee": "Consignee Entity Alignment",
  "E-consignor": "Consignor Entity Alignment",
  "E-vessel": "Vessel / Voyage Identification",
  "G-001": "Tariff Classification Grounding (AHTN)",
};

export function CheckList({
  checks,
  documents = [],
  onSelectDocument,
}: CheckListProps) {
  const [showAllPass, setShowAllPass] = useState(false);

  // Quick lookup from document_id to DocumentRecord
  const docMap = useMemo(() => {
    const map = new Map<string, DocumentRecord>();
    for (const d of documents) {
      map.set(d.document_id, d);
    }
    return map;
  }, [documents]);

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

  const renderCheckItem = (check: CheckResult, index: number) => {
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

        {/* Structured Evidence Comparison Breakdown */}
        {evidenceList.length > 0 && (
          <div className="mt-1 pt-2 border-t border-[var(--cc-border)]/60 flex flex-col gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--cc-text-subtle)]">
              Compared Documents & Stated Evidence:
            </span>
            <div className="flex flex-col gap-1.5">
              {evidenceList.map((ev, evIdx) => {
                const docRecord = ev.doc ? docMap.get(ev.doc) : null;
                const docName = docRecord?.filename || ev.doc || "Unknown Document";
                const docType = docRecord?.doc_type?.replace(/_/g, " ") || "";
                const hasValue = ev.raw_value !== undefined && ev.raw_value !== null && String(ev.raw_value).trim() !== "";
                const isGap = !hasValue;

                return (
                  <div
                    key={`${ev.doc}:${ev.field}:${evIdx}`}
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
                      {ev.page && (
                        <span className="text-[10px] text-[var(--cc-text-subtle)]">
                          p.{ev.page}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
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
            {issues.map(renderCheckItem)}
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
              {passed.map(renderCheckItem)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
