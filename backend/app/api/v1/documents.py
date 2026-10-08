"""Documents router — PDF upload, file retrieval, and metadata registration."""

from fastapi import APIRouter, File, Path, UploadFile
from fastapi.responses import Response

from app.domain.schemas import DocumentResponse
from app.gateway.errors import NotFoundError, ValidationError
from app.repo import firestore
from app.services import audit, storage

router = APIRouter(tags=["documents"])

_ALLOWED_MIME = {"application/pdf", "application/octet-stream"}
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB hard limit


@router.post(
    "/bundles/{bundle_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
    summary="Upload a PDF trade document into a bundle",
)
async def upload_document(
    bundle_id: str = Path(..., description="Target bundle ID"),
    file: UploadFile = File(..., description="PDF file to upload"),
) -> DocumentResponse:
    """Accepts PDF document, verifies size/MIME, stores to GCS, and registers in Firestore."""
    # Verify bundle exists
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    # Validate MIME type
    content_type = file.content_type or "application/pdf"
    if content_type not in _ALLOWED_MIME and not (file.filename and file.filename.lower().endswith(".pdf")):
        raise ValidationError(
            f"Only PDF files are accepted. Received: {content_type}",
            detail={"content_type": content_type, "filename": file.filename},
        )

    data = await file.read()
    if len(data) == 0:
        raise ValidationError("Uploaded file is empty (0 bytes).")

    if len(data) > _MAX_BYTES:
        raise ValidationError(
            f"File exceeds 50 MB limit. Got: {len(data)} bytes.",
            detail={"bytes": len(data), "max_bytes": _MAX_BYTES},
        )

    filename = file.filename or "document.pdf"

    # Upload to storage (GCS or local cache)
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
        "doc_type": "UNKNOWN",  # Will be classified by Extraction Agent in Stage 1
        "gcs_uri": meta["gcs_uri"],
        "sha256": meta["sha256"],
        "bytes": meta["bytes"],
        "uploaded_at": meta["uploaded_at"],
    }

    # Register document in Firestore
    await firestore.create_evidence_document(bundle_id, doc_data)

    # Append-only audit record
    await audit.record({
        "bundle_id": bundle_id,
        "iteration": bundle.get("current_iteration", 0),
        "audit_event_type": "DOCUMENT_UPLOADED",
        "audit_payload": {
            "document_id": meta["document_id"],
            "filename": filename,
            "sha256": meta["sha256"],
            "bytes": meta["bytes"],
        },
        "actor": "user",
    })

    return DocumentResponse(
        document_id=meta["document_id"],
        bundle_id=bundle_id,
        filename=filename,
        doc_type="UNKNOWN",
        gcs_uri=meta["gcs_uri"],
        sha256=meta["sha256"],
        bytes=meta["bytes"],
        uploaded_at=meta["uploaded_at"],
    )


@router.get(
    "/documents/{document_id}/file",
    summary="Download or stream the raw PDF file",
    response_class=Response,
)
async def get_document_file(
    document_id: str = Path(..., description="Document ID"),
) -> Response:
    """Stream raw PDF bytes back to the client or frontend canvas viewer."""
    doc_meta = await firestore.get_evidence_document(document_id)
    if doc_meta is None:
        raise NotFoundError(f"Document '{document_id}' not found.", detail={"document_id": document_id})

    bundle_id = doc_meta["bundle_id"]
    pdf_bytes = await storage.download_raw(bundle_id, document_id)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc_meta.get("filename", "document.pdf")}"',
            "Cache-Control": "public, max-age=3600",
        },
    )
