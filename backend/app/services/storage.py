"""GCS storage service.

Handles upload/download of raw PDFs and processed artifacts.
GCS layout:
  bundles/{bundle_id}/
    raw/{document_id}/original.pdf
    raw/{document_id}/meta.json
    processed/{document_id}/page-NNNN.png
    processed/{document_id}/transform.json
    derived/{document_id}/extraction.json

Design rules:
  - Never overwrite: each upload gets a content-addressed document_id.
  - Re-uploading the same bytes is a no-op (same sha256 → same ID).
  - Uploading different bytes under the same logical document creates a
    new document_id and a new AuditEvent.

Phase 1 implementation: Uncomment the GCS client and remove stubs.
"""

import hashlib
import json
from datetime import datetime, timezone


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document_id_from_sha256(sha: str) -> str:
    """Use the first 32 hex chars of the sha256 as the document_id."""
    return sha[:32]


async def upload_raw(
    bundle_id: str,
    data: bytes,
    mime: str = "application/pdf",
    filename: str = "original.pdf",
) -> dict:
    """Upload a raw PDF to GCS and return storage metadata.

    Returns:
        dict with keys: document_id, gcs_uri, sha256, bytes, mime, uploaded_at

    Phase 1: Uncomment GCS client code below.
    Skeleton: Returns metadata without actual GCS upload.
    """
    sha = _compute_sha256(data)
    document_id = _document_id_from_sha256(sha)
    uploaded_at = datetime.now(timezone.utc).isoformat()

    # ---- Phase 1: uncomment ----
    # from google.cloud import storage as gcs_lib
    # from app.core.config import settings
    # client = gcs_lib.Client(project=settings.project_id)
    # bucket = client.bucket(settings.raw_bucket)
    # blob_path = f"bundles/{bundle_id}/raw/{document_id}/original.pdf"
    # blob = bucket.blob(blob_path)
    # blob.metadata = {"sha256": sha, "bundle_id": bundle_id, "document_id": document_id}
    # blob.upload_from_string(data, content_type=mime)
    # meta_blob = bucket.blob(f"bundles/{bundle_id}/raw/{document_id}/meta.json")
    # meta_blob.upload_from_string(json.dumps(meta), content_type="application/json")
    # ----------------------------

    gcs_uri = f"gs://cargoclear-raw-pdfs/bundles/{bundle_id}/raw/{document_id}/original.pdf"
    meta = {
        "document_id": document_id,
        "gcs_uri": gcs_uri,
        "sha256": sha,
        "bytes": len(data),
        "mime": mime,
        "filename": filename,
        "uploaded_at": uploaded_at,
    }
    return meta


async def download_raw(bundle_id: str, document_id: str) -> bytes:
    """Download a raw PDF from GCS.

    Phase 1: Uncomment GCS client code below.
    Skeleton: Raises NotImplementedError.
    """
    # ---- Phase 1: uncomment ----
    # from google.cloud import storage as gcs_lib
    # from app.core.config import settings
    # client = gcs_lib.Client(project=settings.project_id)
    # bucket = client.bucket(settings.raw_bucket)
    # blob_path = f"bundles/{bundle_id}/raw/{document_id}/original.pdf"
    # return bucket.blob(blob_path).download_as_bytes()
    # ----------------------------
    raise NotImplementedError("Storage service not yet connected. Implement in Phase 1.")


async def upload_transform_meta(
    bundle_id: str,
    document_id: str,
    transform_meta: list[dict],
) -> str:
    """Persist the preprocessing transform metadata to GCS.

    The frontend uses this to map processed-page bounding boxes back to
    the original PDF page for display.

    Phase 1: Implement.
    Skeleton: No-op.
    """
    # TODO(Phase 1): upload transform_meta as JSON to GCS
    path = f"bundles/{bundle_id}/processed/{document_id}/transform.json"
    return f"gs://cargoclear-raw-pdfs/{path}"


async def upload_extraction(
    bundle_id: str,
    document_id: str,
    extraction: dict,
) -> str:
    """Persist the Gemini extraction JSON to GCS for auditing.

    Phase 1: Implement.
    Skeleton: No-op.
    """
    # TODO(Phase 1): upload extraction JSON to GCS
    path = f"bundles/{bundle_id}/derived/{document_id}/extraction.json"
    return f"gs://cargoclear-raw-pdfs/{path}"
