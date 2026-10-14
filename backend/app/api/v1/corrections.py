"""Corrections router: the authorised agent states what a document actually says, and undoes it again.

A correction does not change the assessment by itself. It is an audited entry (FIELD_CORRECTED / FIELD_CONFIRMED); the next run
of any mode lays it over the extraction, and ``POST /bundles/{id}/recompute`` (api/v1/assessment.py) re-runs the checks
without reading the documents again.
"""

from fastapi import APIRouter, Path

from app.domain.schemas import CorrectionRecord, CorrectionRequest, CorrectionsResponse, RevertCorrectionRequest
from app.gateway.errors import NotFoundError
from app.repo import firestore
from app.services import corrections

router = APIRouter(tags=["corrections"])


async def _require_bundle(bundle_id: str) -> None:
    if await firestore.get_bundle(bundle_id) is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})


@router.get(
    "/bundles/{bundle_id}/corrections",
    response_model=CorrectionsResponse,
    summary="List the corrections made to this bundle's extraction",
)
async def list_corrections(bundle_id: str = Path(..., description="Target bundle ID")) -> CorrectionsResponse:
    """Every entry (corrections, confirmations, undos), the overlay in force now, and how many changes the latest assessment lacks."""
    await _require_bundle(bundle_id)
    return await corrections.state(bundle_id)


@router.post(
    "/bundles/{bundle_id}/corrections",
    response_model=CorrectionRecord,
    status_code=201,
    summary="Correct (or confirm) one value the model read",
)
async def create_correction(body: CorrectionRequest, bundle_id: str = Path(..., description="Target bundle ID")) -> CorrectionRecord:
    """Records what the document actually states at one address of the latest extraction.

    409 before the first analysis; 404 for a document or row that is not in the latest extraction; 422 for a value that cannot
    be read without guessing (an ambiguous number, a weight without a unit, an unknown document type).
    """
    await _require_bundle(bundle_id)
    return await corrections.submit(bundle_id, body)


@router.post(
    "/bundles/{bundle_id}/corrections/{correction_id}/revert",
    response_model=CorrectionRecord,
    status_code=201,
    summary="Undo a correction that is in force",
)
async def revert_correction(
    bundle_id: str = Path(..., description="Target bundle ID"),
    correction_id: str = Path(..., description="'cor-<n>' as listed by GET /corrections"),
    body: RevertCorrectionRequest | None = None,
) -> CorrectionRecord:
    """Appends an undo entry; the history is never edited. The value returns to the entry before, or to what the model read."""
    await _require_bundle(bundle_id)
    return await corrections.revert(bundle_id, correction_id, body.reason if body else None)
