/**
 * Shared TypeScript domain types.
 * In production these would be generated from the FastAPI OpenAPI schema
 * using `openapi-typescript`. For the skeleton, they are manually authored
 * to match `backend/app/domain/schemas.py` exactly.
 *
 * Generation command (Phase 1):
 *   npx openapi-typescript http://localhost:8080/openapi.json -o lib/types.ts
 */

// ---------------------------------------------------------------------------
// Primitive types
// ---------------------------------------------------------------------------

export interface BBox {
  page: number;      // 1-indexed
  ymin: number;      // 0–1000
  xmin: number;
  ymax: number;
  xmax: number;
}

export interface FieldRef {
  value: string | number | null;
  confidence: number;  // 0.0–1.0
  bbox: BBox | null;
}

// ---------------------------------------------------------------------------
// Document types
// ---------------------------------------------------------------------------

export type DocType =
  | "COMMERCIAL_INVOICE"
  | "BILL_OF_LADING"
  | "PACKING_LIST"
  | "CERTIFICATE_OF_ORIGIN"
  | "PHYTOSANITARY"
  | "MILL_TEST_CERTIFICATE"
  | "UNKNOWN";

export interface LineItem {
  description: FieldRef;
  quantity: FieldRef;
  net_weight_kg: FieldRef;
  gross_weight_kg: FieldRef;
  hs_code_declared: FieldRef;
  unit_price?: FieldRef | null;
  total_value?: FieldRef | null;
  currency?: FieldRef | null;
}

export interface ExtractedDocument {
  document_id: string;
  doc_type: DocType;
  doc_type_confidence: number;
  document_number?: FieldRef | null;
  consignee?: FieldRef | null;
  consignor?: FieldRef | null;
  vessel_or_flight?: FieldRef | null;
  invoice_value?: FieldRef | null;
  invoice_currency?: FieldRef | null;
  total_net_weight_kg?: FieldRef | null;
  total_gross_weight_kg?: FieldRef | null;
  tare_weight_kg?: FieldRef | null;
  package_count?: FieldRef | null;
  line_items: LineItem[];
}

// ---------------------------------------------------------------------------
// Compliance status
// ---------------------------------------------------------------------------

export type Status =
  | "COMPLIANT_FOR_SUBMISSION"
  | "MISSING_EVIDENCE"
  | "MATERIAL_CONTRADICTION"
  | "SPECIALIST_REVIEW_REQUIRED";

// ---------------------------------------------------------------------------
// Assessment types
// ---------------------------------------------------------------------------

export interface CheckResult {
  check_id: string;
  severity: "PASS" | "WARN" | "MATERIAL";
  message: string;
  delta?: number | null;
  tolerance?: number | null;
  evidence?: Array<{ doc: string; field?: string; bbox?: BBox }> | null;
}

export interface GroundingFinding {
  document_id: string;
  declared_hs: string | null;
  top_candidate_hs: string | null;
  top_candidate_description: string | null;
  distance: number | null;
  ambiguous: boolean;
  required_documents: string[];
}

export interface MissingEvidence {
  id: string;
  document_label: string;
  hs_code: string;
  reason: string;
  regulation_ref?: string | null;
}

export interface ReasoningDelta {
  kind: "INITIAL" | "REASSESSMENT";
  changes: Array<{
    field: string;
    from: string;
    to: string;
    because: string;
  }>;
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
  confidence: ConfidenceResult | null;
  reasoning_delta: ReasoningDelta | null;
  documents: string[];
  created_at: string | null;
}

// ---------------------------------------------------------------------------
// Bundle / Document types
// ---------------------------------------------------------------------------

export interface DocumentRecord {
  document_id: string;
  bundle_id: string;
  filename: string;
  doc_type: DocType;
  gcs_uri: string;
  sha256: string;
  bytes: number;
  uploaded_at: string;
}

export interface Bundle {
  id: string;
  reference: string | null;
  destination_country: string;
  status: string;
  current_iteration: number;
  documents: DocumentRecord[];
  created_at: string;
}

// ---------------------------------------------------------------------------
// API request/response types
// ---------------------------------------------------------------------------

export interface CreateBundleBody {
  reference?: string | null;
  destination_country?: string;
}

export interface RunResponse {
  run_id: string;
  bundle_id: string;
  state: "QUEUED" | "RUNNING" | "COMPLETE" | "ERROR";
  message?: string | null;
}

// ---------------------------------------------------------------------------
// SSE event types
// ---------------------------------------------------------------------------

export interface StatusEvent {
  kind: "status";
  bundle_id: string;
  run_id: string;
  state: "QUEUED" | "RUNNING" | "COMPLETE" | "ERROR";
  stage: string | null;
  progress: number;   // 0.0–1.0
  message: string | null;
}

export interface IterationEvent {
  kind: "iteration";
  bundle_id: string;
  iteration: number;
  status: Status;
  confidence: ConfidenceResult;
  checks: CheckResult[];
  missing_evidence: MissingEvidence[];
  reasoning_delta: ReasoningDelta;
}

export interface ErrorEvent {
  kind: "error";
  bundle_id: string;
  run_id: string;
  code: string;
  message: string;
}

// ---------------------------------------------------------------------------
// API error type
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
