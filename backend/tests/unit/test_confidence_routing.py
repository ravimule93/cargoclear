"""Unit tests for the 4-tier confidence routing table."""

import pytest
from app.domain.schemas import ExtractedDocument, FieldRef, LineItem, BBox
from app.services.confidence import route


def _make_doc(conf: float) -> ExtractedDocument:
    ref = FieldRef(value="Val", confidence=conf, bbox=BBox(page=1, ymin=0, xmin=0, ymax=10, xmax=10))
    return ExtractedDocument(
        document_id="doc-test",
        doc_type="COMMERCIAL_INVOICE",
        doc_type_confidence=conf,
        document_number=ref,
        line_items=[
            LineItem(
                description=ref,
                quantity=ref,
                net_weight_kg=ref,
                gross_weight_kg=ref,
                hs_code_declared=ref,
            )
        ],
    )


@pytest.mark.asyncio
async def test_confidence_auto_accept():
    # Confidence >= 0.95 and math PASS -> AUTO_ACCEPT
    ctx = {
        "extracted": [_make_doc(0.98)],
        "math_status": "COMPLIANT_FOR_SUBMISSION",
    }
    res = await route(ctx)
    assert res["confidence"]["action"] == "AUTO_ACCEPT"
    assert "force_status" not in res


@pytest.mark.asyncio
async def test_confidence_auto_flag():
    # Confidence >= 0.95 and math FAIL -> AUTO_FLAG
    ctx = {
        "extracted": [_make_doc(0.96)],
        "math_status": "MATERIAL_CONTRADICTION",
    }
    res = await route(ctx)
    assert res["confidence"]["action"] == "AUTO_FLAG"
    assert "force_status" not in res


@pytest.mark.asyncio
async def test_confidence_interactive_review():
    # 0.65 <= Confidence < 0.95 -> INTERACTIVE_REVIEW
    ctx = {
        "extracted": [_make_doc(0.82)],
        "math_status": "COMPLIANT_FOR_SUBMISSION",
    }
    res = await route(ctx)
    assert res["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert res["force_status"] == "SPECIALIST_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_confidence_manual_entry():
    # Confidence < 0.65 -> MANUAL_ENTRY
    ctx = {
        "extracted": [_make_doc(0.55)],
        "math_status": "COMPLIANT_FOR_SUBMISSION",
    }
    res = await route(ctx)
    assert res["confidence"]["action"] == "MANUAL_ENTRY"
    assert res["force_status"] == "SPECIALIST_REVIEW_REQUIRED"
