"use client";

import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { canClear, hasUnit, pathLabel, type CellValue } from "@/lib/corrections";
import type { CorrectionRequest } from "@/lib/types";

interface CorrectionEditorProps {
  documentId: string;
  documentName: string;
  /** address of the value, e.g. "consignee" or "test_results[7]" */
  path: string;
  /** the value the extraction has now; null while it is still loading or when the address is not in it */
  current: CellValue | null;
  /** records the correction; resolves to an error message to show here, or null on success */
  onSubmit: (request: CorrectionRequest) => Promise<string | null>;
  onClose: () => void;
}

/**
 * Edit-in-place for one extracted value: the authorised agent states what the document actually says.
 * Saving the value as it already is records a confirmation (the model was right, and a person checked); anything else is a
 * correction. Nothing changes the assessment until it is recomputed.
 */
export function CorrectionEditor({ documentId, documentName, path, current, onSubmit, onClose }: CorrectionEditorProps) {
  const id = useId();
  const valueRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(current?.value ?? "");
  const [unit, setUnit] = useState(current?.unit ?? "");
  // The extraction can still be loading when the editor opens: fill the fields once it arrives, unless the person has typed.
  const touched = useRef(false);
  const [reason, setReason] = useState("");
  const [clear, setClear] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const showUnit = hasUnit(path);
  const label = pathLabel(path);
  const unchanged = !clear && value.trim() === (current?.value ?? "") && (!showUnit || unit.trim() === (current?.unit ?? ""));

  useEffect(() => {
    const returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    valueRef.current?.focus();
    return () => { if (returnTo?.isConnected) returnTo.focus({ preventScroll: true }); };
  }, []);

  const loadedValue = current?.value ?? "";
  const loadedUnit = current?.unit ?? "";
  useEffect(() => {
    if (touched.current) return;
    setValue(loadedValue);
    setUnit(loadedUnit);
  }, [loadedValue, loadedUnit]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const message = await onSubmit({
      document_id: documentId,
      path,
      value: clear ? null : value,
      unit: showUnit && !clear && unit.trim() !== "" ? unit.trim() : null,
      clear,
      reason: reason.trim() === "" ? null : reason.trim(),
    });
    setBusy(false);
    if (message === null) onClose();
    else setError(message);
  };

  return (
    <form
      onSubmit={submit}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          if (!busy) onClose();
        }
      }}
      onClick={(e) => e.stopPropagation()}
      data-testid="correction-editor"
      aria-label={`Correct ${label} in ${documentName}`}
      className="rounded border border-[var(--cc-focus)] bg-[var(--cc-surface)] p-2 flex flex-col gap-2 text-[11px]"
    >
      <div className="flex flex-col gap-0.5 text-[var(--cc-text-muted)]">
        <span className="font-semibold text-[var(--cc-text)]">
          {label} · {documentName}
        </span>
        {current === null ? (
          <span role="status">Loading the extracted value...</span>
        ) : (
          <span>
            Model read:{" "}
            <span className="font-mono">
              {current.corrected ? (current.originalValue ?? "(not stated)") : (current.value ?? "(not stated)")}
              {(current.corrected ? current.originalUnit : current.unit) ? ` ${current.corrected ? current.originalUnit : current.unit}` : ""}
            </span>
            . State what the document actually says.
          </span>
        )}
      </div>

      <div className="flex gap-2 items-end">
        <label className="flex flex-col gap-0.5 flex-1" htmlFor={`${id}-value`}>
          <span className="font-semibold text-[var(--cc-text)]">Value as printed</span>
          <input
            id={`${id}-value`}
            ref={valueRef}
            data-testid="correction-value"
            value={clear ? "" : value}
            disabled={clear || busy}
            onChange={(e) => {
              touched.current = true;
              setValue(e.target.value);
            }}
            maxLength={500}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-error` : undefined}
            autoComplete="off"
            className="rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] px-2 py-1 font-mono text-[11px] text-[var(--cc-text)] disabled:opacity-60"
          />
        </label>
        {showUnit && (
          <label className="flex flex-col gap-0.5 w-24" htmlFor={`${id}-unit`}>
            <span className="font-semibold text-[var(--cc-text)]">Unit</span>
            <input
              id={`${id}-unit`}
              data-testid="correction-unit"
              value={clear ? "" : unit}
              disabled={clear || busy}
              onChange={(e) => {
                touched.current = true;
                setUnit(e.target.value);
              }}
              maxLength={24}
              autoComplete="off"
              placeholder="KGS, MT, %"
              className="rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] px-2 py-1 font-mono text-[11px] text-[var(--cc-text)] disabled:opacity-60"
            />
          </label>
        )}
      </div>

      <label className="flex flex-col gap-0.5" htmlFor={`${id}-reason`}>
        <span className="font-semibold text-[var(--cc-text)]">Reason (optional, kept in the audit trail)</span>
        <input
          id={`${id}-reason`}
          data-testid="correction-reason"
          value={reason}
          disabled={busy}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
          autoComplete="off"
          className="rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] px-2 py-1 text-[11px] text-[var(--cc-text)]"
        />
      </label>

      {canClear(path) && (
        <label className="flex items-center gap-1.5 text-[var(--cc-text-muted)]">
          <input type="checkbox" checked={clear} disabled={busy} onChange={(e) => setClear(e.target.checked)} />
          <span>The document does not state this value</span>
        </label>
      )}

      {error && (
        <div id={`${id}-error`} role="alert" data-testid="correction-error" className="text-[var(--cc-err)] font-medium">
          {error}
        </div>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          data-testid="correction-save"
          disabled={busy || current === null || (!clear && value.trim() === "")}
          className="rounded bg-[var(--cc-action)] px-3 py-1 font-semibold text-white hover:brightness-90 disabled:opacity-50 cursor-pointer"
        >
          {busy ? "Saving..." : unchanged ? "Confirm value" : "Save correction"}
        </button>
        <button
          type="button"
          onClick={onClose}
          disabled={busy}
          className="rounded border border-[var(--cc-border-strong)] px-3 py-1 font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] cursor-pointer"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
