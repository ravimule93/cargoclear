/**
 * Domain types for CargoClear-JAPAC frontend.
 * HAND-MAINTAINED mirror of backend/app/domain/schemas.py and of the SSE payloads backend/app/api/v1/stream.py
 * sends (the run record as repo/firestore.py writes it, and a full AssessmentIteration). Nothing generates this
 * file: change the backend model and this file in the same change.
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
  /** index of the line item, for a line-item field */
  line_item?: number | null;
  /** index of the row, for a field that is a list on the document ("test_results", "heat_numbers") */
  row?: number | null;
  page?: number | null;
  /** 0-1000 normalised, top-left origin; the backend sends null when a field has no box */
  bbox?: BBox | null;
  raw_value?: string | number | null;
  /** unit as printed, for a weight or a lab value */
  unit?: string | null;
}

export interface CheckResult {
  check_id: string;
  severity: "PASS" | "WARN" | "MATERIAL";
  message: string;
  delta?: number | null;
  tolerance?: number | null;
  evidence?: EvidenceRef[] | null;
  /** Every assumption the result depends on; a check with assumptions is never PASS or MATERIAL. */
  assumptions?: string[];
  /** Set when the check uses curated reference data: which rule set, and where it comes from (never "official" unless it is). */
  rule_set?: string | null;
  regulation_ref?: string | null;
  /** The document to look at first for this finding (the engine says; else the first document its evidence cites). Absent on older assessments. */
  focus_document?: string | null;
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

export interface DutyLine {
  name: string;
  rate_pct?: number | null;
  base?: number | null;
  amount: number;
  note?: string | null;
}

/** Indicative assessable value and duty exposure: decision support, never a determination, never the status. */
export interface ValuationEstimate {
  destination_country: string;
  status: "ESTIMATED" | "PARTIAL" | "NOT_AVAILABLE";
  reason?: string | null;
  incoterm?: string | null;
  invoice_currency?: string | null;
  destination_currency?: string | null;
  exchange_rate?: number | null;
  exchange_rate_note?: string | null;
  transaction_value?: number | null;
  freight?: number | null;
  insurance?: number | null;
  assessable_value?: number | null;
  hs_code?: string | null;
  duties: DutyLine[];
  total_duty?: number | null;
  implied_hs_code?: string | null;
  implied_total_duty?: number | null;
  assumptions: string[];
  rule_set?: string | null;
  regulation_ref?: string | null;
  disclaimer: string;
}

/** A correction by the authorised agent as one assessment used it. `skipped` = it could not be placed and was NOT used. */
export interface AppliedCorrection {
  correction_id: string;
  seq: number;
  document_id: string;
  path: string;
  anchor?: string | null;
  /** the value that replaced the extracted one; null = cleared */
  value?: string | null;
  unit?: string | null;
  /** what the model read */
  original_value?: string | null;
  original_unit?: string | null;
  reason?: string | null;
  created_at: string;
  status: "applied" | "skipped";
  note?: string | null;
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
  /** null when unknown (iterations stored before the field existed) */
  data_source?: "fixture" | "live" | null;
  /** null / absent on iterations stored before the estimate existed */
  valuation?: ValuationEstimate | null;
  /** file name -> sha256 prefix of the curated reference data the checks used */
  reference_data?: Record<string, string> | null;
  /** corrections in force when this assessment ran; absent on iterations stored before they existed */
  corrections?: AppliedCorrection[];
  /** "full" | "reassess" | "recompute"; null / absent on older iterations */
  run_mode?: string | null;
}

export interface CorrectionRequest {
  document_id: string;
  path: string;
  value?: string | null;
  unit?: string | null;
  /** true = the document does not state this value */
  clear?: boolean;
  reason?: string | null;
}

/** One entry of the correction history, read back from the audit chain. */
export interface CorrectionRecord {
  correction_id: string;
  kind: "correction" | "confirmation" | "revert";
  seq: number;
  created_at: string;
  iteration: number;
  document_id: string;
  path: string;
  anchor?: string | null;
  value?: string | null;
  unit?: string | null;
  original_value?: string | null;
  original_unit?: string | null;
  previous_value?: string | null;
  previous_unit?: string | null;
  reverts?: string | null;
  reason?: string | null;
  actor: string;
}

export interface CorrectionsResponse {
  corrections: CorrectionRecord[];
  /** the overlay in force now */
  effective: CorrectionRecord[];
  /** changes to the overlay that the latest assessment does not include yet */
  pending: number;
  latest_iteration?: number | null;
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
  /** What the uploader said the file is; an assessment flags a file the model read as another type (T-001). */
  declared_type?: string | null;
}

/** Answer of DELETE /bundles/{id}/documents/{document_id}: what was removed, and whether the newest assessment used the document. */
export interface DocumentDeleted {
  bundle_id: string;
  document_id: string;
  filename: string;
  files_removed: number;
  cached_answers_removed: number;
  latest_iteration: number | null;
  /** True: the newest assessment was made with this document and is not changed by the removal; reassess to drop it. */
  in_latest_assessment: boolean;
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
  /** the skew that was measured, whether or not it was corrected (`deskew_deg` is what was applied; 0 when none) */
  deskew_detected_deg?: number;
  /** why no deskew was applied: "disabled" | "below_threshold" | "above_limit" */
  deskew_skipped?: string | null;
  /** what the model was shown: "bw" (1-bit) or "gray" */
  image_mode?: "bw" | "gray";
  /** where the page image the model was shown is stored */
  processed_uri?: string | null;
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

export interface UserIdentity {
  user_id: string;
  email: string;
  name: string;
  tenant_id: string;
  role: "LICENSED_CHA" | "OPERATOR" | "AUDITOR" | "SYSTEM";
  issuer?: string;
}

export interface AuthConfig {
  enabled: boolean;
  oauth_client_id?: string | null;
  oauth_issuer?: string;
  allowed_email_domains: string[];
}

export interface Bundle {
  id: string;
  reference?: string | null;
  destination_country: string;
  status: Status;
  current_iteration: number;
  documents: DocumentRecord[];
  created_at: string;
  tenant_id?: string | null;
  created_by?: string | null;
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
  pipeline_engine?: string;
  auth?: AuthConfig;
  user?: UserIdentity;
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

/** One AUDIT_HEAD_SIGNED event, checked: `valid` is null when the public key could not be retrieved. */
export interface SignatureCheck {
  event_seq: number;
  signed_seq: number;
  signed_hash: string;
  signed_at?: string | null;
  /** "kms" (Cloud KMS) or "local-demo" (a throwaway key: proves the chain was not edited, not who signed) */
  signer: string;
  key: string;
  algorithm: string;
  valid: boolean | null;
  reason?: string | null;
}

export type SignatureStatus = "NOT_CONFIGURED" | "UNSIGNED" | "SIGNED" | "PARTIAL" | "INVALID" | "UNVERIFIED";

/** What the chain's signatures say: tamper-evidence under the operator's key (never legal non-repudiation). */
export interface AuditSignature {
  status: SignatureStatus;
  configured: boolean;
  signer?: string | null;
  key?: string | null;
  signed_seq?: number | null;
  /** events after the newest signed one */
  unsigned_events: number;
  /** AUDIT_SIGNING_FAILED events recorded */
  failures: number;
  signatures: SignatureCheck[];
  meaning: string;
}

export interface AuditResponse {
  events: AuditEvent[];
  verified: boolean;
  error: string | null;
  signature?: AuditSignature;
}

export interface CheckUserResponse {
  registered: boolean;
  email: string;
  name?: string | null;
  tenant_id?: string | null;
  role?: "LICENSED_CHA" | "OPERATOR" | "AUDITOR" | "SYSTEM" | null;
  auth_provider?: string | null;
}

export interface AuthResponse {
  token: string;
  user: UserIdentity;
  message: string;
}

export interface SignUpRequest {
  email: string;
  password: string;
  name: string;
  organization?: string;
  role: "LICENSED_CHA" | "OPERATOR" | "AUDITOR";
}

export interface SignInRequest {
  email: string;
  password: string;
}

export interface UserAuditRecord {
  audit_id: string;
  action: string;
  timestamp: string;
  details?: Record<string, unknown>;
}

export interface UserAuditResponse {
  email: string;
  tenant_id: string;
  total_events: number;
  audit_events: UserAuditRecord[];
}
