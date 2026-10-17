"use client";

import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import {
  DECLARABLE_DOCUMENT_TYPES,
  DeclarableDocumentType,
  NO_DECLARED_TYPE,
  suggestDocumentType,
} from "@/lib/documentTypes";
import type { DocumentRecord } from "@/lib/types";

export interface StagedFileItem {
  id: string;
  file: File;
  declaredType: DeclarableDocumentType | "";
  status: "staged" | "uploading" | "success" | "error";
  error?: string;
}

interface UploadStagingModalProps {
  bundleId: string;
  isOpen: boolean;
  initialFiles?: File[];
  existingDocuments?: DocumentRecord[];
  onClose: () => void;
  onUploaded: () => void;
}

const REQUIRED_CUSTOMS_TYPES = [
  { value: "COMMERCIAL_INVOICE", label: "Commercial Invoice", required: true },
  { value: "BILL_OF_LADING", label: "Bill of Lading / AWB", required: true },
  { value: "PACKING_LIST", label: "Packing List", required: true },
  { value: "MILL_TEST_CERTIFICATE", label: "Mill Test Cert (Steel/Pipe)", required: false },
  { value: "CERTIFICATE_OF_ORIGIN", label: "Certificate of Origin", required: false },
] as const;

export function UploadStagingModal({
  bundleId,
  isOpen,
  initialFiles = [],
  existingDocuments = [],
  onClose,
  onUploaded,
}: UploadStagingModalProps) {
  const [stagedFiles, setStagedFiles] = useState<StagedFileItem[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [overallProgress, setOverallProgress] = useState<{ current: number; total: number; name?: string } | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const additionalInputRef = useRef<HTMLInputElement>(null);

  // Initialize staged files when modal opens with new initialFiles
  useEffect(() => {
    if (initialFiles.length > 0) {
      const items: StagedFileItem[] = initialFiles.map((file, idx) => ({
        id: `${file.name}-${file.size}-${idx}-${Date.now()}`,
        file,
        declaredType: suggestDocumentType(file.name),
        status: "staged",
      }));
      setStagedFiles(items);
      setGeneralError(null);
    }
  }, [initialFiles]);

  if (!isOpen) return null;

  const handleAddMoreFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const newItems: StagedFileItem[] = Array.from(files).map((file, idx) => ({
      id: `${file.name}-${file.size}-${idx}-${Date.now()}`,
      file,
      declaredType: suggestDocumentType(file.name),
      status: "staged",
    }));
    setStagedFiles((prev) => [...prev, ...newItems]);
  };

  const handleRemoveItem = (id: string) => {
    if (isUploading) return;
    setStagedFiles((prev) => prev.filter((item) => item.id !== id));
  };

  const handleChangeType = (id: string, newType: DeclarableDocumentType | "") => {
    setStagedFiles((prev) =>
      prev.map((item) => (item.id === id ? { ...item, declaredType: newType } : item))
    );
  };

  const handleSetAll = (type: DeclarableDocumentType | "") => {
    setStagedFiles((prev) => prev.map((item) => ({ ...item, declaredType: type })));
  };

  const handleUploadAll = async () => {
    if (stagedFiles.length === 0) return;
    setIsUploading(true);
    setGeneralError(null);
    setOverallProgress({ current: 0, total: stagedFiles.length });

    let successfulCount = 0;
    const updated = [...stagedFiles];

    for (let i = 0; i < updated.length; i++) {
      const item = updated[i];
      if (item.status === "success") {
        successfulCount++;
        continue;
      }

      setOverallProgress({ current: i + 1, total: updated.length, name: item.file.name });
      item.status = "uploading";
      setStagedFiles([...updated]);

      try {
        await api.uploadDocument(bundleId, item.file, item.declaredType || null);
        item.status = "success";
        item.error = undefined;
        successfulCount++;
      } catch (err: unknown) {
        const env = toErrorEnvelope(err);
        item.status = "error";
        item.error = env.message || "Upload failed";
      }
      setStagedFiles([...updated]);
    }

    setIsUploading(false);
    setOverallProgress(null);

    if (successfulCount === stagedFiles.length) {
      onUploaded();
      onClose();
    } else if (successfulCount > 0) {
      onUploaded();
      setGeneralError(`Uploaded ${successfulCount} of ${stagedFiles.length} files. Review errors below.`);
    } else {
      setGeneralError("Upload failed for all selected files. Please check file format and limits.");
    }
  };

  // Determine which document types are fulfilled either by existing documents or staged files
  const existingTypes = new Set(existingDocuments.map((d) => d.declared_type || d.doc_type));
  const stagedTypes = new Set(stagedFiles.map((f) => f.declaredType).filter(Boolean));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Upload and Classify Trade Documents"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-3 sm:p-4 animate-in fade-in duration-150"
    >
      <div className="relative w-full max-w-2xl max-h-[90vh] flex flex-col rounded-xl border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] shadow-2xl text-[var(--cc-text)] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--cc-border)] p-4 bg-[var(--cc-surface-2)]">
          <div>
            <h2 className="text-base font-bold flex items-center gap-2">
              <span>📄</span> Add & Classify Trade Documents
            </h2>
            <p className="text-xs text-[var(--cc-text-muted)] mt-0.5">
              Bundle: <code className="font-mono font-semibold">{bundleId}</code> • Assign customs document types before upload
            </p>
          </div>
          <button
            type="button"
            disabled={isUploading}
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded p-1.5 text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] hover:bg-[var(--cc-surface)] disabled:opacity-50 cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Required Documents Checklist */}
          <div className="rounded-lg border border-[var(--cc-border)] bg-[var(--cc-surface-2)] p-3 text-xs space-y-2">
            <span className="font-semibold text-[11px] uppercase tracking-wider text-[var(--cc-text-subtle)]">
              Customs Package Coverage
            </span>
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {REQUIRED_CUSTOMS_TYPES.map((req) => {
                const isFulfilled = existingTypes.has(req.value) || stagedTypes.has(req.value);
                return (
                  <span
                    key={req.value}
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium border ${
                      isFulfilled
                        ? "bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border-[var(--cc-ok-bd)]"
                        : req.required
                        ? "bg-[var(--cc-warn-bg)] text-[var(--cc-warn)] border-[var(--cc-warn-bd)]"
                        : "bg-[var(--cc-surface)] text-[var(--cc-text-muted)] border-[var(--cc-border)]"
                    }`}
                  >
                    <span>{isFulfilled ? "✓" : req.required ? "⚠️" : "○"}</span>
                    <span>{req.label}</span>
                    {req.required && !isFulfilled && <span className="text-[9px] font-bold uppercase">(Req)</span>}
                  </span>
                );
              })}
            </div>
          </div>

          {/* Staged File List */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-[var(--cc-text)]">
                Files to Upload ({stagedFiles.length})
              </span>
              {stagedFiles.length > 1 && !isUploading && (
                <div className="flex items-center gap-1.5 text-[11px]">
                  <span className="text-[var(--cc-text-muted)]">Quick assign:</span>
                  <button
                    type="button"
                    onClick={() => handleSetAll(NO_DECLARED_TYPE)}
                    className="hover:underline text-[var(--cc-focus)] cursor-pointer"
                  >
                    Auto-detect all
                  </button>
                </div>
              )}
            </div>

            {stagedFiles.length === 0 ? (
              <div className="rounded-lg border-2 border-dashed border-[var(--cc-border-strong)] p-6 text-center text-xs text-[var(--cc-text-muted)] space-y-2">
                <p>No documents staged yet.</p>
                <button
                  type="button"
                  onClick={() => additionalInputRef.current?.click()}
                  className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5 font-semibold text-white hover:brightness-90 cursor-pointer"
                >
                  Choose PDF Files
                </button>
              </div>
            ) : (
              <div className="divide-y divide-[var(--cc-border)] rounded-lg border border-[var(--cc-border)] bg-[var(--cc-surface)] max-h-64 overflow-y-auto">
                {stagedFiles.map((item) => (
                  <div key={item.id} className="p-2.5 flex items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span aria-hidden="true" className="text-base shrink-0">
                        {item.status === "success" ? "✅" : item.status === "error" ? "❌" : "📄"}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-[var(--cc-text)] truncate" title={item.file.name}>
                          {item.file.name}
                        </p>
                        <p className="text-[10px] text-[var(--cc-text-muted)]">
                          {(item.file.size / 1024).toFixed(1)} KB
                          {item.error && <span className="text-[var(--cc-err)] font-bold ml-1.5">— {item.error}</span>}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <select
                        aria-label={`Document type for ${item.file.name}`}
                        disabled={isUploading || item.status === "success"}
                        value={item.declaredType}
                        onChange={(e) => handleChangeType(item.id, e.target.value as DeclarableDocumentType | "")}
                        className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-2 py-1 text-xs text-[var(--cc-text)] cursor-pointer disabled:opacity-50"
                      >
                        <option value={NO_DECLARED_TYPE}>Type: Auto-detect by AI</option>
                        {DECLARABLE_DOCUMENT_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>

                      {!isUploading && item.status !== "success" && (
                        <button
                          type="button"
                          onClick={() => handleRemoveItem(item.id)}
                          aria-label={`Remove ${item.file.name}`}
                          className="text-[var(--cc-text-muted)] hover:text-[var(--cc-err)] p-1 text-xs cursor-pointer"
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Add more files picker */}
          <input
            ref={additionalInputRef}
            type="file"
            multiple
            accept="application/pdf,.pdf"
            className="hidden"
            data-testid="staging-file-input"
            onChange={(e) => handleAddMoreFiles(e.target.files)}
          />

          {stagedFiles.length > 0 && !isUploading && (
            <button
              type="button"
              onClick={() => additionalInputRef.current?.click()}
              className="inline-flex items-center gap-1 text-xs text-[var(--cc-focus)] font-medium hover:underline cursor-pointer"
            >
              <span>+ Add more files to batch</span>
            </button>
          )}

          {generalError && (
            <div role="alert" className="rounded-lg bg-[var(--cc-err-bg)] border border-[var(--cc-err-bd)] p-2.5 text-xs text-[var(--cc-err)]">
              {generalError}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between border-t border-[var(--cc-border)] p-3 sm:p-4 bg-[var(--cc-surface-2)]">
          <div className="text-xs text-[var(--cc-text-muted)]">
            {overallProgress && (
              <span className="font-medium text-[var(--cc-text)] flex items-center gap-1.5">
                <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-[var(--cc-focus)] border-t-transparent" />
                Uploading {overallProgress.current} of {overallProgress.total}...
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={isUploading}
              onClick={onClose}
              className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-3 py-1.5 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface)] disabled:opacity-50 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={isUploading || stagedFiles.length === 0}
              onClick={handleUploadAll}
              className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-4 py-1.5 text-xs font-semibold text-white shadow-xs hover:brightness-90 disabled:opacity-50 transition-all cursor-pointer flex items-center gap-1.5"
            >
              {isUploading ? "Uploading..." : `Upload ${stagedFiles.length} ${stagedFiles.length === 1 ? "File" : "Files"}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
