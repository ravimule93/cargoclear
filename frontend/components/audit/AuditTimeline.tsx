"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toErrorEnvelope } from "@/lib/errors";
import type { AuditResponse } from "@/lib/types";

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
