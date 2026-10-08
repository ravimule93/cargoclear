export interface AuditEntry {
  seq: number;
  ts: string;
  actor: string;
  event_type: string;
  hash: string;
  prev_hash: string;
  payload?: any;
}

interface AuditTimelineProps {
  events?: AuditEntry[];
}

export function AuditTimeline({ events = [] }: AuditTimelineProps) {
  // Default entries if no events passed yet
  const displayEvents: AuditEntry[] =
    events.length > 0
      ? events
      : [
          {
            seq: 1,
            ts: new Date().toISOString(),
            actor: "system",
            event_type: "BUNDLE_INITIALIZED",
            hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            prev_hash: "GENESIS",
          },
          {
            seq: 2,
            ts: new Date().toISOString(),
            actor: "user",
            event_type: "DOCUMENTS_INGESTED",
            hash: "a94a8fe5ccb19ba61c4c0873d391e987982fbbd34208a1d7f6c3821034c449c2",
            prev_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
          },
        ];

  return (
    <div className="flex flex-col gap-2 max-w-4xl" aria-label="Tamper-evident audit chain">
      {displayEvents.map((evt) => (
        <article
          key={evt.seq}
          className="text-xs p-2.5 rounded-[var(--cc-radius)] border border-[var(--cc-border)] bg-[var(--cc-surface-2)] flex flex-col gap-1.5"
        >
          <div className="flex items-center justify-between font-semibold">
            <span className="font-mono text-[var(--cc-focus)]">
              #{evt.seq} {evt.event_type}
            </span>
            <time className="text-[10px] text-[var(--cc-text-muted)] font-mono">
              {evt.ts}
            </time>
          </div>
          <div className="flex items-center justify-between text-[11px] font-mono text-[var(--cc-text-muted)] pt-1 border-t border-[var(--cc-border)]">
            <span>Actor: <strong className="text-[var(--cc-text)]">{evt.actor}</strong></span>
            <span>
              Hash: <code className="text-[var(--cc-text-subtle)]">{evt.hash.substring(0, 16)}...</code>
            </span>
          </div>
        </article>
      ))}
    </div>
  );
}
