"use client";

import { use, useState } from "react";
import Link from "next/link";
import { TopBar } from "@/components/shell/TopBar";
import { UserMenu } from "@/components/shell/UserMenu";
import { DemoBanner } from "@/components/shell/DemoBanner";
import { DocumentRail } from "@/components/rail/DocumentRail";
import { DocumentViewer } from "@/components/viewer/DocumentViewer";
import { AssessmentPanel } from "@/components/assess/AssessmentPanel";
import { DeltaDrawer } from "@/components/delta/DeltaDrawer";
import { useMeta } from "@/lib/hooks/useMeta";
import { useWorkbench } from "@/lib/hooks/useWorkbench";
import { demoSignIn, signOut } from "@/lib/session";

interface WorkbenchPageProps {
  params: Promise<{ bundleId: string }>;
}

export default function WorkbenchPage({ params }: WorkbenchPageProps) {
  const { bundleId } = use(params);
  const wb = useWorkbench(bundleId);
  const { meta } = useMeta();
  const [activeTab, setActiveTab] = useState<"assess" | "viewer" | "rail" | "drawer">("assess");

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
        <div role="alert" className="flex flex-col items-center gap-4 max-w-md text-center">
          <p className="text-sm font-medium text-[var(--cc-err)]">
            Could not load bundle: {wb.loadError ?? "unknown error"}
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={wb.retry}
              className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-90 cursor-pointer"
            >
              Retry
            </button>
            <UserMenu
              user={meta?.user ?? null}
              onLogin={(email) => {
                if (demoSignIn(email, meta?.app_mode)) window.location.reload();
              }}
              onLogout={signOut}
            />
          </div>
        </div>
      </main>
    );
  }

  const { bundle, assessment } = wb;
  const actionError = wb.actionError ?? wb.streamError;
  const auditRefreshKey = `${assessment?.iteration ?? 0}:${wb.run?.run_id ?? ""}:${wb.run?.state ?? ""}:${wb.documents.length}:${wb.corrections?.corrections.length ?? 0}`;

  const handleSelectDocument = (docId: string) => {
    wb.selectDocument(docId);
    setActiveTab("viewer");
  };

  const openIssuesCount = assessment?.checks?.filter((c) => c.severity !== "PASS").length ?? 0;

  return (
    <div className="cc-workbench" data-tab={activeTab}>
      <DemoBanner appMode={meta?.app_mode} dataSource={assessment?.data_source} />

      <TopBar
        bundle={bundle}
        status={assessment?.status ?? null}
        user={meta?.user ?? null}
        isRunning={wb.isRunning}
        isUploading={wb.isUploading}
        uploadProgress={wb.uploadProgress}
        runMode={wb.runMode}
        connection={wb.connection}
        actionError={actionError}
        onRun={wb.runAnalysis}
        onFilesSelected={wb.uploadFiles}
        onLogin={(email) => {
          if (demoSignIn(email, meta?.app_mode)) window.location.reload();
        }}
        onLogout={signOut}
      />

      <nav className="cc-tabs" role="tablist" aria-label="Workbench sections">
        <button
          type="button"
          role="tab"
          id="tab-btn-assess"
          aria-selected={activeTab === "assess"}
          aria-controls="panel-assess"
          className="cc-tab-btn"
          onClick={() => setActiveTab("assess")}
        >
          <span>⚖️ Assessment</span>
          {openIssuesCount > 0 ? (
            <span className="cc-tab-badge bg-[var(--cc-err-bg)] text-[var(--cc-err)] border border-[var(--cc-err-bd)]">
              {openIssuesCount}
            </span>
          ) : assessment?.checks?.length ? (
            <span className="cc-tab-badge bg-[var(--cc-ok-bg)] text-[var(--cc-ok)] border border-[var(--cc-ok-bd)]">
              ✓
            </span>
          ) : null}
        </button>

        <button
          type="button"
          role="tab"
          id="tab-btn-viewer"
          aria-selected={activeTab === "viewer"}
          aria-controls="panel-viewer"
          className="cc-tab-btn"
          onClick={() => setActiveTab("viewer")}
        >
          <span>🔍 Viewer</span>
          {wb.documents.length > 0 && (
            <span className="cc-tab-badge">
              {wb.activeDocumentId ? "1 doc" : `${wb.documents.length}`}
            </span>
          )}
        </button>

        <button
          type="button"
          role="tab"
          id="tab-btn-rail"
          aria-selected={activeTab === "rail"}
          aria-controls="panel-rail"
          className="cc-tab-btn"
          onClick={() => setActiveTab("rail")}
        >
          <span>📁 Files</span>
          <span className="cc-tab-badge">{wb.documents.length}</span>
        </button>

        <button
          type="button"
          role="tab"
          id="tab-btn-drawer"
          aria-selected={activeTab === "drawer"}
          aria-controls="panel-drawer"
          className="cc-tab-btn"
          onClick={() => setActiveTab("drawer")}
        >
          <span>📜 Audit & Delta</span>
          {assessment?.iteration ? (
            <span className="cc-tab-badge">v{assessment.iteration}</span>
          ) : null}
        </button>
      </nav>

      <aside id="panel-rail" className="cc-rail" aria-label="Documents in this bundle">
        <DocumentRail
          documents={wb.documents}
          checks={assessment?.checks ?? []}
          activeDocumentId={wb.activeDocumentId ?? undefined}
          onSelectDocument={handleSelectDocument}
          onRemoveDocument={wb.removeDocument}
          removeDisabled={wb.isRunning || wb.isUploading || wb.isRemoving}
        />
      </aside>

      <main id="panel-viewer" className="cc-viewer" aria-label="Document viewer and annotations">
        <DocumentViewer
          bundleId={bundleId}
          documents={wb.documents}
          activeDocumentId={wb.activeDocumentId}
          highlights={wb.highlights}
          iteration={assessment?.iteration ?? null}
          isVisible={activeTab === "viewer"}
        />
      </main>

      <section id="panel-assess" className="cc-assess" aria-label="Compliance assessment and actions">
        <AssessmentPanel
          assessment={assessment}
          bundleId={bundleId}
          documents={wb.documents}
          onSelectDocument={handleSelectDocument}
          run={wb.run}
          isRunning={wb.isRunning}
          actionError={actionError}
          appMode={meta?.app_mode}
          onDocumentUploaded={wb.handleUploaded}
          corrections={wb.corrections}
          extractions={wb.extractions}
          onCorrect={wb.submitCorrection}
          onRevertCorrection={wb.revertCorrection}
          onRecompute={wb.recompute}
        />
      </section>

      <section id="panel-drawer" className="cc-drawer" aria-label="Reasoning delta and audit trail">
        <DeltaDrawer
          bundleId={bundleId}
          iterations={wb.iterations}
          auditRefreshKey={auditRefreshKey}
        />
      </section>
    </div>
  );
}
