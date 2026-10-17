"use client";

import { useState, useRef, useEffect } from "react";
import { useExecutionMode } from "@/lib/hooks/useExecutionMode";
import type { AppMode } from "@/lib/types";

export function ModeBadge() {
  const {
    activeMode,
    modeStatus,
    loading,
    switching,
    error,
    switchMode,
    clearError,
  } = useExecutionMode();

  const [isOpen, setIsOpen] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);

  // Close on Escape or click outside
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        setIsOpen(false);
        clearError();
      }
    };
    const handleClickOutside = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        clearError();
      }
    };

    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen, clearError]);

  if (loading) {
    return (
      <div
        className="flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border-[var(--cc-ok-bd)] opacity-85"
        title="Checking AI execution mode..."
      >
        <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
        <span className="text-[11px] font-semibold tracking-wide uppercase">Initializing...</span>
      </div>
    );
  }

  const isLive = activeMode === "live";
  const modelName = modeStatus?.model || "gemini-2.5-flash";
  const provider = modeStatus?.provider || "Google Cloud Vertex AI";
  const region = modeStatus?.region || "asia-south1";

  const handleSelectMode = async (target: AppMode) => {
    if (target === activeMode) return;
    const ok = await switchMode(target);
    if (ok) {
      setIsOpen(false);
    }
  };

  return (
    <div className="relative inline-block" ref={modalRef}>
      {/* Interactive Trigger Button */}
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-label={`AI Execution Mode: ${isLive ? "Live GCP" : "Demo Mode"}. Click to switch.`}
        className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border cursor-pointer transition-all hover:scale-[1.02] shadow-2xs focus-visible:outline-2 focus-visible:outline-[var(--cc-focus)] ${
          isLive
            ? "bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border-[var(--cc-ok-bd)] hover:bg-[var(--cc-ok-bg)]/80"
            : "bg-[var(--cc-warn-bg)] text-[var(--cc-warn)] border-[var(--cc-warn-bd)] hover:bg-[var(--cc-warn-bg)]/80"
        }`}
        title={`Execution Mode: ${isLive ? `Live AI (${modelName})` : "Demo Mode"}. Click to configure.`}
      >
        <span
          className={`w-2 h-2 rounded-full ${
            isLive ? "bg-emerald-500 animate-pulse" : "bg-amber-500"
          }`}
        />
        <span className="text-[11px] font-semibold tracking-wide uppercase">
          {isLive ? "Live AI" : "Demo Mode"}
        </span>
        <span className="text-[10px] opacity-70">▼</span>
      </button>

      {/* Mode Selector Modal / Popover */}
      {isOpen && (
        <div
          role="dialog"
          aria-label="AI Execution Mode Configuration"
          className="absolute right-0 top-full mt-2 w-80 sm:w-96 rounded-xl border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] p-4 shadow-xl z-50 text-[var(--cc-text)] space-y-3.5 animate-in fade-in zoom-in-95 duration-150"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[var(--cc-border)] pb-2.5">
            <div>
              <h2 className="text-sm font-bold flex items-center gap-1.5">
                <span>🤖</span> AI Execution Mode
              </h2>
              <p className="text-[11px] text-[var(--cc-text-muted)]">
                Runtime model & inference flow selector
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setIsOpen(false);
                clearError();
              }}
              className="rounded p-1 text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] cursor-pointer text-xs"
              aria-label="Close mode configuration"
            >
              ✕
            </button>
          </div>

          {/* Model Specification Card */}
          <div className="rounded-lg bg-[var(--cc-surface-2)] border border-[var(--cc-border)] p-2.5 text-xs space-y-1">
            <div className="flex justify-between items-center text-[11px]">
              <span className="text-[var(--cc-text-muted)] font-medium">Provider</span>
              <span className="font-semibold text-[var(--cc-text)]">{provider}</span>
            </div>
            <div className="flex justify-between items-center text-[11px]">
              <span className="text-[var(--cc-text-muted)] font-medium">AI Model</span>
              <span className="font-mono font-semibold text-[var(--cc-focus)]">{modelName}</span>
            </div>
            <div className="flex justify-between items-center text-[11px]">
              <span className="text-[var(--cc-text-muted)] font-medium">Inference Region</span>
              <span className="font-mono text-[var(--cc-text)]">{region}</span>
            </div>
          </div>

          {/* Error Banner if switching failed */}
          {error && (
            <div role="alert" className="rounded-lg bg-[var(--cc-err-bg)] border border-[var(--cc-err-bd)] p-2.5 text-xs text-[var(--cc-err)] space-y-1">
              <div className="font-bold flex items-center gap-1">
                <span>⚠️</span> Configuration Error
              </div>
              <p className="text-[11px] leading-relaxed">{error}</p>
            </div>
          )}

          {/* Mode Options */}
          <div className="space-y-2">
            {/* Live AI Option */}
            <button
              type="button"
              disabled={switching}
              onClick={() => handleSelectMode("live")}
              className={`w-full text-left rounded-lg p-3 border transition-all cursor-pointer ${
                isLive
                  ? "border-[var(--cc-ok-bd)] bg-[var(--cc-ok-bg)]/40 shadow-xs ring-1 ring-[var(--cc-ok-bd)]"
                  : "border-[var(--cc-border)] bg-[var(--cc-surface)] hover:bg-[var(--cc-surface-2)]"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  Live AI Mode (Vertex AI)
                </span>
                {isLive && (
                  <span className="text-[10px] bg-emerald-600 text-white font-bold px-1.5 py-0.5 rounded">
                    Active
                  </span>
                )}
              </div>
              <p className="text-[11px] text-[var(--cc-text-muted)] mt-1 leading-snug">
                Multimodal vision extraction via Gemini 2.5 Flash on Vertex AI ({region}).
              </p>
            </button>

            {/* Demo Mode Option */}
            <button
              type="button"
              disabled={switching}
              onClick={() => handleSelectMode("demo")}
              className={`w-full text-left rounded-lg p-3 border transition-all cursor-pointer ${
                !isLive
                  ? "border-[var(--cc-warn-bd)] bg-[var(--cc-warn-bg)]/40 shadow-xs ring-1 ring-[var(--cc-warn-bd)]"
                  : "border-[var(--cc-border)] bg-[var(--cc-surface)] hover:bg-[var(--cc-surface-2)]"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-amber-500" />
                  Demo Mode (Hermetic Offline)
                </span>
                {!isLive && (
                  <span className="text-[10px] bg-amber-600 text-white font-bold px-1.5 py-0.5 rounded">
                    Active
                  </span>
                )}
              </div>
              <p className="text-[11px] text-[var(--cc-text-muted)] mt-1 leading-snug">
                Uses hermetic synthetic fixtures and reference rule tables without live cloud inference costs.
              </p>
            </button>
          </div>

          {/* Footer note on safety */}
          <div className="border-t border-[var(--cc-border)] pt-2 text-[10px] text-[var(--cc-text-muted)] leading-tight">
            <span>ℹ️ Session preference persisted in browser. In-progress jobs continue in their original mode.</span>
          </div>
        </div>
      )}
    </div>
  );
}
