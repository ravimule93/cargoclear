"use client";

import { useEffect, useState } from "react";
import { subscribeToBundle } from "../sse";
import { AssessmentIteration, IterationEvent, StatusEvent } from "../types";

/** Maps a live SSE IterationEvent to the full AssessmentIteration shape. */
function toAssessmentIteration(iter: IterationEvent): AssessmentIteration {
  return {
    iteration: iter.iteration,
    bundle_id: iter.bundle_id,
    status: iter.status,
    checks: iter.checks,
    missing_evidence: iter.missing_evidence,
    confidence: iter.confidence ?? null,
    reasoning_delta: iter.reasoning_delta ?? null,
    // Fields not present in the SSE event: fall back to safe defaults
    grounding: [],
    documents: [],
    created_at: new Date().toISOString(),
  };
}

export function useBundleStream(
  bundleId: string,
  initialAssessment?: AssessmentIteration | null
) {
  const [assessment, setAssessment] = useState<AssessmentIteration | null>(
    initialAssessment ?? null
  );
  const [run, setRun] = useState<StatusEvent>({
    kind: "status",
    bundle_id: bundleId,
    run_id: "",
    state: "COMPLETE",
    stage: null,
    progress: 1.0,
    message: null,
  });

  useEffect(() => {
    if (!bundleId) return;

    const unsubscribe = subscribeToBundle(bundleId, {
      onStatus: (s) => setRun(s),
      onIteration: (iter) => setAssessment(toAssessmentIteration(iter)),
      onError: (err) => {
        setRun((prev) => ({
          ...prev,
          state: "ERROR",
          message: err.message,
        }));
      },
    });

    return () => unsubscribe();
  }, [bundleId]);

  return { assessment, run };
}
