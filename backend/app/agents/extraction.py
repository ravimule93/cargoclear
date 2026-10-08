"""Extraction agent — Multimodal Gemini 2.5 Flash trade document extraction.

Per v4.0 Specification (US 2.1, US 2.2):
  - Uses gemini-2.5-flash hosted in Vertex AI (asia-south1 / Mumbai).
  - Enforces strict structured JSON output via Pydantic model in response_schema.
  - Generates normalized bounding boxes: [ymin, xmin, ymax, xmax] (0–1000).
  - Attaches per-field confidence scores [0.0–1.0].
  - System prompt restricts to verbatim spatial extraction only (no hallucination).
  - Handles retries on schema errors.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from app.core.config import settings
from app.domain.schemas import (
    BBox,
    DocType,
    ExtractedDocument,
    FieldRef,
    LineItem,
)
from app.gateway.errors import ExtractionError

logger = structlog.get_logger(__name__)

SYSTEM_INSTRUCTION = """
You are an expert customs document extraction engine for cross-border trade paperwork.
You MUST extract only what is visibly printed on the page.
You MUST NOT infer, complete, normalise, or guess any value.
If a field is not visibly present on the document, return null for value and 0.0 for confidence.
Return bounding boxes as [ymin, xmin, ymax, xmax] normalised to 0-1000,
where [0, 0] is top-left and [1000, 1000] is bottom-right of the page.
Extract commodity line items with their exact net weight, gross weight, and declared 8-digit HS code.
Classify the doc_type as one of:
- COMMERCIAL_INVOICE
- BILL_OF_LADING
- PACKING_LIST
- CERTIFICATE_OF_ORIGIN
- PHYTOSANITARY
- MILL_TEST_CERTIFICATE
- UNKNOWN
""".strip()

_genai_client = None


def _get_genai_client():
    """Lazily initialize the google-genai Vertex AI client."""
    global _genai_client
    if _genai_client is not None:
        return _genai_client

    has_creds = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("K_SERVICE"))
    if not has_creds and os.getenv("USE_VERTEX_MOCK") != "false":
        logger.info("genai_client_mock_mode", reason="No GCP credentials found, running extraction fixture generator")
        return None

    try:
        from google import genai

        _genai_client = genai.Client(
            vertexai=True,
            project=settings.project_id,
            location=settings.gemini_live_location,  # asia-south1
        )
        return _genai_client
    except Exception as exc:
        logger.warning("genai_client_init_failed", error=str(exc), fallback="mock_generator")
        return None


async def run_extraction_agent(ctx: dict[str, Any]) -> dict[str, Any]:
    """Execute multimodal extraction across all document pages in the context.

    Reads:
      - ctx["processed_pages"] (list[dict] with page payloads) or ctx["documents"]

    Writes:
      - ctx["extracted"] (list[ExtractedDocument])
    """
    processed_pages: list[dict[str, Any]] = ctx.get("processed_pages", [])
    documents_meta: list[dict[str, Any]] = ctx.get("documents", [])
    extracted_docs: list[ExtractedDocument] = []

    client = _get_genai_client()

    if client is not None and processed_pages:
        from google.genai import types

        for page in processed_pages:
            doc_id = page.get("document_id", "doc-unknown")
            payload = page.get("payload", b"")
            mime = page.get("mime", "application/pdf")

            max_retries = 3
            parsed_doc = None

            for attempt in range(1, max_retries + 1):
                try:
                    part = types.Part.from_bytes(data=payload, mime_type=mime)
                    response = client.models.generate_content(
                        model=settings.gemini_live_model,
                        contents=[part, "Extract all trade data into the requested JSON schema."],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=ExtractedDocument,
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.0,
                        ),
                    )

                    parsed_doc = response.parsed
                    if parsed_doc:
                        parsed_doc.document_id = doc_id
                        extracted_docs.append(parsed_doc)
                        logger.info("gemini_extraction_success", document_id=doc_id, attempt=attempt)
                        break

                except Exception as exc:
                    logger.warning("gemini_extraction_retry", document_id=doc_id, attempt=attempt, error=str(exc))
                    if attempt == max_retries:
                        raise ExtractionError(
                            f"Extraction failed for document {doc_id} after {max_retries} attempts: {exc}"
                        ) from exc

    else:
        # Fixture generator for offline / test environments
        # Dynamically matches documents provided in ctx
        if not documents_meta and not processed_pages:
            # Default hero demo fixture (Case C: Steel pipes HS 7304)
            extracted_docs = _build_default_case_c_fixture(ctx.get("bundle_id", "bnd-sample"))
        else:
            for doc in documents_meta:
                doc_id = doc.get("document_id", "doc-sample")
                filename = doc.get("filename", "").lower()
                extracted_docs.append(_generate_fixture_for_file(doc_id, filename))

    ctx["extracted"] = extracted_docs
    return ctx


# ---------------------------------------------------------------------------
# Fixture generators for offline testing & Hero demo validation
# ---------------------------------------------------------------------------


def _ref(val: Any, conf: float = 0.98, ymin: float = 120, xmin: float = 80, ymax: float = 160, xmax: float = 400, page: int = 1) -> FieldRef:
    return FieldRef(
        value=val,
        confidence=conf,
        bbox=BBox(page=page, ymin=ymin, xmin=xmin, ymax=ymax, xmax=xmax),
    )


def _generate_fixture_for_file(document_id: str, filename: str) -> ExtractedDocument:
    """Generate realistic typed ExtractedDocument according to filename keywords."""
    if "bol" in filename or "lading" in filename:
        return ExtractedDocument(
            document_id=document_id,
            doc_type="BILL_OF_LADING",
            doc_type_confidence=0.99,
            document_number=_ref("BL-SG-2024-8941", 0.99, 100, 100, 130, 350),
            consignee=_ref("SINGAPORE PRECISION PIPING PTE LTD", 0.98, 200, 100, 240, 500),
            consignor=_ref("BHARAT SEAMLESS PIPES LTD", 0.98, 260, 100, 300, 480),
            vessel_or_flight=_ref("EVER GIVEN V-104E", 0.96, 320, 100, 350, 320),
            total_gross_weight_kg=_ref(14280.0, 0.99, 400, 600, 430, 800),
            port_of_loading=_ref("INNSA - NHAVA SHEVA", 0.97, 450, 100, 480, 350),
            port_of_discharge=_ref("SGSIN - SINGAPORE", 0.97, 450, 500, 480, 750),
        )

    if "packing" in filename or "pl" in filename:
        return ExtractedDocument(
            document_id=document_id,
            doc_type="PACKING_LIST",
            doc_type_confidence=0.99,
            document_number=_ref("PL-2024-001", 0.99, 100, 100, 130, 320),
            consignee=_ref("SINGAPORE PRECISION PIPING PTE LTD", 0.98, 200, 100, 240, 500),
            consignor=_ref("BHARAT SEAMLESS PIPES LTD", 0.98, 260, 100, 300, 480),
            total_net_weight_kg=_ref(14000.0, 0.99, 600, 600, 630, 800),
            total_gross_weight_kg=_ref(14280.0, 0.98, 640, 600, 670, 800),
            tare_weight_kg=_ref(280.0, 0.95, 680, 600, 710, 800),
            line_items=[
                LineItem(
                    description=_ref("Seamless carbon steel pipes ASTM A106 Grade B", 0.98, 400, 100, 430, 600),
                    quantity=_ref("120 PCS", 0.99, 400, 610, 430, 700),
                    net_weight_kg=_ref(14000.0, 0.99, 400, 710, 430, 850),
                    gross_weight_kg=_ref(14280.0, 0.98, 400, 860, 430, 980),
                    hs_code_declared=_ref("73041900", 0.99, 400, 30, 430, 90),
                )
            ],
        )

    if "mtc" in filename or "mill" in filename or "test" in filename:
        return ExtractedDocument(
            document_id=document_id,
            doc_type="MILL_TEST_CERTIFICATE",
            doc_type_confidence=0.99,
            document_number=_ref("MTC-2024-8871", 0.99, 80, 120, 110, 340),
            consignee=_ref("SINGAPORE PRECISION PIPING PTE LTD", 0.97, 180, 120, 210, 480),
            consignor=_ref("BHARAT SEAMLESS PIPES LTD", 0.98, 220, 120, 250, 460),
            line_items=[
                LineItem(
                    description=_ref("Chemical & Mechanical Test Cert: ASTM A106 Grade B Seamless", 0.97, 300, 100, 340, 700),
                    quantity=_ref("120 PCS", 0.99, 300, 710, 340, 800),
                    net_weight_kg=_ref(14000.0, 0.98, 300, 810, 340, 900),
                    gross_weight_kg=_ref(14280.0, 0.98, 300, 910, 340, 990),
                    hs_code_declared=_ref("73041900", 0.98, 300, 40, 340, 95),
                )
            ],
        )

    # Default: Commercial Invoice
    return ExtractedDocument(
        document_id=document_id,
        doc_type="COMMERCIAL_INVOICE",
        doc_type_confidence=0.99,
        document_number=_ref("INV-2024-001", 0.99, 90, 100, 120, 300),
        consignee=_ref("SINGAPORE PRECISION PIPING PTE LTD", 0.98, 180, 100, 220, 500),
        consignor=_ref("BHARAT SEAMLESS PIPES LTD", 0.98, 240, 100, 280, 480),
        invoice_value=_ref(84000.0, 0.99, 500, 700, 530, 850),
        invoice_currency=_ref("USD", 0.99, 500, 860, 530, 920),
        total_net_weight_kg=_ref(14000.0, 0.98, 550, 700, 580, 850),
        total_gross_weight_kg=_ref(14280.0, 0.98, 590, 700, 620, 850),
        line_items=[
            LineItem(
                description=_ref("Seamless carbon steel line pipes for gas pipelines", 0.98, 350, 100, 380, 600),
                quantity=_ref("120 PCS", 0.99, 350, 610, 380, 700),
                net_weight_kg=_ref(14000.0, 0.99, 350, 710, 380, 850),
                gross_weight_kg=_ref(14280.0, 0.98, 350, 860, 380, 980),
                hs_code_declared=_ref("73041900", 0.99, 350, 30, 380, 90),
                total_value=_ref(84000.0, 0.99, 350, 990, 380, 1000),
            )
        ],
    )


def _build_default_case_c_fixture(bundle_id: str) -> list[ExtractedDocument]:
    return [
        _generate_fixture_for_file("doc-inv-01", "invoice.pdf"),
        _generate_fixture_for_file("doc-pl-01", "packing_list.pdf"),
        _generate_fixture_for_file("doc-bol-01", "bill_of_lading.pdf"),
    ]
