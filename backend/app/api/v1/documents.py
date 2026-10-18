"""Documents router — PDF upload, file retrieval, and metadata registration."""

import asyncio
import weakref
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Path, Query, UploadFile
from fastapi.responses import Response

from app.core.config import settings
from app.domain.schemas import DocumentDeletedResponse, DocumentResponse, TransformMetadataResponse
from app.gateway.authorization import require_authorized_bundle
from app.gateway.errors import NotFoundError, PayloadTooLargeError, ValidationError
from app.repo import firestore
from app.services import document_identity, orchestrator, relevance, storage
from app.services.documents import register_document, remove_document
from app.services.upload_checks import check_pdf, download_headers, shared_pdf_async

router = APIRouter(tags=["documents"], dependencies=[Depends(require_authorized_bundle)])

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


# One lock per (bundle, document) around [is it new? -> ask the relevance gate -> register], so that two uploads of the same new bytes
# ask the model once: the second finds the document registered. Taken BEFORE the bundle lock (nothing takes them the other way round),
# so the model call never holds up the bundle's other uploads and deletions.
_UPLOAD_LOCKS: "weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock]" = weakref.WeakValueDictionary()


def _upload_lock(bundle_id: str, document_id: str) -> asyncio.Lock:
    lock = _UPLOAD_LOCKS.get((bundle_id, document_id))
    if lock is None:
        lock = _UPLOAD_LOCKS[(bundle_id, document_id)] = asyncio.Lock()
    return lock


def _check_room(bundle: dict[str, Any], document_id: str) -> None:
    """422 when ``document_id`` is a new document and the bundle already holds MAX_DOCUMENTS_PER_BUNDLE. Identical bytes are the same
    document (content-addressed id): re-uploading them replaces the record, as it always has, and is not a new document."""
    known = {d.get("document_id") for d in bundle.get("documents", [])}
    if document_id not in known and len(known) >= settings.max_documents_per_bundle:
        raise ValidationError(
            f"A bundle can hold at most {settings.max_documents_per_bundle} documents.",
            detail={"max_documents": settings.max_documents_per_bundle},
        )


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
    declared_type: Annotated[
        str | None,
        Form(
            description="Optional: what the file is, one of " + ", ".join(document_identity.DECLARABLE_TYPES) + ". When the model reads "
            "another type, the assessment says so (T-001); the file name is never used to guess one."
        ),
    ] = None,
) -> DocumentResponse:
    """Accepts a PDF, checks size and content, stores it (GCS or local cache) and registers it in Firestore."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    declared = document_identity.parse_declared_type(declared_type)  # cheap: refused before the file is read

    content_type = file.content_type or "application/pdf"
    if content_type not in _ALLOWED_MIME and not (file.filename and file.filename.lower().endswith(".pdf")):
        raise ValidationError(
            f"Only PDF files are accepted. Received: {content_type}",
            detail={"content_type": content_type, "filename": file.filename},
        )

    data = await _read_limited(file)
    if len(data) == 0:
        raise ValidationError("Uploaded file is empty (0 bytes).")

    new_id = storage.document_id_from_sha256(storage.compute_sha256(data))

    # One copy of the file on disk for every poppler tool below (header, readability, page count, page sizes, scripts, attachments: poppler's
    # pdfinfo and pdfdetach are subprocesses, so off the event loop; then the text and the page render of the relevance gate).
    async with shared_pdf_async(data):
        await asyncio.to_thread(check_pdf, data, settings.max_pdf_pages, settings.max_page_megapixels)

        async with _upload_lock(bundle_id, new_id):
            bundle = await firestore.get_bundle(bundle_id)  # fresh: another upload of these bytes may have finished while we waited
            if bundle is None:
                raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})
            _check_room(bundle, new_id)  # before the model is asked anything: a file that cannot be added is not worth a request

            # Is the first page a document the assessment reads? Free from the text layer, else one small vision request (services/relevance.py).
            # Not asked again for bytes the bundle already holds: that file passed when it came in.
            existing = next((d for d in bundle.get("documents", []) if d.get("document_id") == new_id), None)
            gate_usage = (existing or {}).get("gate_usage")  # the same bytes again: what its first check cost stays on the record
            if existing is None:
                asked = await relevance.check_document(data)
                gate_usage = asked.usage if asked is not None and asked.usage["requests"] else None

            async with _bundle_lock(bundle_id):
                bundle = await firestore.get_bundle(bundle_id)  # fresh: another upload may have finished while we waited
                if bundle is None:
                    raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})
                _check_room(bundle, new_id)

                doc_data = await register_document(
                    bundle_id,
                    data=data,
                    filename=file.filename or "document.pdf",
                    iteration=bundle.get("current_iteration", 0),
                    gate_usage=gate_usage,
                    declared_type=declared,
                )

    return DocumentResponse(**doc_data)


@router.delete(
    "/bundles/{bundle_id}/documents/{document_id}",
    response_model=DocumentDeletedResponse,
    summary="Remove a document from a bundle, with the files and kept model answers stored for it",
)
async def delete_document(
    bundle_id: str = Path(..., description="Target bundle ID"),
    document_id: str = Path(..., description="Document ID"),
) -> DocumentDeletedResponse:
    """Takes a document out of a bundle, so that one bad document no longer stops the bundle from being assessed.

    Removes the stored PDF, its processed pages and transform metadata, the model's kept answers for it and its record, and appends a
    DOCUMENT_DELETED event to the audit chain (file name, SHA-256, size, what its upload check cost). It does not rewrite history:
    earlier assessments and their extraction records, the audit chain and the usage records stay as they were. The newest assessment is
    not recomputed (``in_latest_assessment`` says whether it used the document); Reassess makes a verdict without it.

    409 while a run is queued or running for the bundle. 404 for an unknown bundle or a document that is not in it. Takes the same lock
    as an upload, so the two cannot interleave. Repeating a call that failed half way finishes it.
    """
    async with _bundle_lock(bundle_id):
        bundle = await firestore.get_bundle(bundle_id)
        if bundle is None:
            raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})
        doc = next((d for d in bundle.get("documents", []) if d.get("document_id") == document_id), None)
        if doc is None:
            raise NotFoundError(
                f"Document '{document_id}' not found in bundle '{bundle_id}'.",
                detail={"bundle_id": bundle_id, "document_id": document_id},
            )
        async with orchestrator.idle_bundle(bundle_id, "delete a document"):
            removed = await remove_document(bundle_id, doc, iteration=bundle.get("current_iteration", 0))

    latest = await firestore.latest_iteration(bundle_id)
    return DocumentDeletedResponse(
        bundle_id=bundle_id,
        document_id=document_id,
        filename=doc.get("filename") or "document.pdf",
        files_removed=removed["files_removed"],
        cached_answers_removed=removed["cached_answers_removed"],
        latest_iteration=int(latest["iteration"]) if latest else None,
        in_latest_assessment=bool(latest and document_id in (latest.get("documents") or [])),
    )


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
    "/bundles/{bundle_id}/documents/{document_id}/pages/{page}",
    summary="The page image the model was shown (after orientation, deskew and the image mode)",
    response_class=Response,
)
async def get_processed_page(
    bundle_id: str = Path(..., description="Target bundle ID"),
    document_id: str = Path(..., description="Document ID"),
    page: int = Path(..., ge=1, le=10_000, description="1-indexed source page"),
    iteration: int | None = Query(default=None, ge=1, description="Assessment number; the latest when omitted"),
) -> Response:
    """The persisted PNG of one page exactly as the extraction of that assessment saw it: the answer to "what did it see?".
    A recompute shows the model nothing of its own, so it serves the pages of the assessment it copied. 404 when the document is
    not in the bundle or the page was not persisted (PERSIST_PROCESSED_PAGES off, or a document read as a raw PDF)."""
    doc_meta = await firestore.get_bundle_document(bundle_id, document_id)
    if doc_meta is None:
        raise NotFoundError(
            f"Document '{document_id}' not found in bundle '{bundle_id}'.",
            detail={"bundle_id": bundle_id, "document_id": document_id},
        )
    if iteration is None:
        latest = await firestore.latest_iteration(bundle_id)
        iteration = int(latest["iteration"]) if latest else None
    pages_iteration: int | None = None  # None: pages kept before they were kept per assessment (one set per document)
    if iteration is not None:
        record = await firestore.get_extraction_record(bundle_id, iteration)
        if record is None:
            raise NotFoundError(
                f"Assessment {iteration} of bundle '{bundle_id}' has no stored extraction.",
                detail={"bundle_id": bundle_id, "iteration": iteration},
            )
        pages_iteration = record.get("pages_iteration")
    image = await storage.download_processed_page(bundle_id, document_id, page, pages_iteration)
    return Response(content=image, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


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
