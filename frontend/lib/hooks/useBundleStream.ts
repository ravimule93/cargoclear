"use client";

import { useEffect, useState } from "react";
import type { AssessmentIteration, StatusEvent, StreamErrorEvent } from "../types";

export interface StreamRunState {
  run_id?: string;
  state?: StatusEvent["state"];
  stage?: string | null;
  progress?: number;
  message?: string | null;
}

export type StreamConnection = "connecting" | "open" | "reconnecting" | "polling" | "disconnected";

export interface BundleStream {
  /** Latest iteration seen on the stream (full object: grounding, documents, data_source, ...). */
  assessment: AssessmentIteration | null;
  run: StreamRunState | null;
  connection: StreamConnection;
  /** Message of a pipeline run in state ERROR, or of a server-side stream failure. */
  error: string | null;
}


function parseJson(raw: unknown): unknown {
  if (typeof raw !== "string") return null;
  try {
    return JSON.parse(raw);
  } catch (err: unknown) {
    console.error("Failed to parse SSE payload", err);
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStatusPayload(value: unknown): value is StatusEvent {
  return isRecord(value) && typeof value.state === "string";
}

function isIterationPayload(value: unknown): value is AssessmentIteration {
  return isRecord(value) && typeof value.iteration === "number" && typeof value.status === "string";
}

/**
 * Subscribes to the same-origin /api/proxy/bundles/{id}/stream (the Next.js server proxies it to the API).
 *
 * The backend sends NAMED SSE events, so the event name decides how a payload is read:
 *   `status`    -> run progress (payload carries kind:"status")
 *   `iteration` -> a full AssessmentIteration (no `kind` field)
 * On connect it immediately replays the current status and latest iteration.
 */
export function useBundleStream(bundleId: string | null): BundleStream {
  const [assessment, setAssessment] = useState<AssessmentIteration | null>(null);
  const [run, setRun] = useState<StreamRunState | null>(null);
  const [connection, setConnection] = useState<StreamConnection>("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setAssessment(null);
    setRun(null);
    setError(null);
    setConnection("connecting");

    if (!bundleId) return;

    const url = `/api/proxy/bundles/${encodeURIComponent(bundleId)}/stream`;

    // `disposed` makes this safe under React StrictMode's mount/unmount/mount in dev:
    // the first source is closed by cleanup and can never write state afterwards.
    let disposed = false;
    let source: EventSource | null = null;
    let reopenTimer: ReturnType<typeof setTimeout> | undefined;
    let retryAttempt = 0;

    const connect = () => {
      if (disposed) return;
      const es = new EventSource(url);
      source = es;

      es.addEventListener("open", () => {
        if (disposed) return;
        setConnection("open");
        retryAttempt = 0;
      });

      es.addEventListener("status", (event) => {
        if (disposed) return;
        const data = parseJson((event as MessageEvent).data);
        if (!isStatusPayload(data)) return;
        setRun({
          run_id: data.run_id,
          state: data.state,
          stage: data.stage,
          progress: data.progress,
          message: data.message,
        });
        setError(data.state === "ERROR" ? (data.message ?? "Pipeline run failed") : null);
      });

      es.addEventListener("iteration", (event) => {
        if (disposed) return;
        const data = parseJson((event as MessageEvent).data);
        if (!isIterationPayload(data)) return;
        // Ignore stale iterations (e.g. a replay older than what we already hold).
        setAssessment((prev) => (prev && data.iteration < prev.iteration ? prev : data));
      });

      // "error" is both the browser's connection-failure event (a plain Event) and the name of
      // a server-sent error event (a MessageEvent carrying a JSON body).
      es.addEventListener("error", (event) => {
        if (disposed) return;
        if (event instanceof MessageEvent) {
          const data = parseJson(event.data) as StreamErrorEvent | null;
          setError(data?.message ?? "Stream error");
          return;
        }
        if (es.readyState === EventSource.CLOSED) {
          es.close();
          if (retryAttempt >= 3) {
            // Degrade gracefully to polling if SSE disconnected/timed out
            setConnection("polling");
            return;
          }
          setConnection("reconnecting");
          const delay = Math.min(10000, 2000 * Math.pow(1.5, retryAttempt));
          retryAttempt++;
          reopenTimer = setTimeout(connect, delay);
        } else {
          setConnection("reconnecting");
        }
      });
    };

    connect();

    return () => {
      disposed = true;
      if (reopenTimer !== undefined) clearTimeout(reopenTimer);
      source?.close();
    };
  }, [bundleId]);

  return { assessment, run, connection, error };
}
