"""Usage router: what the model calls of a bundle cost, per run and per document (services/token_usage.py)."""

from fastapi import APIRouter, Path

from app.domain.schemas import RunUsage, TokenBudgetStatus, TokenUsage, UsageResponse, UsageTotals
from app.gateway.errors import NotFoundError
from app.repo import firestore
from app.services import token_budget

router = APIRouter(tags=["usage"])


@router.get(
    "/bundles/{bundle_id}/usage",
    response_model=UsageResponse,
    summary="What the model calls of this bundle cost: per run (failed runs included) and per document",
)
async def get_usage(bundle_id: str = Path(..., description="Target bundle ID")) -> UsageResponse:
    """Every run that asked the model something or served an answer from the cache, oldest first, with the tokens the API reported for
    each request (prompt, output, thinking, total), the requests whose answer was not used (cut off, invalid, failed), and the
    totals. A run that FAILED is listed too: it has no iteration, and the tokens it spent were spent. The relevance check at upload is
    counted once per document in ``upload_gate_tokens``, including documents since deleted (a file it refused is stored nowhere, so only
    the log shows that one).
    """
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    runs = [
        RunUsage(
            run_id=record["run_id"], iteration=record.get("iteration"), mode=record.get("mode"), state=record["state"],
            reason=record.get("reason"), created_at=record["created_at"], token_usage=TokenUsage(**record["token_usage"]),
        )
        for record in await firestore.list_usage(bundle_id)
    ]
    # a deleted document's record is gone; the bundle keeps what its upload check cost (firestore.delete_evidence_document)
    totals = UsageTotals(
        runs=len(runs),
        failed_runs=sum(1 for r in runs if r.state == "ERROR"),
        upload_gate_tokens=sum(int((d.get("gate_usage") or {}).get("total_tokens") or 0) for d in bundle.get("documents", []))
        + int(bundle.get("deleted_gate_tokens") or 0),
    )
    for key in ("requests", "failed_requests", "unknown_requests", "prompt_tokens", "output_tokens", "thinking_tokens", "total_tokens",
                "saved_tokens"):
        setattr(totals, key, sum(getattr(r.token_usage, key) for r in runs))
    return UsageResponse(bundle_id=bundle_id, runs=runs, totals=totals)


@router.get(
    "/token-budget",
    response_model=TokenBudgetStatus,
    summary="The service's daily model-token budget: the limit, today's spend and when it resets",
)
async def get_token_budget() -> TokenBudgetStatus:
    """One number for the whole service, UTC day: ``spent_tokens`` is null when the counter cannot be read (the budget is then not
    enforced). When ``remaining_tokens`` reaches 0 a new analysis or reassessment is refused (429 TOKEN_BUDGET_EXCEEDED) until the
    reset; a recompute is not."""
    return TokenBudgetStatus(**await token_budget.status())
