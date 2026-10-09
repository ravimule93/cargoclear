"use client";

import { useEffect, useState } from "react";
import { subscribeToBundle } from "../sse";
import { AssessmentIteration, StatusEvent } from "../types";

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
      onIteration: (iter) => setAssessment(iter),
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
