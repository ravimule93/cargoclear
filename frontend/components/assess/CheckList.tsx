import { CheckResult } from "@/lib/types";

interface CheckListProps {
  checks: CheckResult[];
}

export function CheckList({ checks }: CheckListProps) {
  if (checks.length === 0) {
    return (
      <div className="text-xs text-[var(--cc-text-muted)] p-2">
        No validation checks executed yet.
      </div>
    );
  }

  return (
    <ul className="flex flex-col gap-2" aria-label="Validation checks">
      {checks.map((check) => {
        const isPass = check.severity === "PASS";
        const isMaterial = check.severity === "MATERIAL";

        const badgeColor = isPass
          ? "text-[var(--cc-ok)] bg-[var(--cc-ok-bg)] border-[var(--cc-ok-bd)]"
          : isMaterial
          ? "text-[var(--cc-err)] bg-[var(--cc-err-bg)] border-[var(--cc-err-bd)]"
          : "text-[var(--cc-warn)] bg-[var(--cc-warn-bg)] border-[var(--cc-warn-bd)]";

        return (
          <li
            key={check.check_id}
            className="p-2.5 rounded-[var(--cc-radius)] border border-[var(--cc-border)] bg-[var(--cc-surface-2)] flex flex-col gap-1 text-xs"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono font-bold text-[var(--cc-text)]">
                {check.check_id}
              </span>
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${badgeColor}`}
              >
                {check.severity}
              </span>
            </div>
            <p className="text-[var(--cc-text-muted)] leading-relaxed">
              {check.message}
            </p>
          </li>
        );
      })}
    </ul>
  );
}
