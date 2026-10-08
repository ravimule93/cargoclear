"use client";

import { Bundle, Status } from "@/lib/types";
import { StatusPill } from "../assess/StatusPill";

interface TopBarProps {
  bundle: Bundle;
  status: Status;
  isReassessing?: boolean;
  onReassess?: () => void;
  onAddDocumentClick?: () => void;
}

export function TopBar({
  bundle,
  status,
  isReassessing = false,
  onReassess,
  onAddDocumentClick,
}: TopBarProps) {
  return (
    <header className="cc-top">
      <div className="flex items-center gap-2 font-semibold">
        <span aria-hidden="true" className="text-xl">🛃</span>
        <span className="tracking-tight text-base font-bold text-[var(--cc-text)]">CargoClear</span>
      </div>

      <div className="text-xs text-[var(--cc-text-muted)] border-l border-[var(--cc-border)] pl-3 flex items-center gap-2">
        <span>Bundle</span>
        <code className="font-mono font-medium text-[var(--cc-text)]">{bundle.id}</code>
        {bundle.reference && (
          <span className="text-[11px] bg-[var(--cc-surface-2)] px-1.5 py-0.5 rounded border border-[var(--cc-border)] text-[var(--cc-text-subtle)]">
            {bundle.reference}
          </span>
        )}
      </div>

      <div className="ml-2">
        <StatusPill status={status} />
      </div>

      <div className="ml-auto flex items-center gap-3">
        <button
          type="button"
          onClick={onAddDocumentClick}
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-3 py-1.5 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer"
        >
          Add Document
        </button>
        <button
          type="button"
          disabled={isReassessing}
          onClick={onReassess}
          className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:opacity-90 disabled:opacity-50 transition-all cursor-pointer flex items-center gap-1.5"
        >
          {isReassessing && (
            <span
              aria-hidden="true"
              className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent"
            />
          )}
          <span>{isReassessing ? "Adjudicating..." : "Reassess Bundle"}</span>
        </button>
      </div>
    </header>
  );
}
