"""Assessment router — analyze, reassess, get assessment, list iterations."""

from fastapi import APIRouter, Path

from app.domain.schemas import AssessmentIteration, RunResponse
from app.gateway.errors import NotFoundError
from app.repo import firestore
from app.services import orchestrator

router = APIRouter(tags=["assessment"])


@router.post(
    "/bundles/{bundle_id}/analyze",
    response_model=RunResponse,
    status_code=202,
    summary="Start full assessment pipeline run",
)
async def analyze(
    bundle_id: str = Path(..., description="Target bundle ID"),
) -> RunResponse:
    """Initiates the 7-stage assessment pipeline in the background.

    Returns run_id immediately with 202 Accepted.
    Progress is streamed via SSE on /bundles/{id}/stream.
    """
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    run_id = await orchestrator.start_run(bundle_id, mode="full")

    return RunResponse(
        run_id=run_id,
        bundle_id=bundle_id,
        state="RUNNING",
        message="Full analysis pipeline initiated. Subscribe to /stream for real-time progress.",
    )


@router.post(
    "/bundles/{bundle_id}/reassess",
    response_model=RunResponse,
    status_code=202,
    summary="Reassess after new evidence document is uploaded",
)
async def reassess(
    bundle_id: str = Path(..., description="Target bundle ID"),
) -> RunResponse:
    """Reruns the assessment pipeline against updated documents.

    Generates a new AssessmentIteration and computes the Reasoning Delta
    diff against the previous iteration.
    """
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    run_id = await orchestrator.start_run(bundle_id, mode="reassess")

    return RunResponse(
        run_id=run_id,
        bundle_id=bundle_id,
        state="RUNNING",
        message="Reassessment initiated. Subscribe to /stream for updated findings.",
    )


@router.get(
    "/bundles/{bundle_id}/assessment",
    response_model=AssessmentIteration,
    summary="Get the latest validated compliance assessment",
)
async def get_assessment(bundle_id: str = Path(...)) -> AssessmentIteration:
    """Return the most recent AssessmentIteration for the bundle."""
    iter_data = await firestore.latest_iteration(bundle_id)
    if iter_data is None:
        raise NotFoundError(
            f"No assessment iteration found for bundle '{bundle_id}'. Run /analyze first.",
            detail={"bundle_id": bundle_id},
        )
    return AssessmentIteration(**iter_data)


@router.get(
    "/bundles/{bundle_id}/iterations",
    response_model=list[AssessmentIteration],
    summary="List all assessment iterations for the Reasoning Delta view",
)
async def list_iterations(bundle_id: str = Path(...)) -> list[AssessmentIteration]:
    """Return all AssessmentIterations in chronological order."""
    iterations = await firestore.list_iterations(bundle_id)
    return [AssessmentIteration(**it) for it in iterations]
