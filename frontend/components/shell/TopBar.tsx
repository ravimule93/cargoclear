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
  connection: _connection = "open",
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
      {/* Brand & return breadcrumbs */}
      <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
        <Link
          href="/"
          className="flex items-center gap-1.5 font-semibold hover:opacity-85 transition-opacity"
          title="Return to Dashboard"
        >
          <span aria-hidden="true" className="text-lg sm:text-xl">🛃</span>
          <span className="tracking-tight text-sm sm:text-base font-bold text-[var(--cc-text)] hidden xs:inline">CargoClear</span>
        </Link>
        <Link
          href="/"
          className="text-[11px] text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] px-1.5 sm:px-2 py-0.5 rounded border border-[var(--cc-border)] hover:bg-[var(--cc-surface-2)] transition-colors ml-0.5 sm:ml-1"
          title="View all bundles and assessments"
        >
          <span className="hidden sm:inline">← All Bundles</span>
          <span className="sm:hidden">← All</span>
        </Link>
      </div>

      {/* Bundle context: ID, destination, status */}
      <div className="text-xs text-[var(--cc-text-muted)] sm:border-l border-[var(--cc-border)] sm:pl-3 flex flex-wrap items-center gap-1.5 sm:gap-2">
        <span className="hidden sm:inline">Bundle</span>
        <code className="font-mono font-medium text-[var(--cc-text)] text-[11px] sm:text-xs truncate max-w-[120px] sm:max-w-none">{bundle.id}</code>
        {bundle.reference && (
          <span className="hidden md:inline text-[10px] sm:text-[11px] bg-[var(--cc-surface-2)] px-1.5 py-0.5 rounded border border-[var(--cc-border)] text-[var(--cc-text-subtle)] truncate max-w-[100px]">
            {bundle.reference}
          </span>
        )}
        <span
          data-testid="bundle-destination"
          className="text-[10px] sm:text-[11px] bg-[var(--cc-surface-2)] px-1.5 py-0.5 rounded border border-[var(--cc-border)] text-[var(--cc-text-subtle)] font-medium"
        >
          To {bundle.destination_country}
        </span>
        <StatusPill status={status} />
      </div>

      {isUploading && uploadProgress && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-1.5 text-xs bg-[var(--cc-surface-2)] border border-[var(--cc-focus)]/40 px-2 py-0.5 rounded-full text-[var(--cc-text)] shrink-0"
        >
          <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-[var(--cc-focus)] border-t-transparent" />
          <span className="font-medium text-[10px] sm:text-[11px]">
            Uploading {uploadProgress.current}/{uploadProgress.total}
          </span>
        </div>
      )}

      {/* Action controls cluster */}
      <div className="ml-auto flex items-center gap-1.5 sm:gap-2 shrink-0">
        <div className="hidden lg:block">
          <ModeBadge />
        </div>
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
        <div className="hidden sm:block">
          <DocumentTypeSelect value={declared.declaredType} onChange={declared.setDeclaredType} disabled={isUploading} className="max-w-[130px] sm:max-w-[150px]" />
        </div>
        <Link
          href="/"
          className="hidden xl:flex rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-2.5 py-1 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer items-center gap-1"
          title="Create a new bundle"
        >
          <span>+ New Bundle</span>
        </Link>
        <button
          type="button"
          disabled={isUploading}
          onClick={() => fileInputRef.current?.click()}
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-2 sm:px-2.5 py-1 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 transition-colors cursor-pointer flex items-center gap-1"
        >
          {isUploading ? (
            <>
              <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-[var(--cc-text)] border-t-transparent" />
              <span className="hidden sm:inline">Uploading...</span>
            </>
          ) : (
            <>
              <span>+ Add</span>
              <span className="hidden sm:inline">Document</span>
            </>
          )}
        </button>
        <button
          type="button"
          data-testid="run-button"
          disabled={isRunning}
          aria-busy={isRunning}
          onClick={onRun}
          className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-2.5 sm:px-3 py-1 text-xs font-semibold text-white shadow-xs hover:brightness-90 disabled:opacity-50 transition-all cursor-pointer flex items-center gap-1.5 shrink-0"
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

