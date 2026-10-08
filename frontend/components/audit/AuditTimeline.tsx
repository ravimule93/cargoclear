export interface AuditEntry {
  seq: number;
  ts: string;
  actor: string;
  event_type: string;
  hash: string;
  prev_hash: string;
}

interface AuditTimelineProps {
  events?: AuditEntry[];
}

export function AuditTimeline({ events = [] }: AuditTimelineProps) {
  if (events.length === 0) {
    return (
      <div className="text-xs text-[var(--cc-text-muted)] italic">
        Audit log entries will appear here once events are registered.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {events.map((evt) => (
        <div
          key={evt.seq}
          className="text-xs p-2 rounded-[var(--cc-radius)] border border-[var(--cc-border)] bg-[var(--cc-surface-2)] flex flex-col gap-1"
        >
          <div className="flex items-center justify-between font-semibold">
            <span className="font-mono text-[var(--cc-focus)]">#{evt.seq} {evt.event_type}</span>
            <span className="text-[10px] text-[var(--cc-text-muted)]">{evt.ts}</span>
          </div>
          <div className="flex items-center justify-between text-[10px] font-mono text-[var(--cc-text-muted)]">
            <span>Actor: {evt.actor}</span>
            <span>Hash: {evt.hash.substring(0, 12)}...</span>
          </div>
        </div>
      ))}
    </div>
  );
}
