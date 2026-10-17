"""Assessment router — analyze, reassess, get assessment, list iterations."""

from fastapi import APIRouter, Depends, Path, Request

from app.core.mode import EXECUTION_MODE_COOKIE, EXECUTION_MODE_HEADER, resolve_execution_mode
from app.domain.schemas import AssessmentIteration, RunResponse
from app.gateway.authorization import require_authorized_bundle
from app.gateway.errors import NotFoundError
from app.repo import firestore
from app.services import orchestrator

router = APIRouter(tags=["assessment"], dependencies=[Depends(require_authorized_bundle)])


@router.post(
    "/bundles/{bundle_id}/analyze",
    response_model=RunResponse,
    status_code=202,
    summary="Start full assessment pipeline run",
)
async def analyze(
    request: Request,
    bundle_id: str = Path(..., description="Target bundle ID"),
) -> RunResponse:
    """Initiates the six-stage assessment pipeline (plus its finalize step) in the background.

    Returns run_id immediately with 202 Accepted.
    Progress is streamed via SSE on /bundles/{id}/stream.
    """
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    exec_mode = resolve_execution_mode(
        header_val=request.headers.get(EXECUTION_MODE_HEADER),
        cookie_val=request.cookies.get(EXECUTION_MODE_COOKIE),
    )
    run_id = await orchestrator.start_run(bundle_id, mode="full", execution_mode=exec_mode)

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
    request: Request,
    bundle_id: str = Path(..., description="Target bundle ID"),
) -> RunResponse:
    """Reruns the assessment pipeline against updated documents.

    Generates a new AssessmentIteration and computes the Reasoning Delta
    diff against the previous iteration.
    """
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    exec_mode = resolve_execution_mode(
        header_val=request.headers.get(EXECUTION_MODE_HEADER),
        cookie_val=request.cookies.get(EXECUTION_MODE_COOKIE),
    )
    run_id = await orchestrator.start_run(bundle_id, mode="reassess", execution_mode=exec_mode)

    return RunResponse(
        run_id=run_id,
        bundle_id=bundle_id,
        state="RUNNING",
        message="Reassessment initiated. Subscribe to /stream for updated findings.",
    )


@router.post(
    "/bundles/{bundle_id}/recompute",
    response_model=RunResponse,
    status_code=202,
    summary="Re-run the checks on the stored extraction, with the agent's corrections applied",
)
async def recompute(
    request: Request,
    bundle_id: str = Path(..., description="Target bundle ID"),
) -> RunResponse:
    """Starts a ``recompute`` run: no document is read again and no model is called; the extraction of the latest
    assessment is reused, the corrections in force are laid over it, and every check runs again.

    409 when there is no assessment yet, when documents were added since (use /reassess), or while a run is in progress.
    """
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    exec_mode = resolve_execution_mode(
        header_val=request.headers.get(EXECUTION_MODE_HEADER),
        cookie_val=request.cookies.get(EXECUTION_MODE_COOKIE),
    )
    run_id = await orchestrator.start_run(bundle_id, mode="recompute", execution_mode=exec_mode)

    return RunResponse(
        run_id=run_id,
        bundle_id=bundle_id,
        state="RUNNING",
        message="Recompute initiated. The stored extraction is reused with your corrections applied.",
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
    """Return all AssessmentIterations in chronological order (404 for an unknown bundle; [] before the first run)."""
    if await firestore.get_bundle(bundle_id) is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})
    iterations = await firestore.list_iterations(bundle_id)
    return [AssessmentIteration(**it) for it in iterations]
