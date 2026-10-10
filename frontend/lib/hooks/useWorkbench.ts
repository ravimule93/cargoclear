"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { isNotFound, runErrorMessage, toErrorEnvelope } from "../errors";
import { buildHighlights, type Highlight } from "../highlights";
import type { AssessmentIteration, Bundle, DocumentRecord } from "../types";
import { useBundleStream, type StreamConnection, type StreamRunState } from "./useBundleStream";

export type LoadState = "loading" | "ready" | "not_found" | "error";

export interface Workbench {
  loadState: LoadState;
  loadError: string | null;
  retry: () => void;

  bundle: Bundle | null;
  documents: DocumentRecord[];
  /** Latest assessment, or null when the bundle has not been analysed yet. */
  assessment: AssessmentIteration | null;
  iterations: AssessmentIteration[];
  highlights: Highlight[];

  activeDocumentId: string | null;
  selectDocument: (documentId: string) => void;

  run: StreamRunState | null;
  connection: StreamConnection;
  isRunning: boolean;
  /** Primary action: "analyze" until the first iteration exists, "reassess" afterwards. */
  runMode: "analyze" | "reassess";
  currentIteration: number;
  runAnalysis: () => Promise<void>;

  uploadFiles: (files: File[]) => Promise<void>;
  /** Call after documents were uploaded elsewhere (e.g. the dropzone). One refresh, one run action. */
  handleUploaded: () => Promise<void>;
  isUploading: boolean;

  actionError: string | null;
  /** Pipeline error reported by the stream (run state ERROR or stream failure). */
  streamError: string | null;
}

function latestOf(iterations: AssessmentIteration[]): AssessmentIteration | null {
  return iterations.reduce<AssessmentIteration | null>(
    (best, it) => (best === null || it.iteration > best.iteration ? it : best),
    null
  );
}

/**
 * Everything the workbench page needs for one bundle: the initial fetch, live SSE updates,
 * run controls and uploads. Page components stay presentational.
 */
export function useWorkbench(bundleId: string): Workbench {
  const stream = useBundleStream(bundleId);

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [fetchedAssessment, setFetchedAssessment] = useState<AssessmentIteration | null>(null);
  const [fetchedIterations, setFetchedIterations] = useState<AssessmentIteration[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);

  const [startingRun, setStartingRun] = useState(false);
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Highest iteration number the page data already reflects; SSE replays at or below it are not "new".
  const handledIterationRef = useRef<number | null>(null);

  // Initial load: bundle + latest assessment (404 -> not analysed yet) + iteration list, in parallel.
  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");
    setLoadError(null);
    setBundle(null);
    setFetchedAssessment(null);
    setFetchedIterations([]);
    setSelectedDocumentId(null);
    setPendingRunId(null);
    setActionError(null);
    handledIterationRef.current = null;

    (async () => {
      try {
        const [loadedBundle, loadedAssessment, loadedIterations] = await Promise.all([
          api.getBundle(bundleId),
          api.getAssessment(bundleId).catch((err: unknown) => {
            if (isNotFound(err)) return null;
            throw err;
          }),
          api.listIterations(bundleId),
        ]);
        if (cancelled) return;
        handledIterationRef.current = Math.max(
          loadedAssessment?.iteration ?? 0,
          latestOf(loadedIterations)?.iteration ?? 0
        );
        setBundle(loadedBundle);
        setFetchedAssessment(loadedAssessment);
        setFetchedIterations(loadedIterations);
        setLoadState("ready");
      } catch (err: unknown) {
        if (cancelled) return;
        if (isNotFound(err)) {
          setLoadState("not_found");
        } else {
          setLoadError(toErrorEnvelope(err).message);
          setLoadState("error");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bundleId, attempt]);

  const refreshBundle = useCallback(async () => {
    try {
      setBundle(await api.getBundle(bundleId));
    } catch (err: unknown) {
      console.warn("Could not refresh bundle", err);
    }
  }, [bundleId]);

  const refreshIterations = useCallback(async () => {
    try {
      setFetchedIterations(await api.listIterations(bundleId));
    } catch (err: unknown) {
      console.warn("Could not refresh iterations", err);
    }
  }, [bundleId]);

  // A new iteration arrived over SSE: document types change after classification and the stream
  // only carries the latest iteration, so refetch both the bundle and the iteration list.
  const streamIteration = stream.assessment?.iteration ?? null;
  useEffect(() => {
    if (loadState !== "ready" || streamIteration === null) return;
    const handled = handledIterationRef.current;
    if (handled !== null && streamIteration <= handled) return;
    handledIterationRef.current = streamIteration;
    void refreshBundle();
    void refreshIterations();
  }, [loadState, streamIteration, refreshBundle, refreshIterations]);

  // A finished run supersedes any earlier run/upload error (e.g. a 409 raised while it was running).
  useEffect(() => {
    if (streamIteration !== null) setActionError(null);
  }, [streamIteration]);

  const assessment = useMemo(() => {
    const live = stream.assessment;
    if (live && (!fetchedAssessment || live.iteration >= fetchedAssessment.iteration)) return live;
    return fetchedAssessment;
  }, [stream.assessment, fetchedAssessment]);

  const iterations = useMemo(() => {
    const byNumber = new Map<number, AssessmentIteration>();
    for (const it of fetchedIterations) byNumber.set(it.iteration, it);
    if (assessment) byNumber.set(assessment.iteration, assessment);
    return [...byNumber.values()].sort((a, b) => a.iteration - b.iteration);
  }, [fetchedIterations, assessment]);

  const highlights = useMemo(() => buildHighlights(assessment), [assessment]);

  const documents = useMemo(() => bundle?.documents ?? [], [bundle]);

  // Keep the user's selection unless that document disappeared; otherwise fall back to the first.
  const activeDocumentId = useMemo(() => {
    if (selectedDocumentId && documents.some((d) => d.document_id === selectedDocumentId)) {
      return selectedDocumentId;
    }
    return documents[0]?.document_id ?? null;
  }, [selectedDocumentId, documents]);

  const currentIteration = Math.max(bundle?.current_iteration ?? 0, assessment?.iteration ?? 0);
  const runMode = currentIteration === 0 ? "analyze" : "reassess";

  const run = stream.run;
  const streamRunning = run?.state === "RUNNING" || run?.state === "QUEUED";
  // After POST /analyze the SSE status can lag by up to a poll interval; stay "running" until the
  // stream reports a terminal state for the run we started.
  const awaitingRun =
    pendingRunId !== null &&
    !(run?.run_id === pendingRunId && run.state !== "RUNNING" && run.state !== "QUEUED");
  const isRunning = streamRunning || awaitingRun || startingRun;

  const runAnalysis = useCallback(async () => {
    setActionError(null);
    setStartingRun(true);
    try {
      const started =
        runMode === "analyze" ? await api.analyze(bundleId) : await api.reassess(bundleId);
      setPendingRunId(started.run_id);
    } catch (err: unknown) {
      setActionError(runErrorMessage(err));
    } finally {
      setStartingRun(false);
    }
  }, [bundleId, runMode]);

  // One refresh and at most one run action per upload batch; only auto-reassess once an
  // assessment exists (iteration 0 waits for the user to press "Run analysis").
  const handleUploaded = useCallback(async () => {
    await refreshBundle();
    if (currentIteration > 0) await runAnalysis();
  }, [refreshBundle, currentIteration, runAnalysis]);

  const uploadFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;
      setActionError(null);
      setIsUploading(true);
      let uploaded = 0;
      try {
        for (const file of files) {
          await api.uploadDocument(bundleId, file);
          uploaded += 1;
        }
      } catch (err: unknown) {
        setActionError(toErrorEnvelope(err).message);
      } finally {
        setIsUploading(false);
      }
      if (uploaded === files.length) {
        await handleUploaded();
      } else if (uploaded > 0) {
        await refreshBundle();
      }
    },
    [bundleId, handleUploaded, refreshBundle]
  );

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  return {
    loadState,
    loadError,
    retry,
    bundle,
    documents,
    assessment,
    iterations,
    highlights,
    activeDocumentId,
    selectDocument: setSelectedDocumentId,
    run,
    connection: stream.connection,
    isRunning,
    runMode,
    currentIteration,
    runAnalysis,
    uploadFiles,
    handleUploaded,
    isUploading,
    actionError,
    streamError: stream.error,
  };
}
