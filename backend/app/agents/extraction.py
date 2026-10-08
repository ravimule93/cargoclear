"""Extraction agent — Gemini 2.5 Flash multimodal document extraction.

Uses google-genai SDK with Pydantic response_schema to enforce strict
structured JSON output (v4.0 §2.4).

System instruction enforces extraction-only behaviour:
  "You MUST extract only what is visibly printed. Never infer or guess."

Phase 2: Uncomment the Gemini client and actual extraction.
Skeleton: Returns a synthetic ExtractedDocument stub.
"""

from __future__ import annotations

import structlog

from app.domain.schemas import ExtractedDocument, FieldRef, LineItem, BBox
from app.core.config import settings

logger = structlog.get_logger(__name__)

SYSTEM_INSTRUCTION = """
You are a document extraction engine for cross-border trade paperwork.
You MUST extract only what is visibly printed on the page.
You MUST NOT infer, complete, normalise, or guess any value.
If a field is not present, return null for value and 0.0 for confidence.
Return bounding boxes as [ymin, xmin, ymax, xmax] normalised to 0-1000,
with origin at the top-left of the page.
""".strip()

# ---- Phase 2: uncomment ----
# from google import genai
# from google.genai import types
#
# _client = genai.Client(
#     vertexai=True,
#     project=settings.project_id,
#     location=settings.gemini_live_location,  # asia-south1
# )
# ----------------------------


async def run_extraction_agent(ctx: dict) -> dict:
    """Extract structured data from all document pages in the context.

    Reads:  ctx["document_pages"]   (list[dict] with "document_id" + "payload")
    Writes: ctx["extracted"]         (list[ExtractedDocument])
    """
    document_pages: list[dict] = ctx.get("document_pages", [])
    extracted: list[ExtractedDocument] = []

    if not document_pages:
        # Skeleton: generate one synthetic document per entry in ctx["documents"]
        for doc_meta in ctx.get("documents", []):
            extracted.append(_synthetic_document(doc_meta.get("document_id", "stub-doc-1")))
        ctx["extracted"] = extracted
        return ctx

    for page_bundle in document_pages:
        doc_id = page_bundle.get("document_id", "unknown")

        # ---- Phase 2: uncomment ----
        # resp = _client.models.generate_content(
        #     model=settings.gemini_live_model,
        #     contents=page_bundle["payload"],
        #     config=types.GenerateContentConfig(
        #         response_mime_type="application/json",
        #         response_schema=ExtractedDocument,
        #         system_instruction=SYSTEM_INSTRUCTION,
        #         temperature=0.0,
        #     ),
        # )
        # if resp.parsed is None:
        #     raise ExtractionError(f"Gemini returned unparseable JSON for document {doc_id}")
        # extracted.append(resp.parsed)
        # ----------------------------

        # Skeleton: return a synthetic document
        extracted.append(_synthetic_document(doc_id))
        logger.info("extraction_stub", document_id=doc_id)

    ctx["extracted"] = extracted
    return ctx


def _synthetic_document(document_id: str) -> ExtractedDocument:
    """Return a synthetic ExtractedDocument for skeleton / testing purposes."""
    _ref = lambda v, c=0.97: FieldRef(  # noqa: E731
        value=v, confidence=c,
        bbox=BBox(page=1, ymin=100, xmin=50, ymax=150, xmax=500)
    )
    return ExtractedDocument(
        document_id=document_id,
        doc_type="COMMERCIAL_INVOICE",
        doc_type_confidence=0.98,
        document_number=_ref("INV-2024-001"),
        consignee=_ref("SINGAPORE TRADING PTE LTD"),
        consignor=_ref("MUMBAI STEEL WORKS LTD"),
        total_net_weight_kg=_ref(14000.0),
        total_gross_weight_kg=_ref(14280.0),
        line_items=[
            LineItem(
                description=_ref("Steel pipes for industrial use"),
                quantity=_ref("100 PCS"),
                net_weight_kg=_ref(14000.0),
                gross_weight_kg=_ref(14280.0),
                hs_code_declared=_ref("73041900"),
            )
        ],
    )
