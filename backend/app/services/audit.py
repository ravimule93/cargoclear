"""Audit service — tamper-evident hash-chained Firestore append-only log.

Every meaningful state change (document upload, pipeline start/complete,
assessment written, error) creates an AuditEvent with:
  - A SHA-256 hash that chains to the previous event.
  - An immutable Firestore document (security rules deny update/delete).

Hash chain construction:
  hash_n = SHA-256(prev_hash + str(seq) + ts + canonical_json(payload))

Firestore security rule (set in infra/ — NOT enforced here):
  match /bundles/{id}/audit/{eventId} {
    allow create: if request.auth != null;
    allow update, delete: if false;  // tamper-evident
  }

Phase 1: Uncomment Firestore client code.
Skeleton: Logs locally, returns a synthetic audit event.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def _canonical(payload: dict) -> str:
    """Deterministic JSON serialisation for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, seq: int, ts: str, payload: dict) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode())
    h.update(str(seq).encode())
    h.update(ts.encode())
    h.update(_canonical(payload).encode())
    return h.hexdigest()


async def record(ctx: dict) -> dict:
    """Append an AuditEvent to the Firestore hash chain.

    Reads:  ctx["bundle_id"]
            ctx["audit_event_type"]  (e.g. "DOCUMENT_UPLOADED")
            ctx["audit_payload"]     (dict with event-specific data)
            ctx.get("iteration", 0)
            ctx.get("actor", "system")
    Writes: ctx["audit_event"]       (the written event dict)
    """
    bundle_id = ctx["bundle_id"]
    iteration = ctx.get("iteration", 0)
    event_type = ctx["audit_event_type"]
    payload = ctx.get("audit_payload", {})
    actor = ctx.get("actor", "system")

    # ---- Phase 1: Fetch last event from Firestore ----
    # from app.repo.firestore import db
    # col = db.collection("bundles").document(bundle_id).collection("audit")
    # last_docs = col.order_by("seq", direction=firestore.Query.DESCENDING).limit(1).get()
    # prev_hash = last_docs[0].to_dict()["hash"] if last_docs else "GENESIS"
    # seq = (last_docs[0].to_dict()["seq"] + 1) if last_docs else 1
    # ---------------------------------------------------

    # Skeleton: use synthetic values
    prev_hash = "GENESIS"
    seq = 1

    ts = datetime.now(timezone.utc).isoformat()
    event_id = f"{bundle_id}:{iteration}:{seq}"
    event_hash = _compute_hash(prev_hash, seq, ts, payload)

    event = {
        "event_id": event_id,
        "bundle_id": bundle_id,
        "iteration": iteration,
        "seq": seq,
        "ts": ts,
        "actor": actor,
        "event_type": event_type,
        "payload": payload,
        "prev_hash": prev_hash,
        "hash": event_hash,
    }

    # ---- Phase 1: write to Firestore ----
    # col.document(event_id).set(event)
    # -------------------------------------

    ctx["audit_event"] = event
    return ctx
