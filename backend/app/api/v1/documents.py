"""Documents router — PDF upload, file retrieval, and metadata registration."""

import asyncio
import weakref

from fastapi import APIRouter, File, Path, UploadFile
from fastapi.responses import Response

from app.core.config import settings
from app.domain.schemas import DocumentResponse, TransformMetadataResponse
from app.gateway.errors import NotFoundError, PayloadTooLargeError, ValidationError
from app.repo import firestore
from app.services import storage
from app.services.documents import register_document
from app.services.upload_checks import check_pdf, download_headers

router = APIRouter(tags=["documents"])

_ALLOWED_MIME = {"application/pdf", "application/octet-stream"}
_CHUNK_BYTES = 1024 * 1024  # the upload is read one MiB at a time

# One lock per bundle around [count the documents -> register one], so that simultaneous uploads cannot overshoot
# MAX_DOCUMENTS_PER_BUNDLE (this process is the only instance). Entries disappear when nobody holds or awaits the lock.
_BUNDLE_LOCKS: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()


def _bundle_lock(bundle_id: str) -> asyncio.Lock:
    lock = _BUNDLE_LOCKS.get(bundle_id)
    if lock is None:
        lock = _BUNDLE_LOCKS[bundle_id] = asyncio.Lock()
    return lock


async def _read_limited(file: UploadFile) -> bytes:
    """Read the upload in 1 MiB chunks; stop with 413 as soon as MAX_UPLOAD_MB is crossed.

    At most the limit plus the one chunk that crossed it is ever held, however large the upload claims to be.
    """
    limit = settings.max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise PayloadTooLargeError(
                f"The file is larger than {settings.max_upload_mb:g} MB.", detail={"max_bytes": limit}
            )
        chunks.append(chunk)
    return b"".join(chunks)


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
    """Accepts a PDF, checks size and content, stores it (GCS or local cache) and registers it in Firestore."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    content_type = file.content_type or "application/pdf"
    if content_type not in _ALLOWED_MIME and not (file.filename and file.filename.lower().endswith(".pdf")):
        raise ValidationError(
            f"Only PDF files are accepted. Received: {content_type}",
            detail={"content_type": content_type, "filename": file.filename},
        )

    data = await _read_limited(file)
    if len(data) == 0:
        raise ValidationError("Uploaded file is empty (0 bytes).")

    # header, encryption and page count (poppler's pdfinfo is a subprocess): off the event loop
    await asyncio.to_thread(check_pdf, data, settings.gemini_max_pages)

    async with _bundle_lock(bundle_id):
        bundle = await firestore.get_bundle(bundle_id)  # fresh: another upload may have finished while we waited
        if bundle is None:
            raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

        # Identical bytes are the same document (content-addressed id): re-uploading them replaces the record, as it
        # always has, and is not a new document.
        new_id = storage.document_id_from_sha256(storage.compute_sha256(data))
        known = {d.get("document_id") for d in bundle.get("documents", [])}
        if new_id not in known and len(known) >= settings.max_documents_per_bundle:
            raise ValidationError(
                f"A bundle can hold at most {settings.max_documents_per_bundle} documents.",
                detail={"max_documents": settings.max_documents_per_bundle},
            )

        doc_data = await register_document(
            bundle_id,
            data=data,
            filename=file.filename or "document.pdf",
            iteration=bundle.get("current_iteration", 0),
        )

    return DocumentResponse(**doc_data)


@router.get(
    "/bundles/{bundle_id}/documents/{document_id}/file",
    summary="Download or stream the raw PDF file scoped by bundle",
    response_class=Response,
)
async def get_document_file(
    bundle_id: str = Path(..., description="Target bundle ID"),
    document_id: str = Path(..., description="Document ID"),
) -> Response:
    """Stream raw PDF bytes back to the client or frontend canvas viewer."""
    doc_meta = await firestore.get_bundle_document(bundle_id, document_id)
    if doc_meta is None:
        raise NotFoundError(
            f"Document '{document_id}' not found in bundle '{bundle_id}'.",
            detail={"bundle_id": bundle_id, "document_id": document_id},
        )

    pdf_bytes = await storage.download_raw(bundle_id, document_id)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=download_headers(doc_meta.get("filename") or "document.pdf"),
    )


@router.get(
    "/bundles/{bundle_id}/documents/{document_id}/transform-metadata",
    response_model=TransformMetadataResponse,
    summary="Get persisted preprocessing transforms for one evidence document",
)
async def get_document_transform_metadata(
    bundle_id: str = Path(..., description="Target bundle ID"),
    document_id: str = Path(..., description="Document ID"),
) -> TransformMetadataResponse:
    """Return private transform metadata only after verifying the document belongs to the bundle."""
    doc_meta = await firestore.get_bundle_document(bundle_id, document_id)
    if doc_meta is None:
        raise NotFoundError(
            f"Document '{document_id}' not found in bundle '{bundle_id}'.",
            detail={"bundle_id": bundle_id, "document_id": document_id},
        )
    if not doc_meta.get("transform_meta_uri"):
        raise NotFoundError(
            f"Transform metadata for document '{document_id}' not found.",
            detail={"bundle_id": bundle_id, "document_id": document_id},
        )

    return TransformMetadataResponse(
        document_id=document_id,
        transform_meta=await storage.download_transform_meta(bundle_id, document_id),
    )
