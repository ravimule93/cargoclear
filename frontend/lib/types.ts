/**
 * Domain types for CargoClear-JAPAC frontend.
 * Mirrors backend/app/domain/schemas.py and backend/app/domain/events.py.
 */

export type Status =
  | "COMPLIANT_FOR_SUBMISSION"
  | "MISSING_EVIDENCE"
  | "MATERIAL_CONTRADICTION"
  | "SPECIALIST_REVIEW_REQUIRED";

export interface BBox {
  page: number;
  ymin: number;
  xmin: number;
  ymax: number;
  xmax: number;
}

export interface FieldRef {
  value?: string | number | null;
  confidence: number;
  bbox?: BBox | null;
}

export interface EvidenceRef {
  /** document_id of the document the evidence points into */
  doc: string;
  field: string;
  page?: number | null;
  /** 0-1000 normalised, top-left origin; the backend sends null when a field has no box */
  bbox?: BBox | null;
  raw_value?: string | number | null;
}

export interface CheckResult {
  check_id: string;
  severity: "PASS" | "WARN" | "MATERIAL";
  message: string;
  delta?: number | null;
  tolerance?: number | null;
  evidence?: EvidenceRef[] | null;
}

export interface GroundingFinding {
  document_id: string;
  declared_hs?: string | null;
  top_candidate_hs?: string | null;
  top_candidate_description?: string | null;
  distance?: number | null;
  ambiguous: boolean;
  hs_mismatch: boolean;
  required_documents: string[];
}

export interface MissingEvidence {
  id: string;
  document_label: string;
  hs_code: string;
  reason: string;
  regulation_ref?: string | null;
}

export interface ReasoningDeltaChange {
  field?: string;
  from?: string;
  to?: string;
  because?: string;
  [key: string]: unknown;
}

export interface ReasoningDelta {
  kind: "INITIAL" | "REASSESSMENT";
  changes?: ReasoningDeltaChange[];
  narrative: string;
}

export interface ConfidenceResult {
  min_field_confidence: number;
  action: "AUTO_ACCEPT" | "AUTO_FLAG" | "INTERACTIVE_REVIEW" | "MANUAL_ENTRY";
}

export interface AssessmentIteration {
  iteration: number;
  bundle_id: string;
  status: Status;
  checks: CheckResult[];
  grounding: GroundingFinding[];
  missing_evidence: MissingEvidence[];
  confidence?: ConfidenceResult | null;
  reasoning_delta?: ReasoningDelta | null;
  documents: string[];
  created_at?: string | null;
  data_source?: "fixture" | "live";
}

export interface DocumentRecord {
  document_id: string;
  bundle_id: string;
  filename: string;
  doc_type: string;
  gcs_uri: string;
  sha256: string;
  bytes: number;
  uploaded_at: string;
  transform_meta_uri?: string | null;
}

/** Per-page preprocessing metadata returned through the scoped backend endpoint. */
export interface TransformMetadata {
  page: number;
  /** Original one-indexed PDF page. Absent on metadata written before provenance upgrades. */
  source_page?: number;
  /** One-indexed page position inside the processed artifact. */
  processed_page?: number;
  document_id: string;
  deskew_deg: number;
  deskew_applied?: boolean;
  rotation: number;
  rotation_applied?: boolean;
  /** Normalized processed-to-source affine matrix, present for newly transformed records. */
  processed_to_source_affine?: number[][];
  artifact_index?: number;
  artifact_page?: number;
  artifact_id?: string | null;
  split_offset: number;
  width: number;
  height: number;
}

export interface TransformMetadataResponse {
  document_id: string;
  transform_meta: TransformMetadata[];
}

export interface Bundle {
  id: string;
  reference?: string | null;
  destination_country: string;
  status: Status;
  current_iteration: number;
  documents: DocumentRecord[];
  created_at: string;
}

export interface StatusEvent {
  kind: "status";
  bundle_id: string;
  run_id: string;
  state: "QUEUED" | "RUNNING" | "COMPLETE" | "ERROR";
  stage?: string | null;
  progress: number;
  message?: string | null;
}

/** Payload of the SSE `error` event (server-side stream failure). */
export interface StreamErrorEvent {
  kind: "error";
  bundle_id: string;
  code: string;
  message: string;
}

export interface RunResponse {
  run_id: string;
  bundle_id: string;
  state: "QUEUED" | "RUNNING" | "COMPLETE" | "ERROR";
  message?: string | null;
}

export type AppMode = "demo" | "live";

export interface Meta {
  app_mode: AppMode;
  data_source_policy: string;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  detail?: unknown;
  request_id?: string;
}

export interface AuditEvent {
  event_id: string;
  bundle_id: string;
  iteration: number;
  seq: number;
  /** ISO-8601 timestamp (note: `ts`, not `timestamp`) */
  ts: string;
  actor: string;
  event_type: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface AuditResponse {
  events: AuditEvent[];
  verified: boolean;
  error: string | null;
}
