"use client";

import { ChangeEvent, useRef } from "react";
import Link from "next/link";
import { Bundle, Status, UserIdentity } from "@/lib/types";
import type { StreamConnection } from "@/lib/hooks/useBundleStream";
import { useDeclaredType } from "@/lib/hooks/useDeclaredType";
import { StatusPill } from "../assess/StatusPill";
import { DocumentTypeSelect } from "../upload/DocumentTypeSelect";
import { ModeBadge } from "./ModeBadge";
import { UserMenu } from "./UserMenu";

interface TopBarProps {
  bundle: Bundle;
  /** null = not assessed yet */
  status: Status | null;
  user?: UserIdentity | null;
  isRunning?: boolean;
  isUploading?: boolean;
  uploadProgress?: { current: number; total: number; filename?: string } | null;
  /** "Run analysis" until the first iteration exists, "Reassess" afterwards. */
  runMode: "analyze" | "reassess";
  connection?: StreamConnection;
  /** Visible, role="alert" message for a failed run or upload. */
  actionError?: string | null;
  onRun?: () => void;
  /** `declaredType` is set only when the person picked a type, and then for exactly one file (the picker allows one). */
  onFilesSelected?: (files: File[], declaredType?: string | null) => void;
  onLogin?: (email: string) => void;
  onLogout?: () => void;
}

export function TopBar({
  bundle,
  status,
  user,
  isRunning = false,
  isUploading = false,
  uploadProgress = null,
  runMode,
  connection = "open",
  onRun,
  onFilesSelected,
  onLogin,
  onLogout,
}: TopBarProps) {

  const fileInputRef = useRef<HTMLInputElement>(null);
  const declared = useDeclaredType(); // what the NEXT file is, if the person says (one file; cleared by every upload)

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // allow re-selecting the same file
    if (files.length === 0) return;
    onFilesSelected?.(files, declared.take());
  };

  return (
    <header className="cc-top">
      <div className="flex items-center gap-2">
        <Link
          href="/"
          className="flex items-center gap-2 font-semibold hover:opacity-85 transition-opacity"
          title="Return to Dashboard"
        >
          <span aria-hidden="true" className="text-xl">🛃</span>
          <span className="tracking-tight text-base font-bold text-[var(--cc-text)]">CargoClear</span>
        </Link>
        <Link
          href="/"
          className="text-[11px] text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] px-2 py-1 rounded border border-[var(--cc-border)] hover:bg-[var(--cc-surface-2)] transition-colors ml-1"
          title="View all bundles and assessments"
        >
          ← All Bundles
        </Link>
      </div>

      <div className="text-xs text-[var(--cc-text-muted)] border-l border-[var(--cc-border)] pl-3 flex items-center gap-2">
        <span>Bundle</span>
        <code className="font-mono font-medium text-[var(--cc-text)]">{bundle.id}</code>
        {bundle.reference && (
          <span className="text-[11px] bg-[var(--cc-surface-2)] px-1.5 py-0.5 rounded border border-[var(--cc-border)] text-[var(--cc-text-subtle)]">
            {bundle.reference}
          </span>
        )}
        <span
          data-testid="bundle-destination"
          className="text-[11px] bg-[var(--cc-surface-2)] px-1.5 py-0.5 rounded border border-[var(--cc-border)] text-[var(--cc-text-subtle)]"
        >
          To {bundle.destination_country}
        </span>
      </div>

      <div className="ml-2">
        <StatusPill status={status} />
      </div>

      {connection !== "open" && connection !== "connecting" && (
        <span
          data-testid="stream-connection"
          aria-live="polite"
          className="text-[11px] text-[var(--cc-text-muted)] flex items-center gap-1"
        >
          {connection === "polling" ? (
            <span className="rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 border border-emerald-500/20 text-[10px] font-medium">
              ⚡ Polling active
            </span>
          ) : (
            <span>Live updates: {connection}…</span>
          )}
        </span>
      )}

      {isUploading && uploadProgress && (
        <div
          role="status"
          aria-live="polite"
          className="ml-3 flex items-center gap-2 text-xs bg-[var(--cc-surface-2)] border border-[var(--cc-focus)]/40 px-2.5 py-1 rounded-full text-[var(--cc-text)]"
        >
          <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-[var(--cc-focus)] border-t-transparent" />
          <span className="font-medium text-[11px]">
            Uploading {uploadProgress.current}/{uploadProgress.total}
            {uploadProgress.filename ? `: ${uploadProgress.filename}` : ""}
          </span>
        </div>
      )}

      <div className="ml-auto flex items-center gap-3">
        <ModeBadge />
        <input
          ref={fileInputRef}
          type="file"
          multiple={declared.allowsSeveralFiles}
          accept="application/pdf,.pdf"
          className="hidden"
          data-testid="upload-input"
          aria-label="Add documents to this bundle"
          tabIndex={-1}
          onChange={handleFileChange}
        />
        <DocumentTypeSelect value={declared.declaredType} onChange={declared.setDeclaredType} disabled={isUploading} />
        <Link
          href="/"
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-3 py-1.5 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer flex items-center gap-1"
          title="Create a new bundle"
        >
          <span>+ New Bundle</span>
        </Link>
        <button
          type="button"
          disabled={isUploading}
          onClick={() => fileInputRef.current?.click()}
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-3 py-1.5 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 transition-colors cursor-pointer flex items-center gap-1.5"
        >
          {isUploading ? (
            <>
              <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-[var(--cc-text)] border-t-transparent" />
              <span>
                {uploadProgress ? `Uploading (${uploadProgress.current}/${uploadProgress.total})...` : "Uploading..."}
              </span>
            </>
          ) : (
            <span>+ Add Document</span>
          )}
        </button>
        <button
          type="button"
          data-testid="run-button"
          disabled={isRunning}
          aria-busy={isRunning}
          onClick={onRun}
          className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:brightness-90 disabled:opacity-50 transition-all cursor-pointer flex items-center gap-1.5"
        >
          {isRunning && (
            <span
              aria-hidden="true"
              className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent"
            />
          )}
          <span>{runMode === "analyze" ? "Run analysis" : "Reassess"}</span>
        </button>
        <UserMenu user={user} onLogin={onLogin} onLogout={onLogout} />
      </div>
    </header>
  );
}

