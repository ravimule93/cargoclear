import { StatusEvent, IterationEvent, ErrorEvent } from "./types";

export interface SSEHandlers {
  onStatus?: (status: StatusEvent) => void;
  onIteration?: (iteration: IterationEvent) => void;
  onError?: (error: ErrorEvent) => void;
}

export function subscribeToBundle(bundleId: string, handlers: SSEHandlers): () => void {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080";
  const url = `${apiBase}/api/v1/bundles/${bundleId}/stream`;
  const es = new EventSource(url);

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
    } catch (err) {
      console.error("SSE stream connection error", err);
    }
  });

  return () => {
    es.close();
  };
}
