"use client";

import { use } from "react";
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
                const token = `mock-jwt-${email}-LICENSED_CHA`;
                document.cookie = `__session=${token}; path=/; max-age=86400; SameSite=Lax`;
                document.cookie = `cargoclear_session_token=${token}; path=/; max-age=86400; SameSite=Lax`;
                window.location.reload();
              }}
              onLogout={() => {
                document.cookie = "__session=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
                document.cookie = "cargoclear_session_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
                window.location.href = "/api/auth/logout";
              }}
            />
          </div>
        </div>
      </main>
    );
  }

  const { bundle, assessment } = wb;
  const actionError = wb.actionError ?? wb.streamError;
  const auditRefreshKey = `${assessment?.iteration ?? 0}:${wb.run?.run_id ?? ""}:${wb.run?.state ?? ""}:${wb.documents.length}:${wb.corrections?.corrections.length ?? 0}`;

  return (
    <>
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
          const token = `mock-jwt-${email}-LICENSED_CHA`;
          document.cookie = `__session=${token}; path=/; max-age=86400; SameSite=Lax`;
          document.cookie = `cargoclear_session_token=${token}; path=/; max-age=86400; SameSite=Lax`;
          window.location.reload();
        }}
        onLogout={() => {
          document.cookie = "__session=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
          document.cookie = "cargoclear_session_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
          window.location.href = "/api/auth/logout";
        }}
      />


      <aside className="cc-rail" aria-label="Documents in this bundle">
        <DocumentRail
          documents={wb.documents}
          checks={assessment?.checks ?? []}
          activeDocumentId={wb.activeDocumentId ?? undefined}
          onSelectDocument={wb.selectDocument}
          onRemoveDocument={wb.removeDocument}
          removeDisabled={wb.isRunning || wb.isUploading || wb.isRemoving}
        />
      </aside>

      <main className="cc-viewer" aria-label="Document viewer and annotations">
        <DocumentViewer
          bundleId={bundleId}
          documents={wb.documents}
          activeDocumentId={wb.activeDocumentId}
          highlights={wb.highlights}
          iteration={assessment?.iteration ?? null}
        />
      </main>

      <section className="cc-assess" aria-label="Compliance assessment and actions">
        <AssessmentPanel
          assessment={assessment}
          bundleId={bundleId}
          documents={wb.documents}
          onSelectDocument={wb.selectDocument}
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
