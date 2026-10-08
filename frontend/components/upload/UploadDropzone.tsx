"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";

interface UploadDropzoneProps {
  bundleId: string;
  onUploaded?: () => void;
}

export function UploadDropzone({ bundleId, onUploaded }: UploadDropzoneProps) {
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);

    try {
      for (let i = 0; i < files.length; i++) {
        await api.uploadDocument(bundleId, files[i]);
      }
      onUploaded?.();
    } catch (err) {
      console.error("Upload failed", err);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      onClick={() => fileInputRef.current?.click()}
      className="border-2 border-dashed border-[var(--cc-border-strong)] rounded-[var(--cc-radius)] p-4 text-center cursor-pointer hover:bg-[var(--cc-surface-2)] transition-colors"
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="application/pdf"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
      <div className="text-xs font-semibold text-[var(--cc-text)]">
        {uploading ? "Uploading trade documents..." : "Upload Missing Document (PDF)"}
      </div>
      <p className="text-[11px] text-[var(--cc-text-muted)] mt-1">
        Drag & drop or browse to satisfy requirements
      </p>
    </div>
  );
}
