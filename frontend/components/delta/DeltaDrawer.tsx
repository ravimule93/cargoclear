"use client";

import { useState } from "react";
import { AssessmentIteration } from "@/lib/types";
import { ReasoningDelta } from "./ReasoningDelta";
import { AuditTimeline } from "../audit/AuditTimeline";

interface DeltaDrawerProps {
  bundleId: string;
  iterations: AssessmentIteration[];
  /** Changing this value refetches the audit chain (new iteration, run state change, upload). */
  auditRefreshKey?: string | number;
}

const TABS = [
  { id: "delta", label: "Reasoning Delta" },
  { id: "audit", label: "Audit Chain Timeline" },
] as const;

export function DeltaDrawer({ bundleId, iterations, auditRefreshKey }: DeltaDrawerProps) {
  const [activeTab, setActiveTab] = useState<"delta" | "audit">("delta");
  const latestIteration = iterations[iterations.length - 1];

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key === "ArrowRight") {
      const nextIndex = (index + 1) % TABS.length;
      setActiveTab(TABS[nextIndex].id);
    } else if (e.key === "ArrowLeft") {
      const prevIndex = (index - 1 + TABS.length) % TABS.length;
      setActiveTab(TABS[prevIndex].id);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[var(--cc-surface)]">
      <div
        role="tablist"
        aria-label="Adjudication timeline and delta views"
        className="flex border-b border-[var(--cc-border)] px-4 bg-[var(--cc-surface-2)]"
      >
        {TABS.map((tab, idx) => {
          const isSelected = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={isSelected}
              aria-controls={`panel-${tab.id}`}
              tabIndex={isSelected ? 0 : -1}
              onClick={() => setActiveTab(tab.id)}
              onKeyDown={(e) => handleKeyDown(e, idx)}
              className={`py-2 px-3 text-xs font-semibold cursor-pointer border-b-2 transition-colors ${
                isSelected
                  ? "border-[var(--cc-focus)] text-[var(--cc-focus)]"
                  : "border-transparent text-[var(--cc-text-muted)] hover:text-[var(--cc-text)]"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        className="p-4 flex-1 overflow-y-auto"
      >
        {activeTab === "delta" ? (
          <ReasoningDelta delta={latestIteration?.reasoning_delta} />
        ) : (
          <AuditTimeline bundleId={bundleId} refreshKey={auditRefreshKey} />
        )}
      </div>
    </div>
  );
}
