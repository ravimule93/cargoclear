"""Unit tests for cryptographic audit chain verification and tamper detection."""

import pytest
from app.services.audit import record, verify_audit_chain, list_audit_events


@pytest.mark.asyncio
async def test_audit_chain_sequential_linking():
    bundle_id = "test-bnd-audit-01"

    # Event 1
    ctx1 = {
        "bundle_id": bundle_id,
        "iteration": 0,
        "audit_event_type": "BUNDLE_CREATED",
        "audit_payload": {"destination": "SG"},
        "actor": "user",
    }
    await record(ctx1)

    # Event 2
    ctx2 = {
        "bundle_id": bundle_id,
        "iteration": 0,
        "audit_event_type": "DOCUMENT_UPLOADED",
        "audit_payload": {"doc_id": "doc-01", "bytes": 1024},
        "actor": "user",
    }
    await record(ctx2)

    # Event 3
    ctx3 = {
        "bundle_id": bundle_id,
        "iteration": 1,
        "audit_event_type": "ASSESSMENT_COMPLETED",
        "audit_payload": {"status": "MISSING_EVIDENCE"},
        "actor": "system",
    }
    await record(ctx3)

    events = await list_audit_events(bundle_id)
    assert len(events) == 3

    # Genesis check
    assert events[0]["seq"] == 1
    assert events[0]["prev_hash"] == "GENESIS"

    # Chaining check
    assert events[1]["seq"] == 2
    assert events[1]["prev_hash"] == events[0]["hash"]

    assert events[2]["seq"] == 3
    assert events[2]["prev_hash"] == events[1]["hash"]

    # Verify intact chain
    is_valid, err = verify_audit_chain(events)
    assert is_valid is True
    assert err is None


@pytest.mark.asyncio
async def test_audit_chain_detects_tampered_payload():
    bundle_id = "test-bnd-tamper-02"

    await record({
        "bundle_id": bundle_id,
        "audit_event_type": "EVENT_A",
        "audit_payload": {"amount": 1000},
    })
    await record({
        "bundle_id": bundle_id,
        "audit_event_type": "EVENT_B",
        "audit_payload": {"amount": 2000},
    })

    events = await list_audit_events(bundle_id)

    # Tamper with event A payload
    events[0]["payload"]["amount"] = 99999

    is_valid, err = verify_audit_chain(events)
    assert is_valid is False
    assert "Tampered event payload" in err
