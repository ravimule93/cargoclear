import type { CheckResult } from "./types";

/**
 * The document a person should see first when nothing was chosen: the one the most serious finding is about.
 *
 * The check names it itself (`focus_document`: the alloy check points at the certificate, not at the invoice that carries the HS
 * code). An assessment stored before checks carried one falls back to the first document its evidence cites. Only documents of
 * the bundle on screen count, so a stale id can never select something that is not there.
 */
export function findingDocumentId(checks: readonly CheckResult[] | undefined, documentIds: readonly string[]): string | null {
  const known = (id: string | null | undefined): id is string => !!id && documentIds.includes(id);
  const material = (checks ?? []).find((c) => c.severity === "MATERIAL");
  if (!material) return null;
  if (known(material.focus_document)) return material.focus_document;
  return material.evidence?.map((e) => e.doc).find(known) ?? null;
}
