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

import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator

from app.core.config import settings
from app.domain.hs import HsMatchLevel

# ---------------------------------------------------------------------------
# Primitive building blocks
# ---------------------------------------------------------------------------


class BBox(BaseModel):
    """Bounding box normalised to 0–1000. Origin is top-left of the page.

    Gemini returns [ymin, xmin, ymax, xmax] as a flat list.
    We store as a structured object for clarity and type safety.
    """

    page: int = Field(description="1-indexed page number within the processed document")
    ymin: float
    xmin: float
    ymax: float
    xmax: float

    @field_validator("page")
    @classmethod
    def _validate_page(cls, v: int) -> int:
        if v < 1:
            raise ValueError("page must be >= 1")
        return v

    @field_validator("ymin", "xmin", "ymax", "xmax")
    @classmethod
    def _validate_coords(cls, v: float) -> float:
        if not (0.0 <= v <= 1000.0):
            raise ValueError("coordinate must be between 0 and 1000")
        return v



class FieldRef(BaseModel):
    """A single extracted scalar value with its provenance (confidence + bounding box).

    Used for every field that Gemini extracts so we can:
    1. Apply confidence-based routing per field.
    2. Render bounding-box highlights on the correct page.
    """

    value: str | float | int | None = None
    confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0.0–1.0")
    bbox: BBox | None = None


class QuantityRef(FieldRef):
    """A FieldRef for a measured quantity (a weight): the number as printed plus the unit as printed.

    ``value`` stays exactly as printed ("14,280.50", 14280.5, ...) and ``unit`` is what the document says
    ("KGS", "MT", "LBS", ...). Nothing is converted at extraction time; the deterministic engine converts
    with app.domain.units and reports every assumption it had to make.
    """

    unit: str | None = Field(
        default=None,
        description="unit exactly as printed, e.g. KGS, MT, LBS; never converted",
    )


def _as_quantity_ref(value: Any) -> Any:
    """Accept a plain FieldRef where a QuantityRef is expected (unit = None).

    Pydantic does not coerce a parent-class instance into a subclass-typed field, and older callers and
    fixtures build weights with FieldRef.
    """
    if isinstance(value, FieldRef) and not isinstance(value, QuantityRef):
        return QuantityRef.model_validate(value.model_dump())
    return value


WeightRef = Annotated[QuantityRef, BeforeValidator(_as_quantity_ref)]


class TextRef(FieldRef):
    """A FieldRef for text (identifiers, names, codes): the value is always a string.

    A model that returns 73041900 as a JSON number still yields "73041900": whole numbers lose any ".0",
    other numbers become their decimal text. The JSON schema offered to Gemini is a plain nullable STRING
    for these fields instead of a string/number union.
    """

    value: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _numbers_become_text(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return value  # not a number a document prints; let validation reject it
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, (int, float)):
            return str(value)
        return value


def _as_text_ref(value: Any) -> Any:
    """Accept a plain FieldRef where a TextRef is expected (its value is converted to text)."""
    if isinstance(value, FieldRef) and not isinstance(value, TextRef):
        return TextRef.model_validate(value.model_dump())
    return value


TextField = Annotated[TextRef, BeforeValidator(_as_text_ref)]


# ---------------------------------------------------------------------------
# Line items (one row of a trade document table)
# ---------------------------------------------------------------------------


class LineItem(BaseModel):
    """A single commodity line from an invoice, packing list, etc."""

    description: TextField = Field(description="Raw commodity text as it appears on the document")
    quantity: TextField = Field(description="Quantity with UOM if parseable")
    net_weight_kg: WeightRef = Field(description="Net weight as printed; unit goes in `unit`; do NOT convert to kg")
    gross_weight_kg: WeightRef = Field(description="Gross weight as printed; unit goes in `unit`; do NOT convert to kg")
    hs_code_declared: TextField = Field(description="8-digit HS tariff code, if present, as printed (text)")
    unit_price: FieldRef | None = None
    total_value: FieldRef | None = None
    currency: TextField | None = None


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
    document_number: TextField | None = None
    consignee: TextField | None = None
    consignor: TextField | None = None
    vessel_or_flight: TextField | None = None
    port_of_loading: TextField | None = None
    port_of_discharge: TextField | None = None
    shipment_date: TextField | None = None

    # Financial (primarily on Commercial Invoice)
    invoice_value: FieldRef | None = None
    invoice_currency: TextField | None = None

    # Weight summary (from Packing List or Bill of Lading)
    total_net_weight_kg: WeightRef | None = Field(
        default=None, description="Total net weight as printed; unit goes in `unit`; do NOT convert to kg"
    )
    total_gross_weight_kg: WeightRef | None = Field(
        default=None, description="Total gross weight as printed; unit goes in `unit`; do NOT convert to kg"
    )
    tare_weight_kg: WeightRef | None = Field(
        default=None, description="Tare weight as printed; unit goes in `unit`; do NOT convert to kg"
    )
    package_count: FieldRef | None = None

    # HS code at header level (some invoices declare it once)
    hs_code_header: TextField | None = None

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
    assumptions: list[str] = Field(
        default_factory=list,
        description="Every assumption the result depends on; a check with assumptions is never PASS or MATERIAL",
    )


class GroundingFinding(BaseModel):
    """Result of a BigQuery Vector Search grounding check for one commodity."""

    document_id: str
    declared_hs: str | None
    top_candidate_hs: str | None
    top_candidate_description: str | None
    distance: float | None
    ambiguous: bool
    hs_mismatch: bool = False
    required_documents: list[str] = Field(default_factory=list)
    hs_match_level: HsMatchLevel | None = Field(
        default=None,
        description="How the declared code matches the governing tariff row (exact8, subheading6, heading4, none, "
        "not_declared); null on iterations stored before this field existed",
    )
    governing_hs: str | None = Field(
        default=None,
        description="HS code of the retrieved row that best matches the declared code (the row required documents "
        "come from); null when no row governs",
    )
    rule_set: str | None = Field(default=None, description="Rule set of the governing row, e.g. 'demo-curated'")
    regulation_ref: str | None = Field(default=None, description="Reference of the governing row's rule")
    better_match_hs: str | None = Field(
        default=None,
        description="Set when the declared code exists in the tariff but the description fits a different 8-digit "
        "code much better (the contradicting row's HS code); null otherwise",
    )


class MissingEvidence(BaseModel):
    """A required document that is missing from the bundle."""

    id: str
    document_label: str
    hs_code: str
    reason: str
    regulation_ref: str | None = None
    rule_set: str | None = None


class ReasoningDelta(BaseModel):
    """Before/after diff between two assessment iterations."""

    kind: Literal["INITIAL", "REASSESSMENT"]
    changes: list[dict] = Field(default_factory=list)
    narrative: str


class ConfidenceResult(BaseModel):
    """Output of the confidence routing service."""

    min_field_confidence: float = Field(
        description="Minimum confidence over the fields the checks cite (all populated fields when no check cites "
        "one); the figure the UI shows"
    )
    action: Literal["AUTO_ACCEPT", "AUTO_FLAG", "INTERACTIVE_REVIEW", "MANUAL_ENTRY"]
    min_overall_confidence: float | None = Field(
        default=None, description="Minimum confidence over EVERY populated field, cited or not; null if none"
    )
    min_doc_type_confidence: float | None = Field(
        default=None, description="Minimum doc_type_confidence over all extracted documents; null if none"
    )
    low_confidence_fields: list[dict] = Field(
        default_factory=list,
        description="Up to 10 cited fields below 0.95, ascending, as {document_id, field, line_item?, confidence, "
        "used_by: [check_id]}, plus {document_id, field: 'doc_type', confidence} for each document whose "
        "classification is below 0.95",
    )
    reason: str | None = Field(default=None, description="One sentence naming what determined the tier")


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
    data_source: Literal["live", "fixture"] | None = Field(
        default=None,
        description="Where the data came from: 'fixture' if extraction used fixtures or the tariff came "
        "from the local seed, 'live' otherwise; null if unknown (e.g. iterations stored before this field).",
    )
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
        pattern=r"^[A-Za-z]{2}$",
        description="ISO 3166-1 alpha-2 destination country code",
    )

    @field_validator("reference")
    @classmethod
    def _clean_reference(cls, value: str | None) -> str | None:
        """Control characters removed, stripped, and bounded by MAX_REFERENCE_CHARS (longer is refused, not cut)."""
        if value is None:
            return None
        cleaned = "".join(ch for ch in value if unicodedata.category(ch) != "Cc").strip()
        limit = settings.max_reference_chars
        if len(cleaned) > limit:
            raise ValueError(f"reference must be at most {limit} characters")
        return cleaned


class DocumentResponse(BaseModel):
    document_id: str
    bundle_id: str
    filename: str
    doc_type: str
    gcs_uri: str
    sha256: str
    bytes: int
    uploaded_at: str
    transform_meta_uri: str | None = Field(
        default=None,
        description="Durable location of per-page preprocessing transforms; null until preprocessing completes.",
    )


class TransformMetadataResponse(BaseModel):
    document_id: str
    transform_meta: list[dict[str, Any]] = Field(
        description="Per-page preprocessing transforms used to map evidence coordinates to the original document."
    )


class BundleResponse(BaseModel):
    id: str
    reference: str | None
    destination_country: str
    status: str
    current_iteration: int
    documents: list[DocumentResponse] = Field(default_factory=list)
    created_at: str
    tenant_id: str | None = Field(default=None, description="Multi-tenant brokerage organization domain")
    created_by: str | None = Field(default=None, description="Email of the creator / Customs House Agent")



class RunResponse(BaseModel):
    run_id: str
    bundle_id: str
    state: Literal["QUEUED", "RUNNING", "COMPLETE", "ERROR"]
    message: str | None = None
