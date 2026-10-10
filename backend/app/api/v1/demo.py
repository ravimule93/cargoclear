"""Demo router — one-click Case C sample bundle (demo mode only).

POST /demo/case-c      Creates a fresh bundle preloaded with the Invoice, Bill of Lading and
                       Packing List sample PDFs. The Mill Test Certificate is deliberately
                       withheld so the UI can walk the Missing Evidence -> Compliant journey.
GET  /demo/case-c/mtc  Serves the sample MTC so the UI can offer a one-click upload.

Both endpoints 404 unless APP_MODE=demo. The sample PDFs are generated, deterministic
files (scripts/generate_case_c_pdfs.py) drawn from the same fixture values the offline
extractor returns, so the printed text matches what the pipeline "reads".
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from fastapi import APIRouter
from fastapi.responses import Response

from app.api.v1.bundles import create_bundle
from app.core.config import settings
from app.domain.schemas import BundleResponse, CreateBundleRequest
from app.gateway.errors import CargoClearError, NotFoundError
from app.repo import firestore
from app.services.documents import register_document
from app.services.upload_checks import download_headers

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["demo"])

CASE_C_REFERENCE = "CASE-C-7304-DEMO"
CASE_C_DESTINATION = "SG"
CASE_C_PRELOADED = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf")
CASE_C_MTC = "mtc_pipe_test_cert.pdf"

# backend/app/api/v1/demo.py -> repo root is four levels above this file's directory
_DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "case_c"


def _require_demo_mode() -> None:
    if settings.app_mode != "demo":
        raise NotFoundError("Demo endpoints are only available when APP_MODE=demo.")


def _fixture_dir() -> Path:
    override = os.environ.get("CASE_C_FIXTURE_DIR")
    return Path(override) if override else _DEFAULT_FIXTURE_DIR


def _read_fixture(filename: str) -> bytes:
    path = _fixture_dir() / filename
    if not path.is_file():
        # The path is the operator's business: it goes to the log, never into the response
        logger.error(
            "case_c_fixture_missing",
            path=str(path),
            filename=filename,
            hint="Run scripts/generate_case_c_pdfs.py, or set CASE_C_FIXTURE_DIR to the directory that holds the PDFs.",
        )
        raise CargoClearError(
            "The Case C sample documents are not installed on this server.",
            detail={"filename": filename},
        )
    return path.read_bytes()


@router.post(
    "/demo/case-c",
    response_model=BundleResponse,
    status_code=201,
    summary="Create a Case C demo bundle preloaded with three sample PDFs",
)
async def create_case_c_demo() -> BundleResponse:
    _require_demo_mode()

    # Read every file up-front so a missing fixture fails before a half-built bundle exists.
    payloads = {name: _read_fixture(name) for name in CASE_C_PRELOADED}

    bundle = await create_bundle(
        CreateBundleRequest(reference=CASE_C_REFERENCE, destination_country=CASE_C_DESTINATION)
    )
    for name, data in payloads.items():
        await register_document(bundle.id, data=data, filename=name, iteration=0)

    stored = await firestore.get_bundle(bundle.id)
    if stored is None:  # pragma: no cover - the bundle was created a few lines above
        raise NotFoundError(f"Bundle '{bundle.id}' not found.", detail={"bundle_id": bundle.id})

    return BundleResponse(
        id=stored["id"],
        reference=stored.get("reference"),
        destination_country=stored.get("destination_country", CASE_C_DESTINATION),
        status=stored.get("status", "PENDING"),
        current_iteration=stored.get("current_iteration", 0),
        documents=stored.get("documents", []),
        created_at=stored.get("created_at", ""),
    )


@router.get(
    "/demo/case-c/mtc",
    summary="Sample Mill Test Certificate for the Case C demo",
    response_class=Response,
)
async def get_case_c_mtc() -> Response:
    _require_demo_mode()
    return Response(
        content=_read_fixture(CASE_C_MTC),
        media_type="application/pdf",
        headers=download_headers(CASE_C_MTC),
    )
