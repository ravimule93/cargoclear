import { StatusEvent, IterationEvent, ErrorEvent } from "./types";

export interface SSEHandlers {
  onStatus?: (status: StatusEvent) => void;
  onIteration?: (iteration: IterationEvent) => void;
  onError?: (error: ErrorEvent) => void;
}

export function subscribeToBundle(bundleId: string, handlers: SSEHandlers): () => void {
  if (!bundleId) return () => {};

  // Route through Next.js proxy route (/api/proxy/...) so it works identically
  // in local dev, Docker, and Cloud Run without hardcoded origins or CORS issues.
  const url = `/api/proxy/bundles/${bundleId}/stream`;
  let es: EventSource;

  try {
    es = new EventSource(url);
  } catch (err) {
    console.debug("SSE EventSource init failed", err);
    return () => {};
  }

  es.addEventListener("status", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as StatusEvent;
      handlers.onStatus?.(data);
    } catch (err) {
      console.error("Failed to parse SSE status event", err);
    }
  });

  es.addEventListener("iteration", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as IterationEvent;
      handlers.onIteration?.(data);
    } catch (err) {
      console.error("Failed to parse SSE iteration event", err);
    }
  });

  es.addEventListener("error", (e: Event) => {
    try {
      const msgEvent = e as MessageEvent;
      if (msgEvent.data) {
        const data = JSON.parse(msgEvent.data) as ErrorEvent;
        handlers.onError?.(data);
      }
    } catch {
      // Silent error fallback
    }
  });

  es.onerror = () => {
    handlers.onError?.({
      kind: "error",
      bundle_id: bundleId,
      run_id: "",
      code: "STREAM_UNAVAILABLE",
      message: "Live stream unavailable. Fallback polling active.",
    });
  };

  return () => {
    es.close();
  };
}
