"use client";

import { useMeta } from "@/lib/hooks/useMeta";

export function ModeBadge() {
  const { meta, loading, error } = useMeta();

  if (loading) {
    return (
      <div
        className="flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border-[var(--cc-ok-bd)] opacity-85"
        title="Live GCP Mode: Initializing connection to Vertex AI"
      >
        <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
        <span className="text-[11px] font-semibold tracking-wide uppercase">Live GCP</span>
      </div>
    );
  }

  if (error || !meta) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-[var(--cc-err)] border border-[var(--cc-err)]/30 bg-[var(--cc-err)]/10 rounded-full px-2.5 py-0.5" title={error ?? "Backend offline"}>
        <span className="w-1.5 h-1.5 rounded-full bg-[var(--cc-err)]" />
        <span className="text-[11px] font-medium">Offline</span>
      </div>
    );
  }

  const isLive = meta.app_mode === "live";

  return (
    <div
      className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border ${
        // theme tokens, not fixed palette colors: they carry the contrast ratios for light and dark mode
        isLive
          ? "bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border-[var(--cc-ok-bd)]"
          : "bg-[var(--cc-warn-bg)] text-[var(--cc-warn)] border-[var(--cc-warn-bd)]"
      }`}
      title={
        isLive
          ? "Live GCP Mode: Multimodal extraction powered by Gemini 2.5 Flash on Vertex AI"
          : "Demo Mode: Evaluates synthetic fixtures without contacting GCP"
      }
    >
      <span
        className={`w-2 h-2 rounded-full ${
          isLive ? "bg-emerald-500 animate-pulse" : "bg-amber-500"
        }`}
      />
      <span className="text-[11px] font-semibold tracking-wide uppercase">
        {isLive ? "Live GCP" : "Demo Mode"}
      </span>
    </div>
  );
}
