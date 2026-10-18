"use client";

import type { AssessmentIteration, DocumentRecord, Status } from "@/lib/types";

interface WorkflowStepperProps {
  documents: DocumentRecord[];
  assessment: AssessmentIteration | null;
  status: Status | null;
  isRunning?: boolean;
}

export function WorkflowStepper({
  documents,
  assessment,
  status,
  isRunning = false,
}: WorkflowStepperProps) {
  const docCount = documents.length;
  const isCompliant = status === "COMPLIANT_FOR_SUBMISSION";
  const openIssuesCount = assessment?.checks?.filter((c) => c.severity !== "PASS").length ?? 0;
  const missingCount = assessment?.missing_evidence?.length ?? 0;

  // Step 1: Documents Staged
  const step1Complete = docCount > 0;
  const step1Active = docCount > 0 && !step1Complete;

  // Step 2: AI Assessment
  const step2Active = isRunning;
  const step2Complete = assessment !== null && !isRunning;

  // Step 3: Issue Resolution
  const step3Complete = step2Complete && isCompliant;
  const step3Active = step2Complete && !isCompliant && (openIssuesCount > 0 || missingCount > 0);

  // Step 4: Declaration Ready
  const step4Complete = isCompliant;

  const steps = [
    {
      num: 1,
      title: "Documents",
      detail: step1Complete
        ? `${docCount} uploaded`
        : docCount > 0
        ? `${docCount} uploaded`
        : "Upload Trade Docs",
      complete: step1Complete,
      active: step1Active || (!step1Complete && docCount === 0),
      alert: false,
    },
    {
      num: 2,
      title: "Assessment",
      detail: step2Active
        ? "Analysis in progress"
        : step2Complete
        ? `Iteration ${assessment?.iteration}`
        : "Ready to Analyze",
      complete: step2Complete,
      active: step2Active,
      alert: false,
    },
    {
      num: 3,
      title: "Resolve findings",
      detail: !step2Complete
        ? "Awaiting Run"
        : step3Complete
        ? "All Rules Satisfied"
        : `${openIssuesCount + missingCount} Action Required`,
      complete: step3Complete,
      active: step3Active,
      alert: step3Active,
    },
    {
      num: 4,
      title: "Declaration review",
      detail: step4Complete ? "Review and export" : "Awaiting assessment",
      complete: step4Complete,
      active: false,
      alert: false,
    },
  ];

  return (
    <section
      aria-label="Compliance Workflow Progress"
      className="bg-[var(--cc-surface-2)] border-b border-[var(--cc-border)] px-3 py-2 text-xs"
    >
      <ol className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-5xl mx-auto">
        {steps.map((s, idx) => (
          <li key={s.num} aria-current={(isRunning ? s.num === 2 : docCount === 0 ? s.num === 1 : !assessment ? s.num === 2 : isCompliant ? s.num === 4 : s.num === 3) ? "step" : undefined} className="flex-1 flex items-center gap-1.5 min-w-0">
            <div
              className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold transition-colors ${
                s.complete
                  ? "bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border border-[var(--cc-ok-bd)]"
                  : s.alert
                  ? "bg-[var(--cc-warn-bg)] text-[var(--cc-warn)] border border-[var(--cc-warn-bd)]"
                  : s.active
                  ? "bg-[var(--cc-action)] text-white shadow-2xs"
                  : "bg-[var(--cc-surface)] text-[var(--cc-text-muted)] border border-[var(--cc-border)]"
              }`}
            >
              {s.complete ? "✓" : s.alert ? "!" : s.num}
            </div>
            <div className="min-w-0 flex-1">
              <p
                className={`text-xs font-semibold ${
                  s.complete
                    ? "text-[var(--cc-text)]"
                    : s.active || s.alert
                    ? "text-[var(--cc-text)] font-bold"
                    : "text-[var(--cc-text-muted)]"
                }`}
              >
                {s.title}
              </p>
              <p className="text-xs text-[var(--cc-text-muted)]">{s.detail}</p>
            </div>
            {idx < steps.length - 1 && (
              <div
                className={`h-0.5 flex-1 hidden md:block mx-1 ${
                  s.complete ? "bg-[var(--cc-ok-bd)]" : "bg-[var(--cc-border)]"
                }`}
              />
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
