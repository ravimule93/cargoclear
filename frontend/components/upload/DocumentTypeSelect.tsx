"use client";

import { ChangeEvent } from "react";
import { DECLARABLE_DOCUMENT_TYPES, NO_DECLARED_TYPE } from "@/lib/documentTypes";

interface DocumentTypeSelectProps {
  /** "" = nothing stated (NO_DECLARED_TYPE), else one of the six types. */
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
}

/**
 * "What is the next file?" The answer is optional and applies to ONE file, the next one chosen: the upload sends it as
 * `declared_type`, and the assessment warns (T-001) when the model reads another type. The owner resets it after each upload so
 * that a stale choice never labels an unrelated file.
 */
export function DocumentTypeSelect({ value, onChange, disabled = false, className = "" }: DocumentTypeSelectProps) {
  return (
    <select
      data-testid="declared-type-select"
      aria-label="Type of the next document (optional)"
      title="Say what the next file is. If the model reads another type, the assessment warns. It applies to one file."
      value={value}
      disabled={disabled}
      onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      className={`rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] px-2 py-1.5 text-xs text-[var(--cc-text)] disabled:opacity-50 cursor-pointer ${className}`}
    >
      <option value={NO_DECLARED_TYPE}>Type: not stated</option>
      {DECLARABLE_DOCUMENT_TYPES.map((type) => (
        <option key={type.value} value={type.value}>
          {type.label}
        </option>
      ))}
    </select>
  );
}
