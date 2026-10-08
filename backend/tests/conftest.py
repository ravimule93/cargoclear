"""pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def sample_extracted_document():
    """A valid ExtractedDocument for use in unit tests."""
    from app.domain.schemas import (
        ExtractedDocument, FieldRef, LineItem, BBox
    )

    def ref(v, c=0.97):
        return FieldRef(
            value=v, confidence=c,
            bbox=BBox(page=1, ymin=100, xmin=50, ymax=150, xmax=500)
        )

    return ExtractedDocument(
        document_id="test-doc-001",
        doc_type="PACKING_LIST",
        doc_type_confidence=0.99,
        consignee=ref("SINGAPORE TRADING PTE LTD"),
        consignor=ref("MUMBAI STEEL WORKS LTD"),
        total_net_weight_kg=ref(14000.0),
        total_gross_weight_kg=ref(14280.0),
        tare_weight_kg=ref(280.0),
        line_items=[
            LineItem(
                description=ref("Steel pipes for industrial use"),
                quantity=ref("100 PCS"),
                net_weight_kg=ref(14000.0),
                gross_weight_kg=ref(14280.0),
                hs_code_declared=ref("73041900"),
            )
        ],
    )


@pytest.fixture
def sample_bol_document():
    """A sample Bill of Lading document."""
    from app.domain.schemas import ExtractedDocument, FieldRef, BBox

    def ref(v, c=0.97):
        return FieldRef(
            value=v, confidence=c,
            bbox=BBox(page=1, ymin=100, xmin=50, ymax=150, xmax=500)
        )

    return ExtractedDocument(
        document_id="test-bol-001",
        doc_type="BILL_OF_LADING",
        doc_type_confidence=0.99,
        consignee=ref("SINGAPORE TRADING PTE LTD"),
        consignor=ref("MUMBAI STEEL WORKS LTD"),
        total_gross_weight_kg=ref(14280.0),
    )
