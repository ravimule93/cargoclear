"""Unit tests for the audit hash-chain service."""

import copy

import pytest
from app.services.audit import canonical_json, compute_hash, list_audit_events, record, verify_audit_chain


def test_canonical_is_deterministic():
    payload = {"z": 3, "a": 1, "m": 2}
    assert canonical_json(payload) == canonical_json(payload)


def test_canonical_sorts_keys():
    p1 = {"z": 1, "a": 2}
    p2 = {"a": 2, "z": 1}
    assert canonical_json(p1) == canonical_json(p2)


def test_hash_changes_with_seq():
    h1 = compute_hash("GENESIS", 1, "2024-01-01T00:00:00", "bnd-001", 0, "DOCUMENT_UPLOADED", "user", {"x": 1})
    h2 = compute_hash("GENESIS", 2, "2024-01-01T00:00:00", "bnd-001", 0, "DOCUMENT_UPLOADED", "user", {"x": 1})
    assert h1 != h2


def test_hash_changes_with_payload():
    h1 = compute_hash("GENESIS", 1, "2024-01-01T00:00:00", "bnd-001", 0, "DOCUMENT_UPLOADED", "user", {"x": 1})
    h2 = compute_hash("GENESIS", 1, "2024-01-01T00:00:00", "bnd-001", 0, "DOCUMENT_UPLOADED", "user", {"x": 2})
    assert h1 != h2


def test_hash_is_sha256_hex():
    h = compute_hash("GENESIS", 1, "2024-01-01T00:00:00", "bnd-001", 0, "DOCUMENT_UPLOADED", "user", {})
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


# ---------------------------------------------------------------------------
# Hash coverage: every field of an event must feed the hash
# ---------------------------------------------------------------------------

BASE = {
    "prev_hash": "GENESIS",
    "seq": 1,
    "ts": "2024-01-01T00:00:00+00:00",
    "bundle_id": "bnd-001",
    "iteration": 0,
    "event_type": "DOCUMENT_UPLOADED",
    "actor": "user",
    "payload": {"x": 1},
}

CHANGED = {
    "prev_hash": "a" * 64,
    "seq": 2,
    "ts": "2024-01-01T00:00:01+00:00",
    "bundle_id": "bnd-002",
    "iteration": 1,
    "event_type": "ASSESSMENT_COMPLETED",
    "actor": "system",
    "payload": {"x": 2},
}


def _hash(**overrides):
    return compute_hash(**{**BASE, **overrides})


@pytest.mark.parametrize("field", sorted(BASE))
def test_changing_any_field_changes_the_hash(field):
    assert _hash(**{field: CHANGED[field]}) != _hash(), field


def test_hash_is_deterministic():
    assert _hash() == _hash()


def test_hash_ignores_payload_key_order():
    assert _hash(payload={"a": 1, "b": 2}) == _hash(payload={"b": 2, "a": 1})


def test_hash_field_boundaries_are_unambiguous():
    """Naive concatenation made ("a1", iteration 2) and ("a", iteration 12) hash the same."""
    assert _hash(bundle_id="a1", iteration=2) != _hash(bundle_id="a", iteration=12)
    # same idea across other adjacent string fields
    assert _hash(event_type="AB", actor="C") != _hash(event_type="A", actor="BC")
    assert _hash(prev_hash="x", seq=12) != _hash(prev_hash="x1", seq=2)


def test_hash_is_sha256_of_canonical_json_of_all_fields():
    """Pins the framing: sha256(canonical_json({prev_hash, seq, ts, bundle_id, iteration, event_type, actor, payload}))."""
    import hashlib

    expected = hashlib.sha256(canonical_json(BASE).encode("utf-8")).hexdigest()
    assert _hash() == expected


async def _three_event_chain(bundle_id: str):
    for event_type, actor in (("BUNDLE_CREATED", "user"), ("DOCUMENT_UPLOADED", "user"), ("ANALYSIS_STARTED", "system")):
        await record({
            "bundle_id": bundle_id,
            "iteration": 0,
            "audit_event_type": event_type,
            "audit_payload": {"k": "v"},
            "actor": actor,
        })
    return await list_audit_events(bundle_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("event_type", "ASSESSMENT_COMPLETED"),
        ("actor", "admin"),
        ("payload", {"k": "forged"}),
        ("iteration", 7),
        ("ts", "1999-01-01T00:00:00+00:00"),
        ("bundle_id", "bnd-someone-else"),
    ],
)
async def test_verify_detects_tampering_of_every_hashed_field(field, tampered):
    events = copy.deepcopy(await _three_event_chain("bnd-tamper-matrix"))
    assert verify_audit_chain(events) == (True, None)

    events[0][field] = tampered
    valid, error = verify_audit_chain(events)

    assert valid is False, field
    assert error is not None and "seq=1" in error


@pytest.mark.asyncio
async def test_verify_detects_a_forged_hash_that_breaks_the_next_link():
    events = copy.deepcopy(await _three_event_chain("bnd-forged-link"))
    events[1]["hash"] = "0" * 64
    valid, error = verify_audit_chain(events)
    assert valid is False
    assert "seq=2" in error


@pytest.mark.asyncio
async def test_verify_detects_truncation_of_the_head():
    events = copy.deepcopy(await _three_event_chain("bnd-truncated"))
    valid, error = verify_audit_chain(events[1:])
    assert valid is False
    assert "Sequence gap" in error
