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
  isCollapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}

const TABS = [
  { id: "delta", label: "Reasoning Delta" },
  { id: "audit", label: "Audit Chain Timeline" },
] as const;

export function DeltaDrawer({ bundleId, iterations, auditRefreshKey, isCollapsed, onCollapsedChange }: DeltaDrawerProps) {
  const [activeTab, setActiveTab] = useState<"delta" | "audit">("delta");
  const latestIteration = iterations[iterations.length - 1];

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key === "ArrowRight") {
      const nextIndex = (index + 1) % TABS.length;
      setActiveTab(TABS[nextIndex].id);
      document.getElementById(`tab-${TABS[nextIndex].id}`)?.focus();
    } else if (e.key === "ArrowLeft") {
      const prevIndex = (index - 1 + TABS.length) % TABS.length;
      setActiveTab(TABS[prevIndex].id);
      document.getElementById(`tab-${TABS[prevIndex].id}`)?.focus();
    }
  };

  const toggleCollapse = () => {
    onCollapsedChange(!isCollapsed);
  };

  return (
    <div className="flex flex-col h-full bg-[var(--cc-surface)]">
      <div className="flex items-center justify-between border-b border-[var(--cc-border)] px-4 bg-[var(--cc-surface-2)]">
        {/* The tablist holds ONLY tabs (ARIA: required owned elements); the collapse button is its sibling. */}
        <div role="tablist" aria-label="Audit timeline and delta views" className="flex">
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
                onClick={() => {
                  setActiveTab(tab.id);
                  if (isCollapsed) onCollapsedChange(false);
                }}
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

        <button
          type="button"
          onClick={toggleCollapse}
          aria-expanded={!isCollapsed}
          aria-controls={`panel-${activeTab}`}
          className="text-xs text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] px-2 py-1 rounded hover:bg-[var(--cc-surface)] transition-colors cursor-pointer flex items-center gap-1"
          title={isCollapsed ? "Expand Drawer" : "Collapse Drawer"}
        >
          <span className="text-[10px]">{isCollapsed ? "▲ Expand" : "▼ Collapse"}</span>
        </button>
      </div>

      {TABS.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          id={`panel-${tab.id}`}
          aria-labelledby={`tab-${tab.id}`}
          hidden={isCollapsed || activeTab !== tab.id}
          className="p-4 flex-1 overflow-y-auto"
        >
          {!isCollapsed && activeTab === tab.id && (
            tab.id === "delta" ? (
              <ReasoningDelta delta={latestIteration?.reasoning_delta} />
            ) : (
              <AuditTimeline bundleId={bundleId} refreshKey={auditRefreshKey} />
            )
          )}
        </div>
      ))}
    </div>
  );
}
