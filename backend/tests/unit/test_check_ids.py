"""Check ids must be unique within an iteration (B6): one D-DUP-<DOCTYPE> per duplicated document type."""

from __future__ import annotations

import pytest

from app.domain.schemas import ExtractedDocument
from app.services import calculation


def _doc(document_id: str, doc_type: str) -> ExtractedDocument:
    return ExtractedDocument(document_id=document_id, doc_type=doc_type, doc_type_confidence=0.99)


@pytest.mark.asyncio
async def test_two_duplicated_types_yield_two_distinct_ids() -> None:
    ctx = {
        "extracted": [
            _doc("inv-1", "COMMERCIAL_INVOICE"),
            _doc("inv-2", "COMMERCIAL_INVOICE"),
            _doc("pl-1", "PACKING_LIST"),
            _doc("pl-2", "PACKING_LIST"),
            _doc("bol-1", "BILL_OF_LADING"),
        ]
    }

    checks = (await calculation.run(ctx))["checks"]
    ids = [c["check_id"] for c in checks]
    dup_ids = [i for i in ids if i.startswith("D-DUP")]

    assert sorted(dup_ids) == ["D-DUP-COMMERCIAL_INVOICE", "D-DUP-PACKING_LIST"]
    assert len(ids) == len(set(ids)), f"duplicate check ids: {ids}"
    by_id = {c["check_id"]: c for c in checks}
    assert "COMMERCIAL_INVOICE" in by_id["D-DUP-COMMERCIAL_INVOICE"]["message"]
    assert "PACKING_LIST" in by_id["D-DUP-PACKING_LIST"]["message"]
    assert all(by_id[i]["severity"] == "WARN" for i in dup_ids)


@pytest.mark.asyncio
async def test_unknown_documents_are_not_flagged_as_duplicates() -> None:
    ctx = {"extracted": [_doc("a", "UNKNOWN"), _doc("b", "UNKNOWN")]}
    checks = (await calculation.run(ctx))["checks"]
    assert [c["check_id"] for c in checks] == []


@pytest.mark.asyncio
async def test_a_single_duplicated_type_gets_its_own_id() -> None:
    ctx = {"extracted": [_doc("x", "MILL_TEST_CERTIFICATE"), _doc("y", "MILL_TEST_CERTIFICATE")]}
    ids = [c["check_id"] for c in (await calculation.run(ctx))["checks"]]
    assert ids == ["D-DUP-MILL_TEST_CERTIFICATE"]
