import type { ErrorEnvelope } from "./types";

/** Narrow an unknown thrown value to the backend error envelope that lib/api.ts throws. */
export function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { code?: unknown }).code === "string" &&
    typeof (value as { message?: unknown }).message === "string"
  );
}

/**
 * Normalise anything thrown by a request into an envelope. lib/api.ts throws the backend
 * envelope as a plain object (not an Error); network failures surface as TypeError.
 */
export function toErrorEnvelope(err: unknown): ErrorEnvelope {
  if (isErrorEnvelope(err)) return err;
  if (err instanceof Error) return { code: "CLIENT_ERROR", message: err.message };
  return { code: "CLIENT_ERROR", message: "Unexpected error" };
}

export function isNotFound(err: unknown): boolean {
  return isErrorEnvelope(err) && err.code === "NOT_FOUND";
}

/** User-facing text for run-control (analyze / reassess) failures. */
export function runErrorMessage(err: unknown): string {
  const envelope = toErrorEnvelope(err);
  if (envelope.code === "CONFLICT") return "An analysis is already running for this bundle.";
  if (envelope.code === "VALIDATION_ERROR") return "Upload at least one document before analyzing.";
  return envelope.message;
}
