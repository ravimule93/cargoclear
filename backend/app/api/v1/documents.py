"""Documents router — PDF upload and file retrieval."""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Path, UploadFile
from fastapi.responses import Response

from app.domain.schemas import DocumentResponse
from app.gateway.errors import NotFoundError, ValidationError

router = APIRouter(tags=["documents"])

_ALLOWED_MIME = {"application/pdf"}
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB hard limit (well above e-SANCHIT 1 MB per-page limit)


@router.post(
    "/bundles/{bundle_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
    summary="Upload a PDF document to a bundle",
)
async def upload_document(
    bundle_id: str = Path(..., description="Target bundle ID"),
    file: UploadFile = File(..., description="PDF file to upload"),
) -> DocumentResponse:
    """Upload a raw PDF to GCS and register it in Firestore.

    Accepts: application/pdf only.
    Max size: 50 MB (the preprocessing service splits files >1 MB / >13 pages
    per e-SANCHIT constraints).

    Phase 1: Stores to GCS + Firestore.
    Skeleton: Validates, returns a stub response.
    """
    # Validate MIME
    if file.content_type not in _ALLOWED_MIME:
        raise ValidationError(
            f"Only PDF files are accepted. Got: {file.content_type}",
            detail={"content_type": file.content_type},
        )

    data = await file.read()

    if len(data) > _MAX_BYTES:
        raise ValidationError(
            f"File exceeds 50 MB limit. Got: {len(data)} bytes.",
            detail={"bytes": len(data), "max_bytes": _MAX_BYTES},
        )

    # TODO(Phase 1): services.storage.upload_raw(bundle_id, document_id, data, mime)
    # TODO(Phase 1): repo.firestore.create_evidence_document(...)
    # TODO(Phase 1): services.audit.record("DOCUMENT_UPLOADED", ...)

    document_id = hashlib.sha256(data).hexdigest()[:16]
    now = datetime.now(timezone.utc).isoformat()

    return DocumentResponse(
        document_id=document_id,
        bundle_id=bundle_id,
        filename=file.filename or "unknown.pdf",
        doc_type="UNKNOWN",
        gcs_uri=f"gs://cargoclear-raw-pdfs/bundles/{bundle_id}/raw/{document_id}/original.pdf",
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        uploaded_at=now,
    )


@router.get(
    "/documents/{document_id}/file",
    summary="Retrieve the raw PDF file for a document",
    response_class=Response,
)
async def get_document_file(
    document_id: str = Path(..., description="Document ID"),
) -> Response:
    """Stream the raw PDF bytes from GCS.

    Used by the frontend PDF viewer (pdfjs-dist).
    Phase 1: Fetches from GCS.
    Skeleton: Returns 404.
    """
    # TODO(Phase 1): services.storage.download_raw(document_id)
    raise NotFoundError(
        f"Document '{document_id}' not found.",
        detail={"document_id": document_id},
    )
