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
 * Subscribes to the same-origin /api/proxy/bundles/{id}/stream with automatic fallback to polling.
 *
 * If the connection cannot be established or is buffered by an intermediate CDN (e.g. Firebase Hosting
 * edge rewrites), a watchdog timer automatically degrades to adaptive polling after 3.5s so live updates
 * are never blocked or stuck on "connecting".
 */
export function useBundleStream(bundleId: string | null): BundleStream {
  const [assessment, setAssessment] = useState<AssessmentIteration | null>(null);
  const [run, setRun] = useState<StreamRunState | null>(null);
  const [connection, setConnection] = useState<StreamConnection>("connecting");
  const [error, setError] = useState<string | null>(null);

  // 1. SSE Connection effect
  useEffect(() => {
    setAssessment(null);
    setRun(null);
    setError(null);
    setConnection("connecting");

    if (!bundleId) return;

    const url = `/api/proxy/bundles/${encodeURIComponent(bundleId)}/stream`;

    let disposed = false;
    let source: EventSource | null = null;
    let reopenTimer: ReturnType<typeof setTimeout> | undefined;
    let watchdogTimer: ReturnType<typeof setTimeout> | undefined;
    let retryAttempt = 0;

    const connect = () => {
      if (disposed) return;
      const es = new EventSource(url);
      source = es;

      // Watchdog: If edge CDN or reverse proxy buffers SSE and never fires open,
      // fallback smoothly to active polling after 3.5s.
      if (watchdogTimer !== undefined) clearTimeout(watchdogTimer);
      watchdogTimer = setTimeout(() => {
        if (disposed) return;
        if (es.readyState === EventSource.CONNECTING) {
          console.info("[BundleStream] SSE connection pending; transitioning to polling fallback.");
          es.close();
          setConnection("polling");
        }
      }, 3500);

      es.addEventListener("open", () => {
        if (disposed) return;
        if (watchdogTimer !== undefined) clearTimeout(watchdogTimer);
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

        if (watchdogTimer !== undefined) clearTimeout(watchdogTimer);

        if (es.readyState === EventSource.CLOSED || retryAttempt >= 2) {
          es.close();
          // Degrade gracefully to polling if SSE disconnected or timed out
          setConnection("polling");
          return;
        }

        setConnection("reconnecting");
        const delay = Math.min(10000, 2000 * Math.pow(1.5, retryAttempt));
        retryAttempt++;
        reopenTimer = setTimeout(connect, delay);
      });
    };

    connect();

    return () => {
      disposed = true;
      if (watchdogTimer !== undefined) clearTimeout(watchdogTimer);
      if (reopenTimer !== undefined) clearTimeout(reopenTimer);
      source?.close();
    };
  }, [bundleId]);

  // 2. Active Polling fallback effect when connection === "polling"
  useEffect(() => {
    if (connection !== "polling" || !bundleId) return;

    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      if (cancelled) return;
      try {
        // Fetch run status
        const statusRes = await fetch(`/api/proxy/bundles/${encodeURIComponent(bundleId)}/status`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        if (statusRes.ok && !cancelled) {
          const statusData = await statusRes.json();
          if (isStatusPayload(statusData)) {
            setRun({
              run_id: statusData.run_id,
              state: statusData.state,
              stage: statusData.stage,
              progress: statusData.progress,
              message: statusData.message,
            });
            setError(statusData.state === "ERROR" ? (statusData.message ?? "Pipeline run failed") : null);
          }
        }

        // Fetch latest assessment
        const assessRes = await fetch(`/api/proxy/bundles/${encodeURIComponent(bundleId)}/assessment`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        if (assessRes.ok && !cancelled) {
          const assessData = await assessRes.json();
          if (isIterationPayload(assessData)) {
            setAssessment((prev) => (prev && assessData.iteration < prev.iteration ? prev : assessData));
          }
        }
      } catch (err) {
        console.debug("[BundleStream] Polling cycle error:", err);
      } finally {
        if (!cancelled) {
          // Poll faster (2000ms) while running/queued, slower (5000ms) when idle
          const interval = run?.state === "RUNNING" || run?.state === "QUEUED" ? 2000 : 5000;
          pollTimer = setTimeout(poll, interval);
        }
      }
    };

    void poll();

    return () => {
      cancelled = true;
      if (pollTimer !== undefined) clearTimeout(pollTimer);
    };
  }, [connection, bundleId, run?.state]);

  return { assessment, run, connection, error };
}
