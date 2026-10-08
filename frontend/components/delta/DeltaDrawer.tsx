"use client";

import { useState } from "react";
import { AssessmentIteration } from "@/lib/types";
import { ReasoningDelta } from "./ReasoningDelta";
import { AuditTimeline } from "../audit/AuditTimeline";

interface DeltaDrawerProps {
  iterations: AssessmentIteration[];
}

export function DeltaDrawer({ iterations }: DeltaDrawerProps) {
  const [activeTab, setActiveTab] = useState<"delta" | "audit">("delta");
  const latestIteration = iterations[iterations.length - 1];

  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b border-[var(--cc-border)] px-4 bg-[var(--cc-surface-2)]">
        <button
          type="button"
          onClick={() => setActiveTab("delta")}
          className={`py-2 px-3 text-xs font-semibold cursor-pointer border-b-2 transition-colors ${
            activeTab === "delta"
              ? "border-[var(--cc-focus)] text-[var(--cc-focus)]"
              : "border-transparent text-[var(--cc-text-muted)] hover:text-[var(--cc-text)]"
          }`}
        >
          Reasoning Delta
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("audit")}
          className={`py-2 px-3 text-xs font-semibold cursor-pointer border-b-2 transition-colors ${
            activeTab === "audit"
              ? "border-[var(--cc-focus)] text-[var(--cc-focus)]"
              : "border-transparent text-[var(--cc-text-muted)] hover:text-[var(--cc-text)]"
          }`}
        >
          Audit Chain Timeline
        </button>
      </div>

      <div className="p-4 flex-1 overflow-y-auto">
        {activeTab === "delta" ? (
          <ReasoningDelta delta={latestIteration?.reasoning_delta} />
        ) : (
          <AuditTimeline />
        )}
      </div>
    </div>
  );
}
