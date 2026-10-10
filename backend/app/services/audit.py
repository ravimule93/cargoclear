"""Audit service — tamper-evident hash-chained append-only log.

Every meaningful state change creates an AuditEvent with:
  - A SHA-256 cryptographic hash chaining to the immediate previous event.
  - An immutable Firestore document (security rules deny update/delete).

Cryptographic hash chain construction:
  hash_n = SHA-256(canonical_json({prev_hash, seq, ts, bundle_id, iteration, event_type, actor, payload}))

Hashing one canonical JSON object (instead of concatenating strings) keeps field boundaries unambiguous:
bundle "a1" + iteration 2 can no longer collide with bundle "a" + iteration 12.

Provides a chain verification utility `verify_audit_chain` to detect any
retroactive tampering or sequence truncation.

Appending is safe against a second writer: on Firestore an event is created (never overwritten) at document id
``f"{seq:010d}"``. If another process took that sequence number first, ``create`` raises AlreadyExists, the tail is
read again and the append is retried (at most ``_MAX_APPEND_ATTEMPTS`` times). The stored ``event_id`` field keeps
its original format.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from google.api_core.exceptions import AlreadyExists

from app.core.config import settings
from app.core.mode import no_credentials_message, use_live_gcp
from app.gateway.errors import UpstreamError

logger = structlog.get_logger(__name__)

# In-memory storage fallback for audit events when running offline
_IN_MEMORY_AUDIT: dict[str, list[dict[str, Any]]] = {}

# Locks per bundle for serialized appends
_BUNDLE_LOCKS: dict[str, asyncio.Lock] = {}

_firestore_client = None

# How many times one append may lose a race for its sequence number before giving up
_MAX_APPEND_ATTEMPTS = 5


def _get_firestore_client():
    """Lazily initialize Firestore client."""
    global _firestore_client
    if _firestore_client is not None:
        return _firestore_client

    if not use_live_gcp():
        if settings.app_mode == "live":
            raise UpstreamError(no_credentials_message())
        return None

    try:
        from google.cloud.firestore_v1.async_client import AsyncClient

        _firestore_client = AsyncClient(
            project=settings.project_id,
            database=settings.firestore_database,
        )
        return _firestore_client
    except Exception as exc:
        if settings.app_mode == "live":
            raise UpstreamError(f"Audit Firestore client init failed in live mode: {type(exc).__name__}") from exc
        logger.warning("firestore_client_init_failed", error=str(exc))
        return None


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization with sorted keys and no whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(
    prev_hash: str,
    seq: int,
    ts: str,
    bundle_id: str,
    iteration: int,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
) -> str:
    """Compute the SHA-256 digest of an event, chained to the previous event via ``prev_hash``.

    The digest covers the canonical JSON of *all* hashed fields as one object, so no two distinct
    events can share a serialisation regardless of where one field ends and the next begins.
    """
    framed = {
        "prev_hash": prev_hash,
        "seq": seq,
        "ts": ts,
        "bundle_id": bundle_id,
        "iteration": iteration,
        "event_type": event_type,
        "actor": actor,
        "payload": payload,
    }
    return hashlib.sha256(canonical_json(framed).encode("utf-8")).hexdigest()


# Backward compatibility aliases
_canonical = canonical_json


def _build_event(
    bundle_id: str, iteration: int, event_type: str, actor: str, payload: dict[str, Any], prev_hash: str, seq: int
) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "event_id": f"{bundle_id}:{iteration}:{seq}",
        "bundle_id": bundle_id,
        "iteration": iteration,
        "seq": seq,
        "ts": ts,
        "actor": actor,
        "event_type": event_type,
        "payload": payload,
        "prev_hash": prev_hash,
        "hash": compute_hash(prev_hash, seq, ts, bundle_id, iteration, event_type, actor, payload),
    }


async def _read_tail(client: Any, bundle_id: str) -> tuple[str, int]:
    """(prev_hash, next seq) from the newest stored event; ("GENESIS", 1) for an empty chain."""
    try:
        col = client.collection("bundles").document(bundle_id).collection("audit")
        query = col.order_by("seq", direction="DESCENDING").limit(1)
        results = [doc.to_dict() async for doc in query.stream()]
        if results:
            return results[0]["hash"], results[0]["seq"] + 1
    except Exception as exc:
        if settings.app_mode == "live":
            raise UpstreamError(f"Audit chain query failed in live mode: {type(exc).__name__}") from exc
        logger.warning("firestore_audit_query_failed", error=str(exc))
    return "GENESIS", 1


async def _append_firestore(
    client: Any, bundle_id: str, iteration: int, event_type: str, actor: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Create the event at ``{seq:010d}``; if another writer took that number, re-read the tail and retry."""
    col = client.collection("bundles").document(bundle_id).collection("audit")
    event_data: dict[str, Any] = {}
    for attempt in range(1, _MAX_APPEND_ATTEMPTS + 1):
        prev_hash, seq = await _read_tail(client, bundle_id)
        event_data = _build_event(bundle_id, iteration, event_type, actor, payload, prev_hash, seq)
        try:
            await col.document(f"{seq:010d}").create(event_data)
        except AlreadyExists:
            logger.warning("audit_append_conflict", bundle_id=bundle_id, seq=seq, attempt=attempt)
            continue
        except Exception as exc:
            if settings.app_mode == "live":
                raise UpstreamError(f"Audit event persist failed in live mode: {type(exc).__name__}") from exc
            logger.error("audit_event_persist_failed", error=str(exc))
            return event_data
        logger.info("audit_event_persisted_firestore", bundle_id=bundle_id, seq=seq, hash=event_data["hash"][:12])
        return event_data

    if settings.app_mode == "live":
        raise UpstreamError(
            f"Audit append for bundle {bundle_id} conflicted {_MAX_APPEND_ATTEMPTS} times: "
            "another writer is appending to the same audit chain"
        )
    logger.error("audit_append_conflicts_exhausted", bundle_id=bundle_id, attempts=_MAX_APPEND_ATTEMPTS)
    return event_data


async def record(ctx: dict[str, Any]) -> dict[str, Any]:
    """Append a tamper-evident AuditEvent to the hash chain.

    Serialized per bundle in this process with an asyncio.Lock; across processes the Firestore ``create`` at a
    deterministic document id makes a lost race an error that is retried, not a silent overwrite.
    """
    bundle_id: str = ctx["bundle_id"]
    iteration: int = ctx.get("iteration", 0)
    event_type: str = ctx.get("audit_event_type", "SYSTEM_EVENT")
    payload: dict[str, Any] = ctx.get("audit_payload", {})
    actor: str = ctx.get("actor", "system")

    if bundle_id not in _BUNDLE_LOCKS:
        _BUNDLE_LOCKS[bundle_id] = asyncio.Lock()

    async with _BUNDLE_LOCKS[bundle_id]:
        client = _get_firestore_client()

        if client is not None:
            event_data = await _append_firestore(client, bundle_id, iteration, event_type, actor, payload)
        else:
            events = _IN_MEMORY_AUDIT.get(bundle_id, [])
            prev_hash, seq = (events[-1]["hash"], events[-1]["seq"] + 1) if events else ("GENESIS", 1)
            event_data = _build_event(bundle_id, iteration, event_type, actor, payload, prev_hash, seq)
            _IN_MEMORY_AUDIT.setdefault(bundle_id, []).append(event_data)
            logger.info("audit_event_persisted_in_memory", bundle_id=bundle_id, seq=seq, hash=event_data["hash"][:12])

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
        except Exception as exc:
            if settings.app_mode == "live":
                raise UpstreamError(f"List audit events failed in live mode: {type(exc).__name__}") from exc

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
        if evt["seq"] != idx:
            return False, f"Sequence gap at index {idx}: expected seq={idx}, got seq={evt['seq']}"

        if evt["prev_hash"] != expected_prev_hash:
            return False, f"Broken link at seq={evt['seq']}: expected prev_hash={expected_prev_hash[:12]}, got {evt['prev_hash'][:12]}"

        recalculated = compute_hash(
            evt["prev_hash"],
            evt["seq"],
            evt["ts"],
            evt.get("bundle_id", ""),
            evt.get("iteration", 0),
            evt.get("event_type", ""),
            evt.get("actor", ""),
            evt["payload"],
        )
        if recalculated != evt["hash"]:
            return False, f"Tampered event payload at seq={evt['seq']}: hash mismatch"

        expected_prev_hash = evt["hash"]

    return True, None
