"""The declaration pre-fill pack: CargoClear's own, documented JSON for the person who keys the declaration.

NOT a government format. Whether Indian (ICEGATE) or Singaporean (TradeNet) declarations have a public machine schema that
can be targeted has not been confirmed (see docs/PREFILL_PACK.md); until it is, this pack carries the values the documents
state, in plain names, with where each came from, so that a declarant can type, paste or script them into the form.

Every value says: which document it was read from (and where on the page), how sure the extraction was, whether the agent
corrected it, what the OTHER documents say, and whether a person should look at it before using it. A pack for a bundle that
is not cleared says so at the top and lists what blocks it. The pack never claims a declaration is ready to file.

Bump ``SCHEMA_VERSION`` for any change to this file that a consumer of the JSON could notice; the committed JSON Schema
(docs/schemas/declaration-prefill.schema.json) is checked against these models by a test.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.schemas import AppliedCorrection, BBox, ValuationEstimate

SCHEMA_ID = "cargoclear.declaration-prefill"
SCHEMA_VERSION = "1.0"

DISCLAIMER = (
    "Pre-fill for the authorised declarant. These are values READ from the trade documents by CargoClear (and corrected by "
    "the agent where stated), not a filed declaration and not a customs determination. Check every value against the "
    "source document before it is used; fields marked for review need a person's eyes. The duty figures are an indicative "
    "estimate, never an amount payable."
)


class PrefillSource(BaseModel):
    document_id: str = Field(description="id of the document the value was read from")
    filename: str | None = Field(default=None, description="its file name as uploaded")
    doc_type: str = Field(description="what kind of document it is, e.g. COMMERCIAL_INVOICE")
    page: int | None = Field(default=None, description="1-indexed page the value is on, when the extraction located it")
    bbox: BBox | None = None


class PrefillAlternative(BaseModel):
    """What another document states for the same field."""

    document_id: str = Field(description="the other document")
    doc_type: str = Field(description="its document type")
    value: str | None = Field(default=None, description="what it states, as printed")
    unit: str | None = Field(default=None, description="its unit, as printed")


class PrefillValue(BaseModel):
    """One value of the declaration with its provenance."""

    value: str | None = Field(default=None, description="as printed on the source document; null = no document states it")
    unit: str | None = Field(default=None, description="unit as printed, for weights and certificate values")
    source: PrefillSource | None = Field(default=None, description="where the value was read from; null when no document states it")
    confidence: float | None = Field(default=None, description="extraction confidence 0-1; 1.0 for a value the agent corrected or confirmed")
    corrected: bool = Field(default=False, description="true when the agent corrected this value (the model read something else)")
    alternatives: list[PrefillAlternative] = Field(default_factory=list, description="what the other documents state for this field")
    conflict: bool = Field(default=False, description="true when the documents disagree on this field")
    review: list[str] = Field(default_factory=list, description="why a person should check this value before using it; empty = nothing flagged")


class PrefillParties(BaseModel):
    consignee: PrefillValue
    consignor: PrefillValue


class PrefillShipment(BaseModel):
    invoice_number: PrefillValue
    bill_of_lading_number: PrefillValue
    packing_list_number: PrefillValue
    vessel_or_flight: PrefillValue
    port_of_loading: PrefillValue
    port_of_discharge: PrefillValue
    shipment_date: PrefillValue
    incoterm: PrefillValue
    country_of_origin: PrefillValue
    package_count: PrefillValue
    total_gross_weight: PrefillValue
    total_net_weight: PrefillValue


class PrefillCommercial(BaseModel):
    invoice_value: PrefillValue
    invoice_currency: PrefillValue
    freight_amount: PrefillValue
    freight_currency: PrefillValue
    insurance_amount: PrefillValue
    insurance_currency: PrefillValue


class PrefillLine(BaseModel):
    """One commodity line, as the invoice (else the packing list) states it."""

    line_no: int = Field(description="1-indexed position on the source document")
    document_id: str = Field(description="the document the lines are read from (the invoice, else the packing list)")
    description: PrefillValue
    hs_code: PrefillValue
    quantity: PrefillValue
    unit_price: PrefillValue
    unit_price_basis: PrefillValue
    line_value: PrefillValue
    currency: PrefillValue
    net_weight: PrefillValue
    gross_weight: PrefillValue


class PrefillMaterial(BaseModel):
    """What the mill test certificate states (empty when the bundle has none)."""

    certificate_document_id: str | None = Field(default=None, description="the mill test certificate the values are read from; null when the bundle has none")
    specification: PrefillValue = Field(description="product standard / grade as printed on the certificate")
    heat_numbers: list[str] = Field(default_factory=list, description="every heat number the certificate prints, each once")


class PrefillFinding(BaseModel):
    check_id: str = Field(description="the check, e.g. M-001")
    severity: str = Field(description="MATERIAL (a contradiction) or WARN (a specialist should look)")
    message: str = Field(description="what the check found, in words")


class PrefillAssessment(BaseModel):
    iteration: int = Field(description="the assessment this pack is made from")
    status: str = Field(description="COMPLIANT_FOR_SUBMISSION, MISSING_EVIDENCE, MATERIAL_CONTRADICTION or SPECIALIST_REVIEW_REQUIRED")
    run_mode: str | None = Field(default=None, description="full, reassess or recompute")
    created_at: str | None = Field(default=None, description="when the assessment was made (ISO-8601)")
    data_source: str | None = Field(default=None, description="live, or fixture when synthetic demo data was used")
    blocking: list[PrefillFinding] = Field(default_factory=list, description="MATERIAL findings: contradictions to resolve")
    review: list[PrefillFinding] = Field(default_factory=list, description="WARN findings: a specialist should look")
    missing_documents: list[str] = Field(default_factory=list)
    pending_corrections: int = Field(default=0, description="corrections the agent made that this assessment does not include yet")


class PrefillDeclaration(BaseModel):
    destination_country: str = Field(description="ISO 3166-1 alpha-2 code of the destination")
    declaration: str = Field(description="what the destination calls it, from the curated reference data (unverified until reviewed)")
    rule_set: str = Field(description="label of that reference data, e.g. demo-curated: never presented as official")
    regulation_ref: str = Field(description="where that reference data comes from, in the words it states")


class PrefillInput(BaseModel):
    id: str = Field(description="short identifier, e.g. IEC")
    label: str = Field(description="what the declarant must supply")


class PrefillDocument(BaseModel):
    document_id: str = Field(description="id of the document (content-addressed)")
    filename: str = Field(description="file name as uploaded")
    doc_type: str = Field(description="document type as classified")
    sha256: str = Field(description="SHA-256 of the uploaded file")
    bytes: int = Field(description="size of the uploaded file")


class PrefillProvenance(BaseModel):
    audit_events: int = Field(description="events in the bundle's audit chain when the pack was made")
    audit_head_hash: str | None = Field(default=None, description="hash of the newest audit event: ties the pack to the trail")
    audit_chain_verified: bool = Field(description="whether the audit chain verified when the pack was made")
    reference_data: dict[str, str] | None = Field(default=None, description="the curated tables the assessment used (file -> sha256 prefix)")


class PrefillIntegrity(BaseModel):
    content_sha256: str = Field(description="SHA-256 of this document's canonical JSON with this block removed")


class PrefillPack(BaseModel):
    schema_id: str = SCHEMA_ID
    schema_version: str = SCHEMA_VERSION
    generated_at: str = Field(description="when the pack was made (ISO-8601, UTC)")
    disclaimer: str = Field(default=DISCLAIMER, description="what this pack is and is not; always present")
    banner: str | None = Field(default=None, description="set when the bundle is NOT cleared: say so before anything else is read")
    bundle_id: str = Field(description="the CargoClear bundle")
    reference: str | None = Field(default=None, description="the bundle's human-readable reference (e.g. a shipment number)")
    declaration: PrefillDeclaration
    assessment: PrefillAssessment
    parties: PrefillParties
    shipment: PrefillShipment
    commercial: PrefillCommercial
    lines: list[PrefillLine] = Field(default_factory=list)
    material: PrefillMaterial
    valuation: ValuationEstimate | None = Field(default=None, description="the indicative duty estimate of the assessment; never an amount payable")
    to_be_supplied: list[PrefillInput] = Field(default_factory=list, description="what the declarant must supply: no trade document carries it")
    corrections: list[AppliedCorrection] = Field(default_factory=list, description="the agent's corrections this pack's values include")
    documents: list[PrefillDocument] = Field(default_factory=list)
    provenance: PrefillProvenance
    integrity: PrefillIntegrity
