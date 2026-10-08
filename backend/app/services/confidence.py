"""Confidence routing service.

Implements the 4-tier routing table from Specification §3 (Epic 5, US 5.3):

  Extraction Confidence   Deterministic Result     Action               Resulting Status
  >= 0.95                 PASS                     AUTO_ACCEPT          COMPLIANT_FOR_SUBMISSION
  >= 0.95                 FAIL                     AUTO_FLAG            MATERIAL_CONTRADICTION
  0.65 – 0.94             any                      INTERACTIVE_REVIEW   SPECIALIST_REVIEW_REQUIRED
  < 0.65                  any                      MANUAL_ENTRY         SPECIALIST_REVIEW_REQUIRED

Extracts confidence scores recursively from every visible scalar field across
document headers and commodity line items.
"""

from __future__ import annotations

from typing import Any, Generator

from app.domain.schemas import ExtractedDocument, FieldRef

MIN_FIELD_CONF_THRESHOLD: float = 0.65
HIGH_CONF_THRESHOLD: float = 0.95


def _extract_all_field_refs(doc: ExtractedDocument) -> Generator[FieldRef, None, None]:
    """Recursively collect every FieldRef present in a document."""
    # Top-level fields
    for field_name in doc.model_fields:
        val = getattr(doc, field_name, None)
        if isinstance(val, FieldRef):
            yield val
        elif isinstance(val, list):
            for item in val:
                if hasattr(item, "model_fields"):
                    for sub_field in item.model_fields:
                        sub_val = getattr(item, sub_field, None)
                        if isinstance(sub_val, FieldRef):
                            yield sub_val


async def route(ctx: dict[str, Any]) -> dict[str, Any]:
    """Execute confidence-based routing for the extracted document bundle.

    Reads:
      - ctx["extracted"] (list[ExtractedDocument])
      - ctx.get("math_status", "COMPLIANT_FOR_SUBMISSION")

    Writes:
      - ctx["confidence"] (dict with min_field_confidence and action)
      - ctx["force_status"] (optional status override when confidence requires review)
    """
    extracted_docs: list[ExtractedDocument] = ctx.get("extracted", [])
    math_status: str = ctx.get("math_status", "COMPLIANT_FOR_SUBMISSION")

    # Gather confidence scores across all fields
    all_refs: list[FieldRef] = []
    for doc in extracted_docs:
        all_refs.extend(_extract_all_field_refs(doc))

    # Calculate minimum confidence across bundle
    if all_refs:
        min_conf = min(ref.confidence for ref in all_refs)
    else:
        min_conf = 1.0

    min_conf = round(float(min_conf), 4)
    math_passed = math_status == "COMPLIANT_FOR_SUBMISSION"

    # Evaluate 4-tier routing table
    if min_conf >= HIGH_CONF_THRESHOLD:
        action = "AUTO_ACCEPT" if math_passed else "AUTO_FLAG"
    elif MIN_FIELD_CONF_THRESHOLD <= min_conf < HIGH_CONF_THRESHOLD:
        action = "INTERACTIVE_REVIEW"
    else:
        action = "MANUAL_ENTRY"

    ctx["confidence"] = {
        "min_field_confidence": min_conf,
        "action": action,
    }

    # Moderate or low confidence overrides compliance to force specialist review
    if action in ("INTERACTIVE_REVIEW", "MANUAL_ENTRY"):
        ctx["force_status"] = "SPECIALIST_REVIEW_REQUIRED"

    return ctx
