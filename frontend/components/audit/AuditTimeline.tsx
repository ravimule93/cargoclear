"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import type { AuditEvent, AuditResponse, AuditSignature } from "@/lib/types";

interface AuditTimelineProps {
  bundleId: string;
  /** Changing this value refetches the chain (e.g. a new iteration arrived). */
  refreshKey?: string | number;
}

const SHORT_HASH_LENGTH = 12;

function shortHash(hash: string): string {
  // "GENESIS" and other short markers are shown whole
  return hash.length > SHORT_HASH_LENGTH ? `${hash.slice(0, SHORT_HASH_LENGTH)}…` : hash;
}

/** One line of detail for the events a person causes (corrections); the machine events need none. */
function describe(evt: AuditEvent): string | null {
  const p = evt.payload as Record<string, unknown>;
  const shown = (value: unknown, fallback: string) => (value === null || value === undefined || value === "" ? fallback : String(value));
  switch (evt.event_type) {
    case "FIELD_CORRECTED":
      return `${shown(p.path, "?")} in ${shown(p.document_id, "?")}: ${shown(p.original_value, "(not stated)")} → ${shown(p.value, "(cleared)")}${
        p.reason ? ` — ${String(p.reason)}` : ""
      }`;
    case "FIELD_CONFIRMED":
      return `${shown(p.path, "?")} in ${shown(p.document_id, "?")}: confirmed as ${shown(p.value, "(not stated)")}`;
    case "CORRECTION_REVERTED":
      return `undid ${shown(p.reverts, "?")} (${shown(p.path, "?")} in ${shown(p.document_id, "?")})${p.reason ? ` — ${String(p.reason)}` : ""}`;
    case "AUDIT_HEAD_SIGNED":
      return `signed the chain head at #${shown(p.signed_seq, "?")} (${p.signer === "kms" ? "Cloud KMS" : "demo key, not KMS"})`;
    case "AUDIT_SIGNING_FAILED":
      return `signing the chain head failed (${shown(p.error_type, "error")}); the chain itself is unaffected`;
    default:
      return null;
  }
}

const SIGNER_LABEL: Record<string, string> = { kms: "Cloud KMS key", "local-demo": "demo key, not KMS" };

/** The one-line answer to "is this history signed, and does the signature hold?" */
function describeSignature(signature: AuditSignature): { text: string; tone: "ok" | "warn" | "err" } {
  const who = SIGNER_LABEL[signature.signer ?? ""] ?? signature.signer ?? "unknown key";
  switch (signature.status) {
    case "SIGNED":
      return { text: `Head signed through #${signature.signed_seq} (${who})`, tone: "ok" };
    case "PARTIAL":
      return {
        text: `Signed through #${signature.signed_seq} (${who}); ${signature.unsigned_events} later event${signature.unsigned_events === 1 ? "" : "s"} not signed yet`,
        tone: "warn",
      };
    case "UNSIGNED":
      return { text: "Head not signed yet", tone: "warn" };
    case "INVALID":
      return { text: "A signature does NOT verify: the history may have been rewritten", tone: "err" };
    case "UNVERIFIED":
      return { text: "Signed, but the public key could not be retrieved to verify it", tone: "warn" };
    default:
      return { text: "Signing is not configured for this service", tone: "warn" };
  }
}

const TONE_CLASS = {
  ok: "text-[var(--cc-ok)] bg-[var(--cc-ok-bg)] border-[var(--cc-ok-bd)]",
  warn: "text-[var(--cc-warn)] bg-[var(--cc-warn-bg)] border-[var(--cc-warn-bd)]",
  err: "text-[var(--cc-err)] bg-[var(--cc-err-bg)] border-[var(--cc-err-bd)]",
} as const;

export function AuditTimeline({ bundleId, refreshKey }: AuditTimelineProps) {
  const [audit, setAudit] = useState<AuditResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getAudit(bundleId)
      .then((response) => {
        if (cancelled) return;
        setAudit(response);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(toErrorEnvelope(err).message);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [bundleId, refreshKey, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const [signing, setSigning] = useState(false);
  const [signError, setSignError] = useState<string | null>(null);
  const signNow = useCallback(async () => {
    setSigning(true);
    setSignError(null);
    try {
      await api.signAuditHead(bundleId);
      setAttempt((n) => n + 1);
    } catch (err: unknown) {
      setSignError(toErrorEnvelope(err).message);
    } finally {
      setSigning(false);
    }
  }, [bundleId]);

  if (error) {
    return (
      <div role="alert" className="text-xs text-[var(--cc-err)] flex items-center gap-3">
        <span>Could not load audit chain: {error}</span>
        <button
          type="button"
          onClick={retry}
          className="px-2 py-0.5 rounded border border-[var(--cc-border-strong)] text-[var(--cc-text)] cursor-pointer"
        >
          Retry
        </button>
      </div>
    );
  }

  // Keep showing the previous chain while a refetch is in flight; only the first load is a blank state.
  if (!audit) {
    return (
      <div role="status" aria-busy={loading} className="text-xs text-[var(--cc-text-muted)]">
        Loading audit chain...
      </div>
    );
  }

  const badgeText = audit.verified ? "Chain verified" : `Chain BROKEN: ${audit.error ?? "unknown reason"}`;

  return (
    <div className="flex flex-col gap-2 max-w-4xl" aria-label="Tamper-evident audit chain">
      <div
        data-testid="audit-verified-badge"
        className={`self-start rounded-full border px-2.5 py-0.5 text-xs font-semibold ${
          audit.verified
            ? "text-[var(--cc-ok)] bg-[var(--cc-ok-bg)] border-[var(--cc-ok-bd)]"
            : "text-[var(--cc-err)] bg-[var(--cc-err-bg)] border-[var(--cc-err-bd)]"
        }`}
      >
        {badgeText}
      </div>

      {audit.signature && (
        <div className="flex flex-col gap-1">
          {(() => {
            const summary = describeSignature(audit.signature);
            const canSign = audit.signature.configured && ["UNSIGNED", "PARTIAL"].includes(audit.signature.status);
            return (
              <div className="flex flex-wrap items-center gap-2">
                <div
                  data-testid="audit-signature-badge"
                  data-status={audit.signature.status}
                  className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE_CLASS[summary.tone]}`}
                >
                  {summary.text}
                </div>
                {canSign && (
                  <button
                    type="button"
                    data-testid="audit-sign-now"
                    disabled={signing}
                    onClick={() => void signNow()}
                    className="rounded border border-[var(--cc-border-strong)] px-2 py-0.5 text-[11px] font-semibold text-[var(--cc-focus)] hover:bg-[var(--cc-surface-2)] disabled:opacity-50 cursor-pointer"
                  >
                    {signing ? "Signing..." : "Sign now"}
                  </button>
                )}
              </div>
            );
          })()}
          {audit.signature.failures > 0 && (
            <p role="status" className="text-[11px] text-[var(--cc-warn)]">
              {audit.signature.failures} signing failure{audit.signature.failures === 1 ? "" : "s"} recorded in the trail.
            </p>
          )}
          {signError && (
            <p role="alert" className="text-[11px] text-[var(--cc-err)]">
              {signError}
            </p>
          )}
          <details className="text-[11px] text-[var(--cc-text-muted)]">
            <summary className="cursor-pointer">What a signature means here</summary>
            <p className="mt-1 leading-relaxed">{audit.signature.meaning}</p>
            {audit.signature.key && <p className="mt-1 font-mono break-all">Key: {audit.signature.key}</p>}
          </details>
        </div>
      )}

      {audit.events.length === 0 ? (
        <p className="text-xs text-[var(--cc-text-muted)] italic">No audit events recorded yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {audit.events.map((evt) => (
            <li
              key={evt.event_id}
              className="text-xs p-2.5 rounded-[var(--cc-radius)] border border-[var(--cc-border)] bg-[var(--cc-surface-2)] flex flex-col gap-1.5"
            >
              <div className="flex items-center justify-between font-semibold">
                <span className="font-mono text-[var(--cc-focus)]">
                  #{evt.seq} {evt.event_type}
                </span>
                <time dateTime={evt.ts} className="text-[10px] text-[var(--cc-text-muted)] font-mono">
                  {evt.ts}
                </time>
              </div>
              {describe(evt) && <p className="text-[11px] text-[var(--cc-text)] break-words">{describe(evt)}</p>}
              <div className="flex items-center justify-between gap-3 text-[11px] font-mono text-[var(--cc-text-muted)] pt-1 border-t border-[var(--cc-border)]">
                <span>
                  Actor: <strong className="text-[var(--cc-text)]">{evt.actor}</strong>
                </span>
                <span>
                  Prev: <code title={evt.prev_hash}>{shortHash(evt.prev_hash)}</code>
                </span>
                <span>
                  Hash: <code title={evt.hash}>{shortHash(evt.hash)}</code>
                </span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
