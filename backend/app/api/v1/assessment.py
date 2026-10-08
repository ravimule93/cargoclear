"""Assessment router — analyze, reassess, get assessment, list iterations."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Path

from app.domain.schemas import AssessmentIteration, RunResponse
from app.gateway.errors import NotFoundError

router = APIRouter(tags=["assessment"])


@router.post(
    "/bundles/{bundle_id}/analyze",
    response_model=RunResponse,
    status_code=202,
    summary="Start a full assessment pipeline run",
)
async def analyze(
    bundle_id: str = Path(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> RunResponse:
    """Trigger the full pipeline: preprocess → extract → discrepancy → ground →
    confidence → synthesize → audit.

    Returns immediately with a run_id; progress is streamed via SSE.

    Phase 2: Wires to services.orchestrator.start_run(mode='full').
    Skeleton: Returns a stub 202.
    """
    # TODO(Phase 2): await orchestrator.start_run(bundle_id, mode="full")
    run_id = str(uuid.uuid4())
    return RunResponse(
        run_id=run_id,
        bundle_id=bundle_id,
        state="QUEUED",
        message="Analysis queued. Subscribe to /stream for progress.",
    )


@router.post(
    "/bundles/{bundle_id}/reassess",
    response_model=RunResponse,
    status_code=202,
    summary="Reassess after a new document has been uploaded",
)
async def reassess(
    bundle_id: str = Path(...),
) -> RunResponse:
    """Re-run the full pipeline on the updated document set.

    Produces a new AssessmentIteration and a Reasoning Delta comparing
    it to the previous iteration.

    Phase 2: Wires to services.orchestrator.start_run(mode='reassess').
    Skeleton: Returns a stub 202.
    """
    # TODO(Phase 2): await orchestrator.start_run(bundle_id, mode="reassess")
    run_id = str(uuid.uuid4())
    return RunResponse(
        run_id=run_id,
        bundle_id=bundle_id,
        state="QUEUED",
        message="Reassessment queued. Subscribe to /stream for progress.",
    )


@router.get(
    "/bundles/{bundle_id}/assessment",
    response_model=AssessmentIteration,
    summary="Get the latest validated compliance assessment",
)
async def get_assessment(bundle_id: str = Path(...)) -> AssessmentIteration:
    """Return the most recent AssessmentIteration for the bundle.

    Phase 1: Reads from Firestore via repo.firestore.latest_iteration().
    Skeleton: Returns 404.
    """
    # TODO(Phase 1): return await repo.firestore.latest_iteration(bundle_id)
    raise NotFoundError(
        f"No assessment found for bundle '{bundle_id}'.",
        detail={"bundle_id": bundle_id},
    )


@router.get(
    "/bundles/{bundle_id}/iterations",
    response_model=list[AssessmentIteration],
    summary="List all assessment iterations for the Reasoning Delta view",
)
async def list_iterations(bundle_id: str = Path(...)) -> list[AssessmentIteration]:
    """Return all AssessmentIterations in chronological order.

    Used by the frontend DeltaDrawer to render the full reasoning delta history.

    Phase 1: Reads from Firestore via repo.firestore.list_iterations().
    Skeleton: Returns empty list.
    """
    # TODO(Phase 1): return await repo.firestore.list_iterations(bundle_id)
    return []
