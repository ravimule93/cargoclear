"""Document registration shared by the upload route and the Case C demo route.

Registering a document is three steps that must stay in lock-step:
  1. store the raw bytes (GCS or the local demo cache),
  2. persist the EvidenceDocument record,
  3. append a DOCUMENT_UPLOADED event to the audit chain.

Removing one (``remove_document``) undoes them in an order that a repeat can finish: the files, then the model's kept answers, then
the DOCUMENT_DELETED event, then the record.
"""

from __future__ import annotations

from typing import Any

from app.repo import firestore
from app.services import audit, storage
from app.services.upload_checks import sanitize_filename


async def register_document(
    bundle_id: str,
    *,
    data: bytes,
    filename: str,
    iteration: int = 0,
    actor: str = "user",
    gate_usage: dict[str, int] | None = None,
    declared_type: str | None = None,
) -> dict[str, Any]:
    """Store ``data`` under ``bundle_id`` and register it; returns the EvidenceDocument record.

    ``filename`` is sanitised here, the one place both the upload route and the demo route go through, so the stored,
    audited and classified name is always the clean one.
    """
    filename = sanitize_filename(filename)
    meta = await storage.upload_raw(
        bundle_id=bundle_id,
        data=data,
        mime="application/pdf",
        filename=filename,
    )

    doc_data = {
        "document_id": meta["document_id"],
        "bundle_id": bundle_id,
        "filename": filename,
        "doc_type": "UNKNOWN",
        "gcs_uri": meta["gcs_uri"],
        "sha256": meta["sha256"],
        "bytes": meta["bytes"],
        "uploaded_at": meta["uploaded_at"],
    }
    if gate_usage:  # what the relevance check at upload cost (services/token_usage.py); shown by GET /bundles/{id}/usage
        doc_data["gate_usage"] = gate_usage
    if declared_type:  # what the uploader said the file is; compared with what the model read (services/document_identity.py)
        doc_data["declared_type"] = declared_type

    await firestore.create_evidence_document(bundle_id, doc_data)

    uploaded: dict[str, Any] = {
        "document_id": meta["document_id"],
        "filename": filename,
        "sha256": meta["sha256"],
        "bytes": meta["bytes"],
    }
    if declared_type:
        uploaded["declared_type"] = declared_type
    await audit.record({
        "bundle_id": bundle_id,
        "iteration": iteration,
        "audit_event_type": "DOCUMENT_UPLOADED",
        "audit_payload": uploaded,
        "actor": actor,
    })

    return doc_data


async def remove_document(bundle_id: str, doc: dict[str, Any], *, iteration: int = 0, actor: str = "user") -> dict[str, Any]:
    """Remove ``doc`` (its EvidenceDocument record) from the bundle with everything stored for it: the raw file, the processed pages
    and transform metadata, and the model's answers kept for it (the extraction cache).

    What stays, on purpose: the audit chain (append-only; it gets a DOCUMENT_DELETED event with the file's name, SHA-256 and size, and
    what its upload check cost), the stored assessments and their extraction records (they describe what was read at the time), and the
    usage records. The caller holds the bundle still (no run live, the upload lock taken).

    Each step can be repeated, and the order is the one a retry can finish: files first (a missing file is fine), the record last. If a
    step fails the record is still there and the same call can be made again; the only trace of a half-done delete is that the audit
    chain may then hold two DOCUMENT_DELETED events for it.
    """
    document_id = doc["document_id"]
    files_removed = await storage.delete_document_files(bundle_id, document_id)
    answers_removed = await firestore.delete_cached_answers(bundle_id, document_id)

    payload: dict[str, Any] = {
        "document_id": document_id,
        "filename": doc.get("filename"),
        "sha256": doc.get("sha256"),
        "bytes": doc.get("bytes"),
        "files_removed": files_removed,
        "cached_answers_removed": answers_removed,
    }
    if doc.get("gate_usage"):  # the cost of its upload check leaves with the record: keep it where GET /bundles/{id}/usage reads it
        payload["gate_usage"] = doc["gate_usage"]
    await audit.record({
        "bundle_id": bundle_id,
        "iteration": iteration,
        "audit_event_type": "DOCUMENT_DELETED",
        "audit_payload": payload,
        "actor": actor,
    })

    gate_tokens = int((doc.get("gate_usage") or {}).get("total_tokens") or 0)  # kept on the bundle: GET /usage still counts it
    await firestore.delete_evidence_document(bundle_id, document_id, gate_tokens)
    return {"files_removed": files_removed, "cached_answers_removed": answers_removed}
