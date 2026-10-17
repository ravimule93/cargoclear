"use client";

import { DragEvent, useRef, useState } from "react";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import { useDeclaredType } from "@/lib/hooks/useDeclaredType";
import { DocumentTypeSelect } from "./DocumentTypeSelect";
import { UploadStagingModal } from "./UploadStagingModal";
import type { DocumentRecord } from "@/lib/types";

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
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const declared = useDeclaredType(); // what the NEXT file is, if the person says (one file; cleared by every upload)
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputId = `upload-input-${bundleId}`;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;

    // If multiple files are provided, open the staging modal so user can assign per-file document types
    if (files.length > 1) {
      setStagedFiles(Array.from(files));
      setStagingOpen(true);
      return;
    }

    const declaredType = declared.take();
    setUploading(true);
    setUploadProgress({ current: 0, total: files.length, name: files[0]?.name });
    setErrorMessage(null);

    let uploaded = 0;
    try {
      for (let i = 0; i < files.length; i++) {
        setUploadProgress({ current: i + 1, total: files.length, name: files[i]?.name });
        await api.uploadDocument(bundleId, files[i], declaredType);
        uploaded += 1;
      }
    } catch (err: unknown) {
      console.error("Upload error", err);
      setErrorMessage(toErrorEnvelope(err).message || "Failed to upload file");
    } finally {
      setUploading(false);
      setUploadProgress(null);
    }
    // One callback per batch, even after a partial failure, so the page refreshes what did land.
    if (uploaded > 0) onUploaded?.();
  };

  const onDragOver = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const onDragLeave = () => {
    setIsDragOver(false);
  };

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    handleFiles(e.dataTransfer.files);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <DocumentTypeSelect value={declared.declaredType} onChange={declared.setDeclaredType} disabled={uploading} className="self-start" />
        <button
          type="button"
          onClick={() => {
            setStagedFiles([]);
            setStagingOpen(true);
          }}
          className="text-[11px] font-semibold text-[var(--cc-focus)] hover:underline cursor-pointer"
        >
          📄 Multi-file Staging & Classification
        </button>
      </div>

      <label
        htmlFor={inputId}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-[var(--cc-radius)] p-4 text-center cursor-pointer transition-all ${
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
          accept="application/pdf"
          className="sr-only"
          data-testid="upload-input"
          aria-describedby={`${hintId}${errorMessage ? ` ${errorId}` : ""}`}
          onChange={(e) => handleFiles(e.target.files)}
        />

        <div className="flex flex-col items-center gap-1.5">
          <span aria-hidden="true" className="text-xl">
            {uploading ? "⏳" : "📄"}
          </span>
          <div className="text-xs font-semibold text-[var(--cc-text)]">
            {uploading
              ? uploadProgress
                ? `Uploading ${uploadProgress.current} of ${uploadProgress.total}...`
                : "Uploading document..."
              : label}
          </div>
          <p id={hintId} className="text-[11px] text-[var(--cc-text-muted)]">
            {uploading && uploadProgress?.name
              ? uploadProgress.name
              : "Drag & drop trade PDF or browse file"}
          </p>
        </div>

        {errorMessage && (
          <div id={errorId} role="alert" className="mt-2 text-[11px] text-[var(--cc-err)] font-medium">
            {errorMessage}
          </div>
        )}
      </label>

      <UploadStagingModal
        bundleId={bundleId}
        isOpen={stagingOpen}
        initialFiles={stagedFiles}
        existingDocuments={existingDocuments}
        onClose={() => setStagingOpen(false)}
        onUploaded={() => {
          setStagingOpen(false);
          onUploaded?.();
        }}
      />
    </div>
  );
}
