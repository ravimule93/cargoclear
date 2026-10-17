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
  const step1Complete = docCount >= 3;
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
      title: "Documents Staged",
      detail: step1Complete
        ? `${docCount} Docs Ready`
        : docCount > 0
        ? `${docCount} Staged (Need ≥3)`
        : "Upload Trade Docs",
      complete: step1Complete,
      active: step1Active || (!step1Complete && docCount === 0),
      alert: false,
    },
    {
      num: 2,
      title: "AI Assessment",
      detail: step2Active
        ? "Analyzing Pipeline..."
        : step2Complete
        ? `v${assessment?.iteration} Adjudicated`
        : "Ready to Analyze",
      complete: step2Complete,
      active: step2Active,
      alert: false,
    },
    {
      num: 3,
      title: "Issue Resolution",
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
      title: "Declaration Ready",
      detail: step4Complete ? "Compliant for Filing" : "Awaiting Compliance",
      complete: step4Complete,
      active: false,
      alert: false,
    },
  ];

  return (
    <nav
      aria-label="Compliance Workflow Progress"
      className="bg-[var(--cc-surface-2)] border-b border-[var(--cc-border)] px-3 py-2 text-xs"
    >
      <ol className="flex items-center justify-between gap-1 sm:gap-2 max-w-5xl mx-auto">
        {steps.map((s, idx) => (
          <li key={s.num} className="flex-1 flex items-center gap-1.5 min-w-0">
            <div
              className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold transition-colors ${
                s.complete
                  ? "bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border border-[var(--cc-ok-bd)]"
                  : s.alert
                  ? "bg-[var(--cc-warn-bg)] text-[var(--cc-warn)] border border-[var(--cc-warn-bd)] animate-pulse"
                  : s.active
                  ? "bg-[var(--cc-focus)] text-white shadow-2xs"
                  : "bg-[var(--cc-surface)] text-[var(--cc-text-muted)] border border-[var(--cc-border)]"
              }`}
            >
              {s.complete ? "✓" : s.alert ? "!" : s.num}
            </div>
            <div className="min-w-0 flex-1 hidden sm:block">
              <p
                className={`text-[11px] font-semibold truncate ${
                  s.complete
                    ? "text-[var(--cc-text)]"
                    : s.active || s.alert
                    ? "text-[var(--cc-text)] font-bold"
                    : "text-[var(--cc-text-muted)]"
                }`}
              >
                {s.title}
              </p>
              <p className="text-[10px] text-[var(--cc-text-muted)] truncate">{s.detail}</p>
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
    </nav>
  );
}
