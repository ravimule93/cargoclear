"""Document registration shared by the upload route and the Case C demo route.

Registering a document is three steps that must stay in lock-step:
  1. store the raw bytes (GCS or the local demo cache),
  2. persist the EvidenceDocument record,
  3. append a DOCUMENT_UPLOADED event to the audit chain.
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

    await firestore.create_evidence_document(bundle_id, doc_data)

    await audit.record({
        "bundle_id": bundle_id,
        "iteration": iteration,
        "audit_event_type": "DOCUMENT_UPLOADED",
        "audit_payload": {
            "document_id": meta["document_id"],
            "filename": filename,
            "sha256": meta["sha256"],
            "bytes": meta["bytes"],
        },
        "actor": actor,
    })

    return doc_data
