"""Assessment pipeline orchestrator.

Runs the multi-stage adjudication pipeline as an asynchronous background task.
Reports progress at each stage transition so the SSE stream can push updates to the UI.

Pipeline stages:
  1. preprocess:  Normalizes PDF pages and records transform metadata.
  2. extract:     Gemini 2.5 Flash multimodal vision extraction -> strict JSON.
  3. discrepancy: Deterministic math engine (weight parity, entity alignment, HS check).
  4. ground:      BigQuery AHTN tariff vector search & required document lookup.
  5. confidence:  Confidence routing table (auto-accept, interactive review, manual).
  6. synthesize:  Final status resolution (precedence order) and Reasoning Delta diff.
  7. audit:       Cryptographic hash-chained tamper-evident event log.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from app.domain.status import Status, resolve_status
from app.gateway.dispatch import dispatch
from app.repo import firestore
from app.services import storage

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

# Progress fractions per stage
_STAGE_PROGRESS = {
    "preprocess": 0.15,
    "extract": 0.40,
    "discrepancy": 0.60,
    "ground": 0.75,
    "confidence": 0.85,
    "synthesize": 0.95,
    "audit": 1.00,
}


async def start_run(bundle_id: str, mode: str = "full") -> str:
    """Start the assessment pipeline as a background asyncio task.

    Returns:
        run_id immediately so callers (POST /analyze, POST /reassess) can return 202.
    """
    run_id = f"run-{uuid.uuid4().hex[:12]}"

    # Fetch bundle and attached documents
    bundle = await firestore.get_bundle(bundle_id)
    documents = bundle.get("documents", []) if bundle else []
    prev_iteration = await firestore.latest_iteration(bundle_id)

    current_iter_num = (bundle.get("current_iteration", 0) if bundle else 0) + 1

    ctx: dict[str, Any] = {
        "bundle_id": bundle_id,
        "run_id": run_id,
        "mode": mode,
        "iteration": current_iter_num,
        "destination_country": bundle.get("destination_country", "SG") if bundle else "SG",
        "documents": documents,
        "previous_iteration": prev_iteration,
        "raw_bytes": b"",
        "uploaded_types": [d.get("doc_type", "UNKNOWN") for d in documents],
    }

    # Initialize run record in Firestore / in-memory store
    await firestore.set_run_stage(bundle_id, run_id, stage="initializing", progress=0.05)

    # Fire and forget pipeline execution
    asyncio.create_task(_execute_pipeline(ctx))
    return run_id


async def _execute_pipeline(ctx: dict[str, Any]) -> None:
    """Execute the pipeline stages sequentially with error containment."""
    bundle_id = ctx["bundle_id"]
    run_id = ctx["run_id"]
    logger.info("pipeline_started", bundle_id=bundle_id, run_id=run_id, mode=ctx["mode"])

    try:
        # Load raw bytes for document preprocessing if available
        docs = ctx.get("documents", [])
        if docs:
            first_doc = docs[0]
            try:
                raw_bytes = await storage.download_raw(bundle_id, first_doc["document_id"])
                ctx["raw_bytes"] = raw_bytes
                ctx["document_id"] = first_doc["document_id"]
            except Exception as exc:
                logger.debug("storage_raw_bytes_skipped", doc=first_doc.get("document_id"), error=str(exc))

        for stage in PIPELINE_STAGES:
            ctx["stage"] = stage
            progress = _STAGE_PROGRESS[stage]
            await firestore.set_run_stage(bundle_id, run_id, stage=stage, progress=progress)
            logger.info("stage_running", bundle_id=bundle_id, stage=stage, progress=progress)

            # Route through decoupled stage dispatcher
            ctx = await dispatch(stage, ctx)

        # Synthesize final status using the 4-status precedence rule
        candidates: list[Status] = []
        if ctx.get("missing_evidence"):
            candidates.append(Status.MISSING_EVIDENCE)
        if ctx.get("math_status") == Status.MATERIAL_CONTRADICTION:
            candidates.append(Status.MATERIAL_CONTRADICTION)
        if ctx.get("grounding_ambiguous") or ctx.get("math_status") == Status.SPECIALIST_REVIEW_REQUIRED:
            candidates.append(Status.SPECIALIST_REVIEW_REQUIRED)
        if ctx.get("force_status"):
            candidates.append(Status(ctx["force_status"]))

        final_status = resolve_status(candidates)
        ctx["final_status"] = final_status.value

        # Write immutable AssessmentIteration point-in-time snapshot
        await firestore.write_iteration(ctx)

        # Mark run COMPLETE
        await firestore.set_run_state(bundle_id, run_id, state="COMPLETE", progress=1.0)
        logger.info("pipeline_finished_successfully", bundle_id=bundle_id, status=ctx["final_status"])

    except Exception as exc:
        logger.exception("pipeline_failed", bundle_id=bundle_id, run_id=run_id, error=str(exc))
        await firestore.set_run_error(bundle_id, run_id, error=str(exc))
