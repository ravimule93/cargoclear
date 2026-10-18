"use client";

import { type CSSProperties, type KeyboardEvent, use, useEffect, useRef, useState } from "react";
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
import { AUTHENTICATION_REQUIRED_MESSAGE } from "@/lib/errors";
import type { SourceRequest } from "@/lib/highlights";
import type { BBox, Meta } from "@/lib/types";

interface WorkbenchPageProps {
  params: Promise<{ bundleId: string }>;
}

export default function WorkbenchPage({ params }: WorkbenchPageProps) {
  const { bundleId } = use(params);
  const { meta, loading, error, retry } = useMeta();

  if (loading) {
    return <main className="cc-state" aria-busy="true"><p role="status">Checking sign-in...</p></main>;
  }

  if (error || !meta) {
    return (
      <main className="cc-state">
        <p role="alert" className="text-sm text-[var(--cc-err)]">Could not verify sign-in: {error ?? "Backend information is unavailable."}</p>
        <button type="button" onClick={retry} className="cc-button cc-button-primary">Retry</button>
        <Link href="/" className="underline">Back to start</Link>
      </main>
    );
  }

  if (meta.auth?.enabled && !meta.user) {
    return (
      <main className="cc-state">
        <div role="alert"><h1 className="text-sm font-semibold text-[var(--cc-err)]">{AUTHENTICATION_REQUIRED_MESSAGE}</h1></div>
        <Link href={`/auth/signin?returnTo=${encodeURIComponent(`/workbench/${bundleId}`)}`} className="cc-button cc-button-primary">Sign in</Link>
        <Link href="/" className="underline">Back to start</Link>
      </main>
    );
  }

  return <WorkbenchContent bundleId={bundleId} meta={meta} />;
}

function WorkbenchContent({ bundleId, meta }: { bundleId: string; meta: Meta }) {
  const wb = useWorkbench(bundleId);
  const [activeTab, setActiveTab] = useState<"assess" | "viewer" | "rail" | "drawer">("assess");
  const [viewerOpen, setViewerOpen] = useState(false);
  const [drawerCollapsed, setDrawerCollapsed] = useState(true);
  const [compact, setCompact] = useState(false);
  const [sourceRequest, setSourceRequest] = useState<SourceRequest | null>(null);
  const [sourceWidth, setSourceWidth] = useState(46);
  const viewerRef = useRef<HTMLElement>(null);
  const sourceTrigger = useRef<HTMLElement | null>(null);
  const sourceOriginTab = useRef<"assess" | "rail" | "drawer">("assess");

  useEffect(() => {
    const query = window.matchMedia("(max-width: 1023px)");
    const update = () => setCompact(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!viewerOpen || !sourceRequest) return;
    viewerRef.current?.focus({ preventScroll: true });
  }, [viewerOpen, sourceRequest]);

  const closeViewer = () => {
    setViewerOpen(false);
    const returnTab = compact ? sourceOriginTab.current : "assess";
    setActiveTab(returnTab);
    requestAnimationFrame(() => {
      const trigger = sourceTrigger.current;
      if (trigger?.isConnected && trigger.getClientRects().length) trigger.focus({ preventScroll: true });
      else document.getElementById(compact ? `tab-btn-${returnTab}` : "source-toggle")?.focus();
    });
  };

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
              className="rounded-[var(--cc-radius)] bg-[var(--cc-action)] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-90 cursor-pointer"
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

  const handleSelectDocument = (docId: string, page?: number, field?: string, bbox?: BBox | null) => {
    sourceTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (activeTab !== "viewer") sourceOriginTab.current = activeTab;
    wb.selectDocument(docId);
    setSourceRequest((previous) => ({ page, field, bbox, sequence: (previous?.sequence ?? 0) + 1 }));
    setViewerOpen(true);
    setActiveTab("viewer");
  };

  const activateTab = (tab: typeof activeTab) => {
    if (tab === "viewer" && activeTab !== "viewer") {
      sourceOriginTab.current = activeTab;
      sourceTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    setActiveTab(tab);
    if (tab === "drawer") setDrawerCollapsed(false);
  };

  const handleWorkbenchTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, current: typeof activeTab) => {
    const tabs: typeof activeTab[] = ["assess", "viewer", "rail", "drawer"];
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const currentIndex = tabs.indexOf(current);
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    const next = tabs[nextIndex];
    activateTab(next);
    document.getElementById(`tab-btn-${next}`)?.focus();
  };

  const openIssuesCount = assessment?.checks?.filter((c) => c.severity !== "PASS").length ?? 0;

  return (
    <div
      className="cc-workbench"
      style={{ "--cc-source-width": `${sourceWidth}%` } as CSSProperties}
      data-tab={activeTab}
      data-viewer-collapsed={viewerOpen ? undefined : "true"}
      data-drawer-collapsed={drawerCollapsed ? "true" : undefined}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented && (compact ? activeTab === "viewer" : viewerOpen) && !(event.target instanceof Element && event.target.closest('[role="dialog"]'))) {
          event.preventDefault();
          closeViewer();
        }
      }}
    >
      <a className="cc-skip-link" href="#panel-assess" onClick={(event) => {
        event.preventDefault();
        setActiveTab("assess");
        requestAnimationFrame(() => document.getElementById("panel-assess")?.focus());
      }}>Skip to assessment</a>
      <DemoBanner appMode={meta?.app_mode} dataSource={assessment?.data_source} />

      <TopBar
        bundle={bundle}
        status={assessment?.status ?? null}
        user={meta?.user ?? null}
        isRunning={wb.isRunning}
        run={wb.run}
        isUploading={wb.isUploading}
        uploadProgress={wb.uploadProgress}
        runMode={wb.runMode}
        connection={wb.connection}
        actionError={actionError}
        onRun={wb.runAnalysis}
        onFilesSelected={wb.uploadFiles}
        onRefresh={wb.handleUploaded}
        onLogin={(email) => {
          if (demoSignIn(email, meta?.app_mode)) window.location.reload();
        }}
        onLogout={signOut}
        viewerOpen={viewerOpen}
        onToggleViewer={() => {
          if (viewerOpen) closeViewer();
          else if (wb.activeDocumentId) handleSelectDocument(wb.activeDocumentId);
        }}
      />

      <nav className="cc-tabs" role="tablist" aria-label="Workbench sections">
        <button
          type="button"
          role="tab"
          id="tab-btn-assess"
          aria-selected={activeTab === "assess"}
          tabIndex={activeTab === "assess" ? 0 : -1}
          aria-controls="panel-assess"
          className="cc-tab-btn"
          onClick={() => activateTab("assess")}
          onKeyDown={(event) => handleWorkbenchTabKeyDown(event, "assess")}
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
          tabIndex={activeTab === "viewer" ? 0 : -1}
          aria-controls="panel-viewer"
          className="cc-tab-btn"
          onClick={() => activateTab("viewer")}
          onKeyDown={(event) => handleWorkbenchTabKeyDown(event, "viewer")}
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
          tabIndex={activeTab === "rail" ? 0 : -1}
          aria-controls="panel-rail"
          className="cc-tab-btn"
          onClick={() => activateTab("rail")}
          onKeyDown={(event) => handleWorkbenchTabKeyDown(event, "rail")}
        >
          <span>📁 Files</span>
          <span className="cc-tab-badge">{wb.documents.length}</span>
        </button>

        <button
          type="button"
          role="tab"
          id="tab-btn-drawer"
          aria-selected={activeTab === "drawer"}
          tabIndex={activeTab === "drawer" ? 0 : -1}
          aria-controls="panel-drawer"
          className="cc-tab-btn"
          onClick={() => activateTab("drawer")}
          onKeyDown={(event) => handleWorkbenchTabKeyDown(event, "drawer")}
        >
          <span>📜 Audit & Delta</span>
          {assessment?.iteration ? (
            <span className="cc-tab-badge">v{assessment.iteration}</span>
          ) : null}
        </button>
      </nav>

      <main className="cc-main-workspace">
      <h1 className="sr-only">Trade bundle assessment</h1>
      <aside id="panel-rail" role={compact ? "tabpanel" : "region"} tabIndex={-1} className="cc-rail" aria-label="Bundle files">
        <DocumentRail
          documents={wb.documents}
          checks={assessment?.checks ?? []}
          activeDocumentId={wb.activeDocumentId ?? undefined}
          onSelectDocument={handleSelectDocument}
          onRemoveDocument={wb.removeDocument}
          onCorrect={wb.submitCorrection}
          removeDisabled={wb.isRunning || wb.isUploading || wb.isRemoving}
        />
      </aside>

      <section ref={viewerRef} id="panel-viewer" role={compact ? "tabpanel" : "region"} tabIndex={-1} className="cc-viewer" aria-label="Document viewer and annotations">
        <div className="cc-source-heading">
          <h2>Source document</h2>
          <label className="cc-source-resize">Width
            <input aria-label="Source panel width" type="range" min="36" max="48" value={sourceWidth} onChange={(event) => setSourceWidth(Number(event.target.value))} />
          </label>
          <button type="button" className="cc-button" onClick={closeViewer} aria-label="Close source PDF">Close PDF <span aria-hidden="true">×</span></button>
        </div>
        <DocumentViewer
          bundleId={bundleId}
          documents={wb.documents}
          activeDocumentId={wb.activeDocumentId}
          highlights={wb.highlights}
          iteration={assessment?.iteration ?? null}
          isVisible={compact ? activeTab === "viewer" : viewerOpen}
          sourceRequest={sourceRequest}
        />
      </section>

      <section id="panel-assess" role={compact ? "tabpanel" : "region"} tabIndex={-1} className="cc-assess" aria-label="Compliance assessment and actions">
        <AssessmentPanel
          assessment={assessment}
          bundleId={bundleId}
          documents={wb.documents}
          onSelectDocument={handleSelectDocument}
          isRunning={wb.isRunning}
          actionError={actionError}
          appMode={meta?.app_mode}
          onDocumentUploaded={wb.handleUploaded}
          corrections={wb.corrections}
          extractions={wb.extractions}
          onCorrect={wb.submitCorrection}
          onRevertCorrection={wb.revertCorrection}
          onRecompute={wb.recompute}
          onRun={wb.runAnalysis}
          onAddDocuments={() => document.getElementById("add-documents-button")?.click()}
        />
      </section>

      <section id="panel-drawer" role={compact ? "tabpanel" : "region"} tabIndex={-1} className="cc-drawer" aria-label="Reasoning delta and audit trail">
        <DeltaDrawer
          bundleId={bundleId}
          iterations={wb.iterations}
          auditRefreshKey={auditRefreshKey}
          isCollapsed={drawerCollapsed}
          onCollapsedChange={setDrawerCollapsed}
        />
      </section>
      </main>
    </div>
  );
}
