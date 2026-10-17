"use client";

import { ChangeEvent, useRef, useState } from "react";
import Link from "next/link";
import { Bundle, Status, UserIdentity } from "@/lib/types";
import type { StreamConnection } from "@/lib/hooks/useBundleStream";
import { useDeclaredType } from "@/lib/hooks/useDeclaredType";
import { StatusPill } from "../assess/StatusPill";
import { UploadStagingModal } from "../upload/UploadStagingModal";
import { ModeBadge } from "./ModeBadge";
import { ThemeToggle } from "./ThemeToggle";
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
  onRefresh?: () => void;
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
  onRefresh,
  onLogin,
  onLogout,
}: TopBarProps) {
  const [stagingOpen, setStagingOpen] = useState(false);
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
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
      {/* Brand & navigation breadcrumbs */}
      <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
        <Link
          href="/"
          className="flex items-center gap-1.5 font-bold hover:opacity-85 transition-opacity"
          title="Return to Dashboard"
        >
          <span aria-hidden="true" className="text-xl">🛃</span>
          <span className="tracking-tight text-sm sm:text-base font-bold text-[var(--cc-text)]">
            CargoClear<span className="text-[var(--cc-focus)] font-semibold">-JAPAC</span>
          </span>
        </Link>
        <span className="text-[var(--cc-text-muted)] opacity-30 select-none">/</span>
        <Link
          href="/"
          className="text-xs font-medium text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] px-2 py-0.5 rounded border border-[var(--cc-border)] hover:bg-[var(--cc-surface-2)] transition-colors inline-flex items-center gap-1"
          title="View all bundles and assessments"
        >
          <span className="hidden sm:inline">← All Bundles</span>
          <span className="sm:hidden">← All</span>
        </Link>
        <Link
          href="/"
          className="hidden md:inline-flex rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-2 py-0.5 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] transition-colors items-center gap-1"
          title="Create a new bundle"
        >
          <span>+ New</span>
        </Link>
      </div>

      {/* Bundle context: ID, destination, status, docs count */}
      <div className="text-xs text-[var(--cc-text-muted)] flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 bg-[var(--cc-surface-2)] px-2 py-0.5 rounded border border-[var(--cc-border)]">
          <span className="text-[10px] uppercase font-bold text-[var(--cc-text-subtle)]">Bundle</span>
          <code className="font-mono font-semibold text-[var(--cc-text)] text-xs truncate max-w-[130px] sm:max-w-none" title={bundle.id}>
            {bundle.id}
          </code>
        </div>
        {bundle.reference && (
          <span className="hidden md:inline-block text-[11px] bg-[var(--cc-surface-2)] px-2 py-0.5 rounded border border-[var(--cc-border)] text-[var(--cc-text-subtle)] font-medium truncate max-w-[120px]" title={bundle.reference}>
            Ref: {bundle.reference}
          </span>
        )}
        <span
          data-testid="bundle-destination"
          className="text-[11px] bg-[var(--cc-surface-2)] px-2 py-0.5 rounded border border-[var(--cc-border)] text-[var(--cc-text)] font-medium inline-flex items-center gap-1"
        >
          To {bundle.destination_country}
        </span>
        {bundle.documents && bundle.documents.length > 0 && (
          <span
            className="hidden sm:inline-flex items-center gap-1 text-[11px] bg-[var(--cc-surface-2)] px-2 py-0.5 rounded border border-[var(--cc-border)] text-[var(--cc-text-subtle)] font-medium"
            title={`${bundle.documents.length} document(s) in this bundle`}
          >
            <span>📁 {bundle.documents.length} {bundle.documents.length === 1 ? "doc" : "docs"}</span>
          </span>
        )}
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
        <ThemeToggle />
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="application/pdf,.pdf"
          className="hidden"
          data-testid="upload-input"
          aria-label="Add documents to this bundle"
          tabIndex={-1}
          onChange={handleFileChange}
        />
        <button
          type="button"
          data-testid="classify-upload-button"
          disabled={isUploading}
          onClick={() => {
            setStagedFiles([]);
            setStagingOpen(true);
          }}
          title="Open multi-file staging and document type classification modal"
          className="rounded-[var(--cc-radius)] border border-[var(--cc-focus)] bg-[var(--cc-surface-2)] px-2.5 sm:px-3 py-1 text-xs font-semibold text-[var(--cc-focus)] hover:brightness-95 disabled:opacity-50 transition-colors cursor-pointer flex items-center gap-1.5 shrink-0"
        >
          <span>📄</span>
          <span>Classify & Upload</span>
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

      <UploadStagingModal
        bundleId={bundle.id}
        isOpen={stagingOpen}
        initialFiles={stagedFiles}
        existingDocuments={bundle.documents ?? []}
        onClose={() => setStagingOpen(false)}
        onUploaded={() => {
          setStagingOpen(false);
          onRefresh?.();
        }}
      />
    </header>
  );
}

