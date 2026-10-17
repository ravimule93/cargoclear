"""Demo router — one-click sample bundles (demo mode only).

POST /demo/case-c      Case C (India -> Singapore): a fresh bundle preloaded with the Invoice, Bill of Lading and
                       Packing List sample PDFs. The Mill Test Certificate is deliberately withheld so the UI can walk
                       the Missing Evidence -> Compliant journey.
GET  /demo/case-c/mtc  Serves the sample MTC so the UI can offer a one-click upload.
POST /demo/case-d      Case D (an INDIA IMPORT of Chinese-origin seamless tubes): a fresh bundle with ALL FOUR documents.
                       The certificate's chemistry (0.35 % chromium) contradicts the declared non-alloy HS code, so the
                       first analysis is a Material Contradiction, with an anti-dumping warning and a duty estimate.

All endpoints 404 unless APP_MODE=demo. The sample PDFs are generated, deterministic files
(scripts/generate_case_c_pdfs.py) drawn from the same fixture values the offline extractor returns, so the printed text
matches what the pipeline "reads". Every name and number in them is invented.
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.v1.bundles import create_bundle
from app.core.config import settings
from app.domain.auth import UserIdentity
from app.domain.schemas import BundleResponse, CreateBundleRequest
from app.gateway.auth import get_current_user
from app.gateway.errors import CargoClearError, NotFoundError
from app.repo import firestore
from app.services.documents import register_document
from app.services.upload_checks import download_headers

logger = structlog.get_logger(__name__)

CASE_C_REFERENCE = "CASE-C-7304-DEMO"
CASE_C_DESTINATION = "SG"
CASE_C_PRELOADED = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf")
CASE_C_MTC = "mtc_pipe_test_cert.pdf"

CASE_D_REFERENCE = "CASE-D-7304-IN-DEMO"
CASE_D_DESTINATION = "IN"
CASE_D_DOCUMENTS = (
    "case_d_commercial_invoice.pdf",
    "case_d_bill_of_lading.pdf",
    "case_d_packing_list.pdf",
    "case_d_mtc_test_cert.pdf",
)

# backend/app/api/v1/demo.py -> repo root is four levels above this file's directory.
# The packaged fallback is copied with ``app/`` by the backend Dockerfile.
# (the Case C directories keep their names: tests patch them; the other cases' directories sit next to them)
_REPOSITORY_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "case_c"
_PACKAGED_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "case_c"


def _require_demo_mode() -> None:
    if settings.app_mode != "demo":
        raise NotFoundError("Demo endpoints are only available when APP_MODE=demo.")


# Router dependencies run before endpoint dependencies. Keep this first so a
# live deployment answers 404 without attempting to authenticate a caller.
router = APIRouter(tags=["demo"], dependencies=[Depends(_require_demo_mode)])


def _fixture_dir(case: str = "case_c") -> Path:
    """Where a case's sample PDFs are: $CASE_C_FIXTURE_DIR / $CASE_D_FIXTURE_DIR, else fixtures/<case>/, else the copy
    packaged with the app."""
    override = os.environ.get(f"{case.upper()}_FIXTURE_DIR")
    if override:
        return Path(override)
    repository = _REPOSITORY_FIXTURE_DIR.parent / case
    if repository.is_dir():
        return repository
    return _PACKAGED_FIXTURE_DIR.parent / case


def _read_fixture(filename: str, case: str = "case_c") -> bytes:
    path = _fixture_dir(case) / filename
    if not path.is_file():
        # The path is the operator's business: it goes to the log, never into the response
        logger.error(
            "case_c_fixture_missing",
            path=str(path),
            filename=filename,
            hint=f"Run scripts/generate_case_c_pdfs.py, or set {case.upper()}_FIXTURE_DIR to the directory that holds the PDFs.",
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
async def create_case_c_demo(
    current_user: UserIdentity = Depends(get_current_user),
) -> BundleResponse:
    _require_demo_mode()

    # Read every file up-front so a missing fixture fails before a half-built bundle exists.
    payloads = {name: _read_fixture(name) for name in CASE_C_PRELOADED}

    bundle = await create_bundle(
        CreateBundleRequest(reference=CASE_C_REFERENCE, destination_country=CASE_C_DESTINATION),
        current_user=current_user,
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


@router.post(
    "/demo/case-d",
    response_model=BundleResponse,
    status_code=201,
    summary="Create a Case D demo bundle (India import) with its four sample PDFs",
)
async def create_case_d_demo(
    current_user: UserIdentity = Depends(get_current_user),
) -> BundleResponse:
    _require_demo_mode()

    payloads = {name: _read_fixture(name, "case_d") for name in CASE_D_DOCUMENTS}

    bundle = await create_bundle(
        CreateBundleRequest(reference=CASE_D_REFERENCE, destination_country=CASE_D_DESTINATION),
        current_user=current_user,
    )
    for name, data in payloads.items():
        await register_document(bundle.id, data=data, filename=name, iteration=0)

    stored = await firestore.get_bundle(bundle.id)
    if stored is None:  # pragma: no cover - the bundle was created a few lines above
        raise NotFoundError(f"Bundle '{bundle.id}' not found.", detail={"bundle_id": bundle.id})

    return BundleResponse(
        id=stored["id"],
        reference=stored.get("reference"),
        destination_country=stored.get("destination_country", CASE_D_DESTINATION),
        status=stored.get("status", "PENDING"),
        current_iteration=stored.get("current_iteration", 0),
        documents=stored.get("documents", []),
        created_at=stored.get("created_at", ""),
    )
