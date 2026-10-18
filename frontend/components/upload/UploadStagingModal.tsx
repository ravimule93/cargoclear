"use client";

import { useState, useEffect, useRef, useId } from "react";
import * as Dialog from "@radix-ui/react-dialog";
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
  const [uploadStatus, setUploadStatus] = useState("");
  const additionalInputRef = useRef<HTMLInputElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);
  const uploadInFlight = useRef(false);
  const pickerId = useId();

  // A new opening is a new batch. Parent refreshes must not reset a batch with failed files.
  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      const items: StagedFileItem[] = initialFiles.map((file) => ({
        id: crypto.randomUUID(),
        file,
        declaredType: suggestDocumentType(file.name),
        status: "staged",
      }));
      setStagedFiles(items);
      setGeneralError(null);
      setOverallProgress(null);
      setUploadStatus("");
    }
    wasOpenRef.current = isOpen;
  }, [isOpen, initialFiles]);

  const handleAddMoreFiles = (files: File[]) => {
    if (uploadInFlight.current || files.length === 0) return;
    const newItems: StagedFileItem[] = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      declaredType: suggestDocumentType(file.name),
      status: "staged",
    }));
    setStagedFiles((prev) => [...prev, ...newItems]);
    setGeneralError(null);
    setUploadStatus(`${files.length} ${files.length === 1 ? "file added" : "files added"} to the batch.`);
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
    setStagedFiles((prev) => prev.map((item) => item.status === "success" ? item : { ...item, declaredType: type }));
  };

  const handleUploadAll = async () => {
    if (uploadInFlight.current || stagedFiles.length === 0) return;
    uploadInFlight.current = true;
    setIsUploading(true);
    setGeneralError(null);
    const pendingCount = stagedFiles.filter((item) => item.status !== "success").length;

    let uploadedCount = 0;
    let pendingIndex = 0;
    const updated = stagedFiles.map((item) => ({ ...item }));

    for (let i = 0; i < updated.length; i++) {
      const item = updated[i];
      if (item.status === "success") continue;

      pendingIndex += 1;
      setOverallProgress({ current: pendingIndex, total: pendingCount, name: item.file.name });
      setUploadStatus(`Uploading ${item.file.name}, file ${pendingIndex} of ${pendingCount}.`);
      item.status = "uploading";
      item.error = undefined;
      setStagedFiles([...updated]);

      try {
        await api.uploadDocument(bundleId, item.file, item.declaredType || null);
        item.status = "success";
        item.error = undefined;
        uploadedCount++;
      } catch (err: unknown) {
        const env = toErrorEnvelope(err);
        item.status = "error";
        item.error = env.message || "Upload failed";
      }
      setStagedFiles([...updated]);
    }

    uploadInFlight.current = false;
    setIsUploading(false);
    setOverallProgress(null);

    const successfulCount = updated.filter((item) => item.status === "success").length;
    if (successfulCount === stagedFiles.length) {
      setUploadStatus(`All ${successfulCount} files uploaded successfully.`);
      if (uploadedCount > 0) onUploaded();
      onClose();
    } else {
      setUploadStatus("");
      setGeneralError(`${successfulCount} of ${stagedFiles.length} files uploaded. Review the errors below and retry. Completed files will not be uploaded again.`);
      if (uploadedCount > 0) onUploaded();
    }
  };

  // Determine which document types are fulfilled either by existing documents or staged files
  const existingTypes = new Set(existingDocuments.map((d) => d.declared_type || d.doc_type));
  const stagedTypes = new Set(stagedFiles.map((f) => f.declaredType).filter(Boolean));
  const pendingCount = stagedFiles.filter((item) => item.status !== "success").length;
  const hasErrors = stagedFiles.some((item) => item.status === "error");

  return (
    <Dialog.Root
      open={isOpen}
      onOpenChange={(open) => {
        if (!open && !uploadInFlight.current) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150" />
        <Dialog.Content
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            closeButtonRef.current?.focus();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
          }}
          onEscapeKeyDown={(event) => {
            if (uploadInFlight.current) event.preventDefault();
          }}
          onInteractOutside={(event) => event.preventDefault()}
          className="fixed left-1/2 top-1/2 z-50 w-[calc(100%_-_1.5rem)] max-w-2xl max-h-[90dvh] -translate-x-1/2 -translate-y-1/2 flex flex-col rounded-xl border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] shadow-2xl text-[var(--cc-text)] overflow-hidden"
        >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--cc-border)] p-4 bg-[var(--cc-surface-2)]">
          <div>
            <Dialog.Title className="text-base font-bold flex items-center gap-2">
              <span aria-hidden="true">📄</span> Add & Classify Trade Documents
            </Dialog.Title>
            <Dialog.Description className="text-xs text-[var(--cc-text-muted)] mt-0.5">
              Bundle: <code className="font-mono font-semibold">{bundleId}</code> • Assign customs document types before upload
            </Dialog.Description>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            disabled={isUploading}
            onClick={onClose}
            aria-label="Close dialog"
            className="min-h-9 min-w-9 rounded p-1.5 text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] hover:bg-[var(--cc-surface)] disabled:opacity-50 cursor-pointer"
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
                    <span aria-hidden="true">{isFulfilled ? "✓" : req.required ? "⚠️" : "○"}</span>
                    <span>{req.label}</span>
                    <span className="sr-only">{isFulfilled ? ": present or staged" : req.required ? ": required, not yet included" : ": optional, not included"}</span>
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
                    className="min-h-9 hover:underline text-[var(--cc-focus)] cursor-pointer"
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
                  className="min-h-9 rounded-[var(--cc-radius)] bg-[var(--cc-action)] px-3 py-1.5 font-semibold text-white hover:brightness-90 cursor-pointer"
                >
                  Choose PDF Files
                </button>
              </div>
            ) : (
              <div className="divide-y divide-[var(--cc-border)] rounded-lg border border-[var(--cc-border)] bg-[var(--cc-surface)] max-h-64 overflow-y-auto">
                {stagedFiles.map((item) => (
                  <div key={item.id} data-testid="staged-file-row" className="p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span aria-hidden="true" className="text-base shrink-0">
                        {item.status === "success" ? "✅" : item.status === "error" ? "❌" : "📄"}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-[var(--cc-text)] truncate" title={item.file.name}>
                          {item.file.name}
                        </p>
                        <p className="text-[11px] text-[var(--cc-text-muted)]">
                          {(item.file.size / 1024).toFixed(1)} KB
                        </p>
                        <p id={`${pickerId}-${item.id}-status`} className={`mt-0.5 text-[11px] ${item.status === "error" ? "text-[var(--cc-err)]" : "text-[var(--cc-text-muted)]"}`}>
                          {item.status === "success" ? "Uploaded" : item.status === "uploading" ? "Uploading…" : item.status === "error" ? `Upload failed: ${item.error}` : "Ready to upload"}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 max-w-full">
                      <select
                        aria-label={`Document type for ${item.file.name}`}
                        aria-describedby={`${pickerId}-${item.id}-status`}
                        disabled={isUploading || item.status === "success"}
                        value={item.declaredType}
                        onChange={(e) => handleChangeType(item.id, e.target.value as DeclarableDocumentType | "")}
                        className="min-h-9 min-w-0 max-w-full rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-2 py-1 text-xs text-[var(--cc-text)] cursor-pointer disabled:opacity-50"
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
                          className="min-h-9 min-w-9 text-[var(--cc-text-muted)] hover:text-[var(--cc-err)] p-1 text-xs cursor-pointer"
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
            id={pickerId}
            ref={additionalInputRef}
            type="file"
            multiple
            accept="application/pdf,.pdf"
            className="hidden"
            tabIndex={-1}
            aria-label="Choose PDF files to stage"
            aria-describedby={`${pickerId}-hint`}
            disabled={isUploading}
            data-testid="staging-file-input"
            onChange={(e) => {
              const files = Array.from(e.currentTarget.files ?? []);
              e.currentTarget.value = "";
              handleAddMoreFiles(files);
            }}
          />
          <p id={`${pickerId}-hint`} className="text-[11px] text-[var(--cc-text-muted)]">PDF files only. You can review and change each document type before uploading.</p>

          {stagedFiles.length > 0 && !isUploading && (
            <button
              type="button"
              onClick={() => additionalInputRef.current?.click()}
              className="min-h-9 inline-flex items-center gap-1 text-xs text-[var(--cc-focus)] font-medium hover:underline cursor-pointer"
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
        <div className="flex flex-wrap gap-3 items-center justify-between border-t border-[var(--cc-border)] p-3 sm:p-4 bg-[var(--cc-surface-2)]">
          <div className="min-w-0 text-xs text-[var(--cc-text-muted)]">
            <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">{uploadStatus}</p>
            {overallProgress && (
              <div>
                <span className="font-medium text-[var(--cc-text)] flex items-center gap-1.5">
                  <span aria-hidden="true" className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-[var(--cc-focus)] border-t-transparent" />
                  Uploading {overallProgress.current} of {overallProgress.total}...
                </span>
                <progress className="mt-1 h-1.5 w-full accent-[var(--cc-focus)]" max={overallProgress.total} value={overallProgress.current - 1} aria-label="Files processed in this batch" />
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={isUploading}
              onClick={onClose}
              className="min-h-9 rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-3 py-1.5 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface)] disabled:opacity-50 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={isUploading || pendingCount === 0}
              onClick={handleUploadAll}
              className="min-h-9 rounded-[var(--cc-radius)] bg-[var(--cc-action)] px-4 py-1.5 text-xs font-semibold text-white shadow-xs hover:brightness-90 disabled:opacity-50 transition-all cursor-pointer flex items-center gap-1.5"
            >
              {isUploading ? "Uploading..." : `${hasErrors ? "Retry" : "Upload"} ${pendingCount} ${pendingCount === 1 ? "File" : "Files"}`}
            </button>
          </div>
        </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
