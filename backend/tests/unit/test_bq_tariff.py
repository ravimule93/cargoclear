"""Unit tests for BigQuery tariff tool, vector distance calculation, and Grounding Agent."""

import pytest
from app.agents.tools.bq_tariff import lookup_tariff, AMBIGUITY_THRESHOLD
from app.agents.grounding import run_grounding_agent
from app.domain.schemas import ExtractedDocument, FieldRef, LineItem, BBox


def _ref(v):
    return FieldRef(value=v, confidence=0.98, bbox=BBox(page=1, ymin=0, xmin=0, ymax=100, xmax=100))


def test_lookup_tariff_returns_candidates():
    hits = lookup_tariff("Seamless steel pipes for gas pipelines", destination_country="SG")
    assert len(hits) >= 1
    top = hits[0]
    assert "hs_code" in top
    assert "description" in top
    assert "distance" in top
    assert "required_documents" in top
    assert top["distance"] <= AMBIGUITY_THRESHOLD


def test_lookup_tariff_wheat_phytosanitary():
    hits = lookup_tariff("Wheat grains for human consumption", destination_country="SG")
    assert len(hits) >= 1
    top = hits[0]
    assert "PHYTOSANITARY" in top["required_documents"]


@pytest.mark.asyncio
async def test_grounding_agent_detects_missing_mtc():
    doc = ExtractedDocument(
        document_id="doc-inv-pipe",
        doc_type="COMMERCIAL_INVOICE",
        doc_type_confidence=0.99,
        line_items=[
            LineItem(
                description=_ref("Line pipe seamless steel for oil pipelines"),
                quantity=_ref("100 PCS"),
                net_weight_kg=_ref(14000.0),
                gross_weight_kg=_ref(14280.0),
                hs_code_declared=_ref("73041900"),
            )
        ],
    )

    ctx = {
        "extracted": [doc],
        "destination_country": "SG",
    }

    result_ctx = await run_grounding_agent(ctx)

    assert "grounding" in result_ctx
    assert "missing_evidence" in result_ctx
    assert len(result_ctx["missing_evidence"]) >= 1
    missing = result_ctx["missing_evidence"][0]
    assert missing["id"] == "ME-MILL_TEST_CERTIFICATE"
    assert "Mill Test Certificate" in missing["document_label"]


@pytest.mark.asyncio
async def test_grounding_agent_with_mtc_present_is_satisfied():
    inv_doc = ExtractedDocument(
        document_id="doc-inv-pipe",
        doc_type="COMMERCIAL_INVOICE",
        doc_type_confidence=0.99,
        line_items=[
            LineItem(
                description=_ref("Line pipe seamless steel for oil pipelines"),
                quantity=_ref("100 PCS"),
                net_weight_kg=_ref(14000.0),
                gross_weight_kg=_ref(14280.0),
                hs_code_declared=_ref("73041900"),
            )
        ],
    )
    mtc_doc = ExtractedDocument(
        document_id="doc-mtc-pipe",
        doc_type="MILL_TEST_CERTIFICATE",
        doc_type_confidence=0.99,
    )

    ctx = {
        "extracted": [inv_doc, mtc_doc],
        "destination_country": "SG",
    }

    result_ctx = await run_grounding_agent(ctx)
    # Since MILL_TEST_CERTIFICATE is present in extracted, missing_evidence must be empty
    assert len(result_ctx["missing_evidence"]) == 0
