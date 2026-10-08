"""Confidence routing service.

Implements the 3-tier routing table from v4.0 §3 (Epic 5, US 5.3):

  Confidence     Deterministic Result   Action
  ≥ 0.95         PASS                   AUTO_ACCEPT
  ≥ 0.95         FAIL                   AUTO_FLAG
  0.65–0.94      any                    INTERACTIVE_REVIEW
  < 0.65         any                    MANUAL_ENTRY (→ SPECIALIST_REVIEW_REQUIRED)
"""

from __future__ import annotations

from app.domain.schemas import ExtractedDocument, FieldRef

MIN_FIELD_CONF: float = 0.65
HIGH_CONF: float = 0.95


def _iter_field_refs(doc: ExtractedDocument):  # type: ignore[no-untyped-def]
    """Yield all FieldRef objects in a document (header fields + line items)."""
    for name in doc.model_fields:
        val = getattr(doc, name, None)
        if isinstance(val, FieldRef):
            yield val
        elif isinstance(val, list):
            for item in val:
                if hasattr(item, "model_fields"):
                    for sub_name in item.model_fields:
                        sub_val = getattr(item, sub_name, None)
                        if isinstance(sub_val, FieldRef):
                            yield sub_val


async def route(ctx: dict) -> dict:
    """Apply confidence routing and set ctx["confidence"] and optionally ctx["force_status"].

    Reads:  ctx["extracted"]   (list[ExtractedDocument])
            ctx["math_status"] (str)
    Writes: ctx["confidence"]  (dict with min_field_confidence and action)
            ctx["force_status"] (optional — set when action requires SPECIALIST_REVIEW)
    """
    extracted: list[ExtractedDocument] = ctx.get("extracted", [])
    all_refs = [ref for doc in extracted for ref in _iter_field_refs(doc)]
    min_conf = min((ref.confidence for ref in all_refs), default=1.0)

    math_status = ctx.get("math_status", "COMPLIANT_FOR_SUBMISSION")
    math_pass = math_status == "COMPLIANT_FOR_SUBMISSION"

    if min_conf >= HIGH_CONF and math_pass:
        action = "AUTO_ACCEPT"
    elif min_conf >= HIGH_CONF and not math_pass:
        action = "AUTO_FLAG"
    elif MIN_FIELD_CONF <= min_conf < HIGH_CONF:
        action = "INTERACTIVE_REVIEW"
    else:
        action = "MANUAL_ENTRY"

    ctx["confidence"] = {
        "min_field_confidence": min_conf,
        "action": action,
    }

    # Low confidence forces SPECIALIST_REVIEW regardless of math result
    if action in ("INTERACTIVE_REVIEW", "MANUAL_ENTRY"):
        ctx["force_status"] = "SPECIALIST_REVIEW_REQUIRED"

    return ctx
