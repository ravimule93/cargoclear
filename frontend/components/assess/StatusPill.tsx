import { Status } from "@/lib/types";

interface StatusPillProps {
  /** null = the bundle has not been assessed yet */
  status: Status | null;
}

const TOKENS: Record<Status, { label: string; fg: string; bd: string; bg: string }> = {
  COMPLIANT_FOR_SUBMISSION: {
    label: "Compliant For Submission",
    fg: "var(--cc-ok)",
    bd: "var(--cc-ok-bd)",
    bg: "var(--cc-ok-bg)",
  },
  MISSING_EVIDENCE: {
    label: "Missing Evidence",
    fg: "var(--cc-warn)",
    bd: "var(--cc-warn-bd)",
    bg: "var(--cc-warn-bg)",
  },
  MATERIAL_CONTRADICTION: {
    label: "Material Contradiction",
    fg: "var(--cc-err)",
    bd: "var(--cc-err-bd)",
    bg: "var(--cc-err-bg)",
  },
  SPECIALIST_REVIEW_REQUIRED: {
    label: "Specialist Review Required",
    fg: "var(--cc-info)",
    bd: "var(--cc-info-bd)",
    bg: "var(--cc-info-bg)",
  },
};

const NOT_ASSESSED = {
  label: "Not assessed yet",
  fg: "var(--cc-text-muted)",
  bd: "var(--cc-border-strong)",
  bg: "var(--cc-surface-2)",
};

export function StatusPill({ status }: StatusPillProps) {
  const token = status === null ? NOT_ASSESSED : TOKENS[status] || TOKENS.SPECIALIST_REVIEW_REQUIRED;

  return (
    <span
      role="status"
      data-testid="status-pill"
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold tracking-tight"
      style={{
        color: token.fg,
        background: token.bg,
        border: `1px solid ${token.bd}`,
      }}
    >
      <span
        aria-hidden="true"
        className="inline-block h-2 w-2 rounded-full"
        style={{ background: token.bd }}
      />
      {token.label}
    </span>
  );
}
