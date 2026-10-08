"""Assessment pipeline orchestrator.

Runs the multi-stage pipeline as a fire-and-forget asyncio task.
Reports progress to Firestore so the SSE stream can relay it to the UI.

Pipeline stages:
  FULL:     preprocess → extract → discrepancy → ground → confidence → synthesize → audit
  REASSESS: preprocess → extract → discrepancy → ground → confidence → synthesize → audit
  (Same stages; orchestrator fetches previous iteration for Reasoning Delta diff.)

Phase 2: Wire extraction agent + all services.
Phase 1: Wire storage + Firestore.
Skeleton: Runs a no-op pipeline with synthetic stub context.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

from app.gateway.dispatch import dispatch

logger = structlog.get_logger(__name__)

PIPELINE_STAGES = [
    "preprocess",
    "extract",
    "discrepancy",
    "ground",
    "confidence",
    "synthesize",
    "audit",
]

# Progress checkpoints (fraction complete after each stage)
_STAGE_PROGRESS = {
    "preprocess": 0.10,
    "extract": 0.35,
    "discrepancy": 0.55,
    "ground": 0.70,
    "confidence": 0.80,
    "synthesize": 0.90,
    "audit": 1.00,
}


async def start_run(bundle_id: str, mode: str = "full") -> str:
    """Start the assessment pipeline as a background asyncio task.

    Returns immediately with a run_id.
    Progress is written to Firestore and relayed via SSE.
    """
    run_id = str(uuid.uuid4())
    ctx = {
        "bundle_id": bundle_id,
        "run_id": run_id,
        "mode": mode,
        # TODO(Phase 1): populate from Firestore
        "raw_bytes": b"",
        "documents": [],
        "uploaded_types": [],
        "destination_country": "SG",
        "previous_iteration": None,
    }

    # Fire-and-forget — caller gets run_id immediately
    asyncio.create_task(_execute(ctx))
    return run_id


async def _execute(ctx: dict) -> None:
    """Run the pipeline stages sequentially, writing progress to Firestore."""
    bundle_id = ctx["bundle_id"]
    run_id = ctx["run_id"]

    logger.info("pipeline_started", bundle_id=bundle_id, run_id=run_id, mode=ctx["mode"])

    try:
        for stage in PIPELINE_STAGES:
            ctx["stage"] = stage
            progress = _STAGE_PROGRESS[stage]

            logger.info("stage_started", bundle_id=bundle_id, stage=stage, progress=progress)

            # TODO(Phase 1): await repo.firestore.set_run_stage(bundle_id, run_id, stage, progress)

            ctx = await dispatch(stage, ctx)

            logger.info("stage_completed", bundle_id=bundle_id, stage=stage)

        # TODO(Phase 1): await repo.firestore.write_iteration(ctx)
        # TODO(Phase 1): await repo.firestore.set_run_state(bundle_id, run_id, "COMPLETE", 1.0)

        logger.info("pipeline_completed", bundle_id=bundle_id, run_id=run_id,
                    status=ctx.get("final_status"))

    except Exception as exc:
        logger.exception("pipeline_failed", bundle_id=bundle_id, run_id=run_id, exc_info=exc)
        # TODO(Phase 1): await repo.firestore.set_run_error(bundle_id, run_id, str(exc))
