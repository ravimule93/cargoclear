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
  - Never overwrite: each upload gets a content-addressed document_id derived from its SHA-256.
  - Re-uploading the same bytes is a no-op (same sha256 -> same ID).
  - Uploading different bytes under the same logical document creates a
    new document_id and a new AuditEvent.
  - Supports local disk cache fallback when in demo mode.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from app.core.config import settings
from app.core.mode import no_credentials_message, use_live_gcp
from app.gateway.errors import NotFoundError, UpstreamError

logger = structlog.get_logger(__name__)

_gcs_client = None


def _get_local_storage_dir() -> Path:
    """Return local storage cache directory Path."""
    path_str = getattr(settings, "local_storage_path", "./.storage_cache")
    p = Path(path_str)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_gcs_client():
    """Lazily initialize GCS client."""
    global _gcs_client
    if _gcs_client is not None:
        return _gcs_client

    if not use_live_gcp():
        if settings.app_mode == "live":
            raise UpstreamError(no_credentials_message())
        logger.info("gcs_local_mode", reason="Running in demo mode without GCP credentials")
        return None

    try:
        from google.cloud import storage as gcs_lib

        _gcs_client = gcs_lib.Client(project=settings.project_id)
        return _gcs_client
    except Exception as exc:
        if settings.app_mode == "live":
            raise UpstreamError(f"GCS client init failed in live mode: {type(exc).__name__}") from exc
        logger.warning("gcs_client_init_failed", error=str(exc), fallback="local_disk")
        return None


def compute_sha256(data: bytes) -> str:
    """Compute standard SHA-256 hex digest of file payload."""
    return hashlib.sha256(data).hexdigest()


def document_id_from_sha256(sha: str) -> str:
    """Use the first 16 hex chars of the SHA-256 digest as the unique document_id."""
    return f"doc-{sha[:16]}"


async def upload_raw(
    bundle_id: str,
    data: bytes,
    mime: str = "application/pdf",
    filename: str = "original.pdf",
) -> dict[str, Any]:
    """Upload a raw PDF to GCS and return storage metadata.

    Returns:
        dict with keys: document_id, gcs_uri, sha256, bytes, mime, filename, uploaded_at
    """
    sha = compute_sha256(data)
    document_id = document_id_from_sha256(sha)
    uploaded_at = datetime.now(timezone.utc).isoformat()
    gcs_uri = f"gs://{settings.raw_bucket}/bundles/{bundle_id}/raw/{document_id}/original.pdf"

    meta = {
        "document_id": document_id,
        "bundle_id": bundle_id,
        "gcs_uri": gcs_uri,
        "sha256": sha,
        "bytes": len(data),
        "mime": mime,
        "filename": filename,
        "uploaded_at": uploaded_at,
    }

    client = _get_gcs_client()

    if client is not None:
        try:
            bucket = client.bucket(settings.raw_bucket)
            blob_path = f"bundles/{bundle_id}/raw/{document_id}/original.pdf"
            blob = bucket.blob(blob_path)
            blob.metadata = {
                "sha256": sha,
                "bundle_id": bundle_id,
                "document_id": document_id,
                "filename": filename,
            }
            blob.upload_from_string(data, content_type=mime)

            meta_blob = bucket.blob(f"bundles/{bundle_id}/raw/{document_id}/meta.json")
            meta_blob.upload_from_string(json.dumps(meta), content_type="application/json")
            logger.info("gcs_raw_uploaded", gcs_uri=gcs_uri, size_bytes=len(data))
        except Exception as exc:
            logger.error("gcs_upload_failed", error=str(exc))
            raise UpstreamError(f"Failed to upload PDF to Cloud Storage: {type(exc).__name__}") from exc
    else:
        # Local cache path
        doc_dir = _get_local_storage_dir() / "bundles" / bundle_id / "raw" / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "original.pdf").write_bytes(data)
        (doc_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        logger.info("local_raw_cached", path=str(doc_dir / "original.pdf"), size_bytes=len(data))

    return meta


async def download_raw(bundle_id: str, document_id: str) -> bytes:
    """Download raw PDF bytes from GCS or local cache."""
    client = _get_gcs_client()

    if client is not None:
        try:
            bucket = client.bucket(settings.raw_bucket)
            blob_path = f"bundles/{bundle_id}/raw/{document_id}/original.pdf"
            blob = bucket.blob(blob_path)
            if not blob.exists():
                raise NotFoundError(f"Document '{document_id}' not found in storage bucket.")
            return blob.download_as_bytes()
        except NotFoundError:
            raise
        except Exception as exc:
            logger.error("gcs_download_failed", error=str(exc))
            raise UpstreamError(f"Failed to retrieve PDF from Cloud Storage: {type(exc).__name__}") from exc

    # Local cache fallback
    local_path = _get_local_storage_dir() / "bundles" / bundle_id / "raw" / document_id / "original.pdf"
    if not local_path.exists():
        raise NotFoundError(f"Document '{document_id}' not found in local cache.")

    return local_path.read_bytes()


async def upload_transform_meta(
    bundle_id: str,
    document_id: str,
    transform_meta: list[dict[str, Any]],
) -> str:
    """Persist preprocessing transform metadata for UI bounding-box remapping."""
    path = f"bundles/{bundle_id}/processed/{document_id}/transform.json"
    data_str = json.dumps(transform_meta)
    client = _get_gcs_client()

    if client is not None:
        try:
            bucket = client.bucket(settings.raw_bucket)
            blob = bucket.blob(path)
            blob.upload_from_string(data_str, content_type="application/json")
        except Exception as exc:
            raise UpstreamError(f"Failed to persist transform metadata: {type(exc).__name__}") from exc
    else:
        local_file = _get_local_storage_dir() / path
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_text(data_str, encoding="utf-8")

    return f"gs://{settings.raw_bucket}/{path}"


async def upload_processed_artifacts(
    bundle_id: str, document_id: str, artifacts: list[dict[str, Any]]
) -> None:
    """Persist private sequential e-SANCHIT-oriented processed PDFs for one raw evidence document."""
    if not artifacts:
        return
    client = _get_gcs_client()
    try:
        if client is not None:
            bucket = client.bucket(settings.raw_bucket)
            for artifact in artifacts:
                artifact_id = artifact["artifact_id"]
                blob = bucket.blob(f"bundles/{bundle_id}/processed/{document_id}/{artifact_id}.pdf")
                blob.upload_from_string(artifact["payload"], content_type="application/pdf")
        else:
            directory = _get_local_storage_dir() / "bundles" / bundle_id / "processed" / document_id
            directory.mkdir(parents=True, exist_ok=True)
            for artifact in artifacts:
                (directory / f"{artifact['artifact_id']}.pdf").write_bytes(artifact["payload"])
    except Exception as exc:
        raise UpstreamError(f"Failed to persist processed artifacts: {type(exc).__name__}") from exc


async def download_transform_meta(bundle_id: str, document_id: str) -> list[dict[str, Any]]:
    """Read one document's persisted preprocessing transforms from private storage."""
    path = f"bundles/{bundle_id}/processed/{document_id}/transform.json"
    client = _get_gcs_client()

    try:
        if client is not None:
            bucket = client.bucket(settings.raw_bucket)
            blob = bucket.blob(path)
            if not blob.exists():
                raise NotFoundError(f"Transform metadata for document '{document_id}' not found.")
            raw = blob.download_as_bytes()
        else:
            local_file = _get_local_storage_dir() / path
            if not local_file.is_file():
                raise NotFoundError(f"Transform metadata for document '{document_id}' not found.")
            raw = local_file.read_bytes()
        data = json.loads(raw)
    except NotFoundError:
        raise
    except Exception as exc:
        raise UpstreamError(f"Failed to retrieve transform metadata: {type(exc).__name__}") from exc

    if not isinstance(data, list) or not all(isinstance(entry, dict) for entry in data):
        raise UpstreamError("Transform metadata is invalid.")
    return data
