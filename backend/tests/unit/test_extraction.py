"""Unit tests for the Multimodal Gemini Extraction Agent."""

import pytest
from app.agents.extraction import run_extraction_agent
from app.domain.schemas import ExtractedDocument


@pytest.mark.asyncio
async def test_extraction_default_fixture():
    ctx = {
        "bundle_id": "bnd-hero-case-c",
        "documents": [
            {"document_id": "doc-inv-001", "filename": "Commercial_Invoice.pdf"},
            {"document_id": "doc-bol-001", "filename": "Bill_of_Lading_ocean.pdf"},
            {"document_id": "doc-pl-001", "filename": "Packing_List.pdf"},
        ],
    }
    result_ctx = await run_extraction_agent(ctx)

    assert "extracted" in result_ctx
    docs = result_ctx["extracted"]
    assert len(docs) == 3

    # Check that documents are strongly typed ExtractedDocument instances
    for doc in docs:
        assert isinstance(doc, ExtractedDocument)
        assert doc.doc_type in ["COMMERCIAL_INVOICE", "PACKING_LIST", "BILL_OF_LADING"]
        assert doc.doc_type_confidence > 0.9


@pytest.mark.asyncio
async def test_extraction_with_custom_files():
    ctx = {
        "bundle_id": "bnd-002",
        "documents": [
            {"document_id": "doc-mtc-01", "filename": "MTC_pipe_cert.pdf"},
            {"document_id": "doc-bol-01", "filename": "Bill_of_Lading_ocean.pdf"},
        ],
    }
    result_ctx = await run_extraction_agent(ctx)
    docs = result_ctx["extracted"]
    assert len(docs) == 2

    mtc_doc = next(d for d in docs if d.document_id == "doc-mtc-01")
    assert mtc_doc.doc_type == "MILL_TEST_CERTIFICATE"
    assert mtc_doc.line_items[0].hs_code_declared.value == "73041900"
    assert mtc_doc.line_items[0].net_weight_kg.value == 14000.0
    assert mtc_doc.line_items[0].net_weight_kg.bbox is not None
