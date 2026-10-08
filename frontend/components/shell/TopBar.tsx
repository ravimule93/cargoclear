"use client";

import { Bundle, Status } from "@/lib/types";
import { StatusPill } from "../assess/StatusPill";

interface TopBarProps {
  bundle: Bundle;
  status: Status;
}

export function TopBar({ bundle, status }: TopBarProps) {
  return (
    <header className="cc-top">
      <div className="flex items-center gap-2 font-semibold">
        <span aria-hidden="true" className="text-xl">🛃</span>
        <span className="tracking-tight text-base font-bold">CargoClear</span>
      </div>

      <div className="text-xs text-[var(--cc-text-muted)] border-l border-[var(--cc-border)] pl-3">
        Bundle <code className="font-mono font-medium text-[var(--cc-text)]">{bundle.id}</code>
      </div>

      <div className="ml-2">
        <StatusPill status={status} />
      </div>

      <div className="ml-auto flex items-center gap-3">
        <button
          type="button"
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer"
          onClick={() => {}}
        >
          Add Document
        </button>
        <button
          type="button"
          className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:opacity-90 transition-opacity cursor-pointer"
          onClick={() => {}}
        >
          Reassess Bundle
        </button>
      </div>
    </header>
  );
}
