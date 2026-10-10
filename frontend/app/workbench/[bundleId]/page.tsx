"use client";

import { use } from "react";
import Link from "next/link";
import { TopBar } from "@/components/shell/TopBar";
import { DemoBanner } from "@/components/shell/DemoBanner";
import { DocumentRail } from "@/components/rail/DocumentRail";
import { DocumentViewer } from "@/components/viewer/DocumentViewer";
import { AssessmentPanel } from "@/components/assess/AssessmentPanel";
import { DeltaDrawer } from "@/components/delta/DeltaDrawer";
import { useMeta } from "@/lib/hooks/useMeta";
import { useWorkbench } from "@/lib/hooks/useWorkbench";

interface WorkbenchPageProps {
  params: Promise<{ bundleId: string }>;
}

export default function WorkbenchPage({ params }: WorkbenchPageProps) {
  const { bundleId } = use(params);
  const wb = useWorkbench(bundleId);
  const { meta } = useMeta();

  if (wb.loadState === "loading") {
    return (
      <main className="cc-state" aria-busy="true">
        <p role="status" className="text-sm text-[var(--cc-text-muted)]">
          Loading bundle...
        </p>
      </main>
    );
  }

  if (wb.loadState === "not_found") {
    return (
      <main className="cc-state">
        <h1 className="text-lg font-bold text-[var(--cc-text)]">Bundle not found</h1>
        <p className="text-sm text-[var(--cc-text-muted)]">
          No bundle with id <code className="font-mono">{bundleId}</code> exists.
        </p>
        <Link
          href="/"
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] px-3 py-1.5 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)]"
        >
          Back to start
        </Link>
      </main>
    );
  }

  if (wb.loadState === "error" || wb.bundle === null) {
    return (
      <main className="cc-state">
        <div role="alert" className="flex flex-col items-center gap-3">
          <p className="text-sm font-medium text-[var(--cc-err)]">
            Could not load bundle: {wb.loadError ?? "unknown error"}
          </p>
          <button
            type="button"
            onClick={wb.retry}
            className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 cursor-pointer"
          >
            Retry
          </button>
        </div>
      </main>
    );
  }

  const { bundle, assessment } = wb;
  const actionError = wb.actionError ?? wb.streamError;
  const auditRefreshKey = `${assessment?.iteration ?? 0}:${wb.run?.run_id ?? ""}:${wb.run?.state ?? ""}:${wb.documents.length}`;

  return (
    <>
      <DemoBanner appMode={meta?.app_mode} dataSource={assessment?.data_source} />

      <TopBar
        bundle={bundle}
        status={assessment?.status ?? null}
        isRunning={wb.isRunning}
        isUploading={wb.isUploading}
        runMode={wb.runMode}
        connection={wb.connection}
        actionError={actionError}
        onRun={wb.runAnalysis}
        onFilesSelected={wb.uploadFiles}
      />

      <aside className="cc-rail" aria-label="Documents in this bundle">
        <DocumentRail
          documents={wb.documents}
          activeDocumentId={wb.activeDocumentId ?? undefined}
          onSelectDocument={wb.selectDocument}
        />
      </aside>

      <main className="cc-viewer" aria-label="Document viewer and annotations">
        <DocumentViewer
          bundleId={bundleId}
          documents={wb.documents}
          activeDocumentId={wb.activeDocumentId}
          highlights={wb.highlights}
        />
      </main>

      <section className="cc-assess" aria-label="Compliance assessment and actions">
        <AssessmentPanel
          assessment={assessment}
          bundleId={bundleId}
          run={wb.run}
          isRunning={wb.isRunning}
          appMode={meta?.app_mode}
          onDocumentUploaded={wb.handleUploaded}
        />
      </section>

      <section className="cc-drawer" aria-label="Reasoning delta and audit trail">
        <DeltaDrawer
          bundleId={bundleId}
          iterations={wb.iterations}
          auditRefreshKey={auditRefreshKey}
        />
      </section>
    </>
  );
}
