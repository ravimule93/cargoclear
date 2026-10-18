"use client";

import { type DragEvent, lazy, Suspense, useId, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import { useDeclaredType } from "@/lib/hooks/useDeclaredType";
import { DocumentTypeSelect } from "./DocumentTypeSelect";
import type { DocumentRecord } from "@/lib/types";

const UploadStagingModal = lazy(() => import("./UploadStagingModal").then((module) => ({ default: module.UploadStagingModal })));

interface UploadDropzoneProps {
  bundleId: string;
  onUploaded?: () => void;
  label?: string;
  existingDocuments?: DocumentRecord[];
}

export function UploadDropzone({
  bundleId,
  onUploaded,
  label = "Upload Missing Document (PDF)",
  existingDocuments = [],
}: UploadDropzoneProps) {
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number; name?: string } | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [stagingOpen, setStagingOpen] = useState(false);
  const [stagingRequested, setStagingRequested] = useState(false);
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const declared = useDeclaredType(); // what the NEXT file is, if the person says (one file; cleared by every upload)
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadInFlight = useRef(false);
  const inputId = useId();
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;

  const handleFiles = async (files: File[]) => {
    if (uploadInFlight.current || stagingOpen || files.length === 0) return;
    setErrorMessage(null);
    setUploadStatus("");

    // If multiple files are provided, open the staging modal so user can assign per-file document types
    if (files.length > 1) {
      if (declared.stated) {
        setErrorMessage("Choose one PDF for the selected document type, or use multi-file staging to classify each file.");
        return;
      }
      setStagedFiles(files);
      setStagingRequested(true);
      setStagingOpen(true);
      return;
    }

    const declaredType = declared.take();
    uploadInFlight.current = true;
    setUploading(true);
    setUploadProgress({ current: 0, total: files.length, name: files[0]?.name });
    setUploadStatus(`Uploading ${files[0].name}.`);

    let uploaded = 0;
    try {
      for (let i = 0; i < files.length; i++) {
        setUploadProgress({ current: i + 1, total: files.length, name: files[i]?.name });
        await api.uploadDocument(bundleId, files[i], declaredType);
        uploaded += 1;
      }
      setUploadStatus(`${files[0].name} uploaded successfully.`);
    } catch (err: unknown) {
      console.error("Upload error", err);
      setErrorMessage(toErrorEnvelope(err).message || "Failed to upload file");
    } finally {
      uploadInFlight.current = false;
      setUploading(false);
      setUploadProgress(null);
    }
    // One callback per batch, even after a partial failure, so the page refreshes what did land.
    if (uploaded > 0) onUploaded?.();
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (uploading || stagingOpen) {
      e.dataTransfer.dropEffect = "none";
      return;
    }
    setIsDragOver(true);
  };

  const onDragLeave = () => {
    setIsDragOver(false);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    if (!uploading && !stagingOpen) void handleFiles(Array.from(e.dataTransfer.files));
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <DocumentTypeSelect value={declared.declaredType} onChange={declared.setDeclaredType} disabled={uploading} className="self-start" />
        <button
          type="button"
          disabled={uploading}
          onClick={() => {
            setStagedFiles([]);
            setStagingRequested(true);
            setStagingOpen(true);
          }}
          className="min-h-9 text-[11px] font-semibold text-[var(--cc-focus)] hover:underline cursor-pointer disabled:opacity-50"
        >
          📄 Multi-file Staging & Classification
        </button>
      </div>

      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-[var(--cc-radius)] text-center transition-all ${
          isDragOver
            ? "border-[var(--cc-focus)] bg-[var(--cc-surface-2)] scale-[1.01]"
            : "border-[var(--cc-border-strong)] hover:border-[var(--cc-focus)] hover:bg-[var(--cc-surface-2)]"
        }`}
      >
        <input
          id={inputId}
          ref={fileInputRef}
          type="file"
          multiple={declared.allowsSeveralFiles}
          accept="application/pdf,.pdf"
          className="hidden"
          tabIndex={-1}
          disabled={uploading || stagingOpen}
          data-testid="upload-input"
          aria-label={label}
          aria-describedby={`${hintId}${errorMessage ? ` ${errorId}` : ""}`}
          onChange={(e) => {
            const files = Array.from(e.currentTarget.files ?? []);
            e.currentTarget.value = "";
            void handleFiles(files);
          }}
        />

        <button
          type="button"
          disabled={uploading || stagingOpen}
          onClick={() => fileInputRef.current?.click()}
          aria-describedby={`${hintId}${errorMessage ? ` ${errorId}` : ""}`}
          aria-busy={uploading}
          className="w-full p-4 flex flex-col items-center gap-1.5 cursor-pointer disabled:opacity-60 disabled:cursor-wait rounded-[var(--cc-radius)]"
        >
          <span aria-hidden="true" className="text-xl">
            {uploading ? "⏳" : "📄"}
          </span>
          <span className="text-xs font-semibold text-[var(--cc-text)]">
            {uploading
              ? uploadProgress
                ? `Uploading ${uploadProgress.current} of ${uploadProgress.total}...`
                : "Uploading document..."
              : label}
          </span>
          <span id={hintId} className="text-[11px] text-[var(--cc-text-muted)]">
            {uploading && uploadProgress?.name
              ? uploadProgress.name
              : "Drag and drop PDFs here, or choose files"}
          </span>
        </button>

        {errorMessage && (
          <div id={errorId} role="alert" className="px-4 pb-3 text-[11px] text-[var(--cc-err)] font-medium">
            {errorMessage}
          </div>
        )}
      </div>
      <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">{uploadStatus}</p>

      {stagingRequested && <Suspense fallback={<p role="status" className="text-xs">Opening document upload…</p>}><UploadStagingModal
        bundleId={bundleId}
        isOpen={stagingOpen}
        initialFiles={stagedFiles}
        existingDocuments={existingDocuments}
        onClose={() => setStagingOpen(false)}
        onUploaded={() => onUploaded?.()}
      /></Suspense>}
    </div>
  );
}
