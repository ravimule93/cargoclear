import type { AssessmentIteration, BBox, CheckResult } from "./types";

export interface Highlight {
  id: string;
  document_id: string;
  page: number;
  bbox: BBox;
  severity: CheckResult["severity"];
  label: string;
  field?: string;
}

export interface SourceRequest {
  page?: number;
  field?: string;
  bbox?: BBox | null;
  sequence: number;
}

/**
 * Viewer highlights come only from check evidence that carries both a page and a bbox.
 * Evidence without a box (the backend sends bbox:null) is simply not drawn.
 */
export function buildHighlights(assessment: AssessmentIteration | null): Highlight[] {
  if (!assessment) return [];

  const highlights: Highlight[] = [];
  assessment.checks.forEach((check, checkIndex) => {
    (check.evidence ?? []).forEach((evidence, index) => {
      if (typeof evidence.page !== "number" || !evidence.bbox) return;
      highlights.push({
        // check_id alone is not unique, so the check's position is part of the id
        id: `${check.check_id}:${checkIndex}:${evidence.doc}:${evidence.field}:${index}`,
        document_id: evidence.doc,
        page: evidence.page,
        bbox: evidence.bbox,
        severity: check.severity,
        label: check.message,
        field: evidence.field,
      });
    });
  });
  return highlights;
}
