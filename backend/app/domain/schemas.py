"""Domain schemas — the single contract between backend services, agents, and frontend.

These Pydantic models are the source of truth. The frontend lib/types.ts is
generated from the FastAPI OpenAPI schema (via ``openapi-typescript``), so
frontend and backend types never drift.

Design rules from v4.0 §2.4:
  - No discriminated unions.
  - No deeply nested arrays (flatten to X | None).
  - Every optional field is ``X | None`` with explicit ``= None``.
  - These rules keep JSON-mode failure rates low with Gemini.
"""

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Primitive building blocks
# ---------------------------------------------------------------------------


class BBox(BaseModel):
    """Bounding box normalised to 0–1000. Origin is top-left of the page.

    Gemini returns [ymin, xmin, ymax, xmax] as a flat list.
    We store as a structured object for clarity and type safety.
    """

    page: int = Field(ge=1, description="1-indexed page number within the processed document")
    ymin: float = Field(ge=0, le=1000)
    xmin: float = Field(ge=0, le=1000)
    ymax: float = Field(ge=0, le=1000)
    xmax: float = Field(ge=0, le=1000)


class FieldRef(BaseModel):
    """A single extracted scalar value with its provenance (confidence + bounding box).

    Used for every field that Gemini extracts so we can:
    1. Apply confidence-based routing per field.
    2. Render bounding-box highlights on the correct page.
    """

    value: str | float | int | None = None
    confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0.0–1.0")
    bbox: BBox | None = None


# ---------------------------------------------------------------------------
# Line items (one row of a trade document table)
# ---------------------------------------------------------------------------


class LineItem(BaseModel):
    """A single commodity line from an invoice, packing list, etc."""

    description: FieldRef = Field(description="Raw commodity text as it appears on the document")
    quantity: FieldRef = Field(description="Quantity with UOM if parseable")
    net_weight_kg: FieldRef = Field(description="Net weight normalised to kilograms")
    gross_weight_kg: FieldRef = Field(description="Gross weight normalised to kilograms")
    hs_code_declared: FieldRef = Field(description="8-digit HS tariff code, if present")
    unit_price: FieldRef | None = None
    total_value: FieldRef | None = None
    currency: FieldRef | None = None


# ---------------------------------------------------------------------------
# Document types
# ---------------------------------------------------------------------------

DocType = Literal[
    "COMMERCIAL_INVOICE",
    "BILL_OF_LADING",
    "PACKING_LIST",
    "CERTIFICATE_OF_ORIGIN",
    "PHYTOSANITARY",
    "MILL_TEST_CERTIFICATE",
    "UNKNOWN",
]


class ExtractedDocument(BaseModel):
    """Structured extraction output for one trade document.

    Produced by the Extraction Agent (Gemini 2.5 Flash) and consumed by
    the Discrepancy Agent (pure Python math engine) and Grounding Agent.
    """

    document_id: str = Field(description="Matches the EvidenceDocument.document_id in Firestore")
    doc_type: DocType
    doc_type_confidence: float = Field(ge=0.0, le=1.0)

    # Header-level fields — present on most documents
    document_number: FieldRef | None = None
    consignee: FieldRef | None = None
    consignor: FieldRef | None = None
    vessel_or_flight: FieldRef | None = None
    port_of_loading: FieldRef | None = None
    port_of_discharge: FieldRef | None = None
    shipment_date: FieldRef | None = None

    # Financial (primarily on Commercial Invoice)
    invoice_value: FieldRef | None = None
    invoice_currency: FieldRef | None = None

    # Weight summary (from Packing List or Bill of Lading)
    total_net_weight_kg: FieldRef | None = None
    total_gross_weight_kg: FieldRef | None = None
    tare_weight_kg: FieldRef | None = None
    package_count: FieldRef | None = None

    # HS code at header level (some invoices declare it once)
    hs_code_header: FieldRef | None = None

    # Commodity line items
    line_items: list[LineItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Assessment output schemas
# ---------------------------------------------------------------------------


class CheckResult(BaseModel):
    """Result of a single deterministic check."""

    check_id: str = Field(description="Unique check identifier e.g. W-001, H-002, E-consignee")
    severity: Literal["PASS", "WARN", "MATERIAL"]
    message: str
    delta: float | None = None
    tolerance: float | None = None
    evidence: list[dict] | None = None  # [{doc, field, bbox}]


class GroundingFinding(BaseModel):
    """Result of a BigQuery Vector Search grounding check for one commodity."""

    document_id: str
    declared_hs: str | None
    top_candidate_hs: str | None
    top_candidate_description: str | None
    distance: float | None
    ambiguous: bool
    required_documents: list[str] = Field(default_factory=list)


class MissingEvidence(BaseModel):
    """A required document that is missing from the bundle."""

    id: str
    document_label: str
    hs_code: str
    reason: str
    regulation_ref: str | None = None


class ReasoningDelta(BaseModel):
    """Before/after diff between two assessment iterations."""

    kind: Literal["INITIAL", "REASSESSMENT"]
    changes: list[dict] = Field(default_factory=list)
    narrative: str


class ConfidenceResult(BaseModel):
    """Output of the confidence routing service."""

    min_field_confidence: float
    action: Literal["AUTO_ACCEPT", "AUTO_FLAG", "INTERACTIVE_REVIEW", "MANUAL_ENTRY"]


class AssessmentIteration(BaseModel):
    """Point-in-time, immutable assessment snapshot stored in Firestore."""

    iteration: int
    bundle_id: str
    status: str  # One of the 4 Status enum values
    checks: list[CheckResult] = Field(default_factory=list)
    grounding: list[GroundingFinding] = Field(default_factory=list)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list)
    confidence: ConfidenceResult | None = None
    reasoning_delta: ReasoningDelta | None = None
    documents: list[str] = Field(default_factory=list, description="document_ids included")
    created_at: str | None = None


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------


class CreateBundleRequest(BaseModel):
    reference: str | None = Field(
        default=None,
        description="Optional human-readable reference (e.g. shipment number)",
    )
    destination_country: str = Field(
        default="SG",
        description="ISO 3166-1 alpha-2 destination country code",
    )


class BundleResponse(BaseModel):
    id: str
    reference: str | None
    destination_country: str
    status: str
    current_iteration: int
    documents: list[dict] = Field(default_factory=list)
    created_at: str


class DocumentResponse(BaseModel):
    document_id: str
    bundle_id: str
    filename: str
    doc_type: str
    gcs_uri: str
    sha256: str
    bytes: int
    uploaded_at: str


class RunResponse(BaseModel):
    run_id: str
    bundle_id: str
    state: Literal["QUEUED", "RUNNING", "COMPLETE", "ERROR"]
    message: str | None = None
