"""Unit tests for the audit hash-chain service."""

import pytest
from app.services.audit import compute_hash, canonical_json


def test_canonical_is_deterministic():
    payload = {"z": 3, "a": 1, "m": 2}
    assert canonical_json(payload) == canonical_json(payload)


def test_canonical_sorts_keys():
    p1 = {"z": 1, "a": 2}
    p2 = {"a": 2, "z": 1}
    assert canonical_json(p1) == canonical_json(p2)


def test_hash_changes_with_seq():
    h1 = compute_hash("GENESIS", 1, "2024-01-01T00:00:00", {"x": 1})
    h2 = compute_hash("GENESIS", 2, "2024-01-01T00:00:00", {"x": 1})
    assert h1 != h2


def test_hash_changes_with_payload():
    h1 = compute_hash("GENESIS", 1, "2024-01-01T00:00:00", {"x": 1})
    h2 = compute_hash("GENESIS", 1, "2024-01-01T00:00:00", {"x": 2})
    assert h1 != h2


def test_hash_is_sha256_hex():
    h = compute_hash("GENESIS", 1, "2024-01-01T00:00:00", {})
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)



@pytest.mark.asyncio
async def test_record_returns_valid_event():
    from app.services.audit import record
    ctx = {
        "bundle_id": "bundle-test-001",
        "audit_event_type": "DOCUMENT_UPLOADED",
        "audit_payload": {"document_id": "doc-001", "sha256": "abc"},
        "iteration": 0,
        "actor": "user",
    }
    result = await record(ctx)
    event = result["audit_event"]
    assert event["event_type"] == "DOCUMENT_UPLOADED"
    assert len(event["hash"]) == 64
    assert event["prev_hash"] == "GENESIS"
    assert event["seq"] == 1
