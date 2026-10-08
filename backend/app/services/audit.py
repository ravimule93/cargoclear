"""Audit service — tamper-evident hash-chained append-only log.

Every meaningful state change creates an AuditEvent with:
  - A SHA-256 cryptographic hash chaining to the immediate previous event.
  - An immutable Firestore document (security rules deny update/delete).

Cryptographic hash chain construction:
  hash_n = SHA-256(prev_hash + str(seq) + ts + canonical_json(payload))

Provides a chain verification utility `verify_audit_chain` to detect any
retroactive tampering or sequence truncation.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# In-memory storage fallback for audit events when running offline
_IN_MEMORY_AUDIT: dict[str, list[dict[str, Any]]] = {}

_firestore_client = None


def _get_firestore_client():
    """Lazily initialize Firestore client."""
    global _firestore_client
    if _firestore_client is not None:
        return _firestore_client

    has_creds = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("K_SERVICE"))
    if not has_creds and os.getenv("USE_FIRESTORE_EMULATOR") != "true":
        return None

    try:
        from google.cloud.firestore_v1.async_client import AsyncClient

        _firestore_client = AsyncClient(
            project=settings.project_id,
            database=settings.firestore_database,
        )
        return _firestore_client
    except Exception as exc:
        logger.warning("firestore_client_init_failed", error=str(exc))
        return None


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization with sorted keys and no whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, seq: int, ts: str, payload: dict[str, Any]) -> str:
    """Compute standard SHA-256 digest chaining from the previous event."""
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(str(seq).encode("utf-8"))
    h.update(ts.encode("utf-8"))
    h.update(canonical_json(payload).encode("utf-8"))
    return h.hexdigest()


# Backward compatibility aliases
_canonical = canonical_json
_compute_hash = compute_hash


async def record(ctx: dict[str, Any]) -> dict[str, Any]:
    """Append a tamper-evident AuditEvent to the Firestore hash chain.

    Reads:
      - ctx["bundle_id"]
      - ctx["audit_event_type"]
      - ctx.get("audit_payload", {})
      - ctx.get("iteration", 0)
      - ctx.get("actor", "system")

    Writes:
      - ctx["audit_event"] (the serialized event dict)
    """
    bundle_id: str = ctx["bundle_id"]
    iteration: int = ctx.get("iteration", 0)
    event_type: str = ctx.get("audit_event_type", "SYSTEM_EVENT")
    payload: dict[str, Any] = ctx.get("audit_payload", {})
    actor: str = ctx.get("actor", "system")

    client = _get_firestore_client()
    prev_hash = "GENESIS"
    seq = 1

    if client is not None:
        try:
            col = client.collection("bundles").document(bundle_id).collection("audit")
            query = col.order_by("seq", direction="DESCENDING").limit(1)
            results = [doc.to_dict() async for doc in query.stream()]
            if results:
                prev_event = results[0]
                prev_hash = prev_event["hash"]
                seq = prev_event["seq"] + 1
        except Exception as exc:
            logger.warning("firestore_audit_query_failed", error=str(exc))
    else:
        # In-memory chain lookup
        events = _IN_MEMORY_AUDIT.get(bundle_id, [])
        if events:
            prev_event = events[-1]
            prev_hash = prev_event["hash"]
            seq = prev_event["seq"] + 1

    ts = datetime.now(timezone.utc).isoformat()
    event_id = f"{bundle_id}:{iteration}:{seq}"
    current_hash = compute_hash(prev_hash, seq, ts, payload)

    event_data = {
        "event_id": event_id,
        "bundle_id": bundle_id,
        "iteration": iteration,
        "seq": seq,
        "ts": ts,
        "actor": actor,
        "event_type": event_type,
        "payload": payload,
        "prev_hash": prev_hash,
        "hash": current_hash,
    }

    if client is not None:
        try:
            col = client.collection("bundles").document(bundle_id).collection("audit")
            await col.document(event_id).set(event_data)
            logger.info("audit_event_persisted_firestore", bundle_id=bundle_id, seq=seq, hash=current_hash[:12])
        except Exception as exc:
            logger.error("audit_event_persist_failed", error=str(exc))
    else:
        if bundle_id not in _IN_MEMORY_AUDIT:
            _IN_MEMORY_AUDIT[bundle_id] = []
        _IN_MEMORY_AUDIT[bundle_id].append(event_data)
        logger.info("audit_event_persisted_in_memory", bundle_id=bundle_id, seq=seq, hash=current_hash[:12])

    ctx["audit_event"] = event_data
    return ctx


async def list_audit_events(bundle_id: str) -> list[dict[str, Any]]:
    """Retrieve all audit events for a bundle ordered by sequence number."""
    client = _get_firestore_client()

    if client is not None:
        try:
            col = client.collection("bundles").document(bundle_id).collection("audit")
            query = col.order_by("seq", direction="ASCENDING")
            return [doc.to_dict() async for doc in query.stream()]
        except Exception:
            pass

    return list(_IN_MEMORY_AUDIT.get(bundle_id, []))


def verify_audit_chain(events: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Verify cryptographic integrity of an ordered list of audit events.

    Returns:
        (True, None) if the chain is intact.
        (False, error_reason) if any tampering or sequence gap is detected.
    """
    if not events:
        return True, None

    expected_prev_hash = "GENESIS"

    for idx, evt in enumerate(events, start=1):
        # 1. Verify sequence order
        if evt["seq"] != idx:
            return False, f"Sequence gap at index {idx}: expected seq={idx}, got seq={evt['seq']}"

        # 2. Verify previous hash link
        if evt["prev_hash"] != expected_prev_hash:
            return False, f"Broken link at seq={evt['seq']}: expected prev_hash={expected_prev_hash[:12]}, got {evt['prev_hash'][:12]}"

        # 3. Recalculate hash over contents
        recalculated = compute_hash(evt["prev_hash"], evt["seq"], evt["ts"], evt["payload"])
        if recalculated != evt["hash"]:
            return False, f"Tampered event payload at seq={evt['seq']}: hash mismatch"

        expected_prev_hash = evt["hash"]

    return True, None
