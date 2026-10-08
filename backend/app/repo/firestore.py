"""Firestore repository — async CRUD for all Firestore collections.

Collections:
  bundles/{id}                   → TradeBundle
  bundles/{id}/documents/{id}    → EvidenceDocument
  bundles/{id}/runs/{run_id}     → RunState
  bundles/{id}/iterations/{n}    → AssessmentIteration
  bundles/{id}/audit/{event_id}  → AuditEvent (append-only)

Phase 1: Uncomment AsyncClient and implement all operations.
Skeleton: All functions raise NotImplementedError.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# ---- Phase 1: uncomment ----
# from google.cloud.firestore_v1.async_client import AsyncClient
# from app.core.config import settings
# db: AsyncClient = AsyncClient(project=settings.project_id,
#                                database=settings.firestore_database)
# ----------------------------

db = None  # Phase 1: replace with AsyncClient


async def create_bundle(bundle_data: dict) -> dict:
    """Create a new TradeBundle document in Firestore."""
    # TODO(Phase 1): implement
    raise NotImplementedError


async def get_bundle(bundle_id: str) -> dict | None:
    """Fetch a TradeBundle by ID. Returns None if not found."""
    # TODO(Phase 1): implement
    raise NotImplementedError


async def create_evidence_document(bundle_id: str, doc_data: dict) -> dict:
    """Register a new EvidenceDocument under a bundle."""
    # TODO(Phase 1): implement
    raise NotImplementedError


async def set_run_stage(bundle_id: str, run_id: str, stage: str, progress: float) -> None:
    """Update the current pipeline stage and progress in the run document."""
    # TODO(Phase 1): implement
    raise NotImplementedError


async def set_run_state(bundle_id: str, run_id: str, state: str, progress: float) -> None:
    """Set the terminal state (COMPLETE / ERROR) of a run."""
    # TODO(Phase 1): implement
    raise NotImplementedError


async def set_run_error(bundle_id: str, run_id: str, error: str) -> None:
    """Record an error on the run document."""
    # TODO(Phase 1): implement
    raise NotImplementedError


async def get_run_state(bundle_id: str) -> dict:
    """Fetch the current run state for SSE polling. Returns a StatusEvent-compatible dict."""
    # TODO(Phase 1): implement
    # Skeleton: return a synthetic COMPLETE state
    return {
        "kind": "status",
        "bundle_id": bundle_id,
        "run_id": "skeleton-run",
        "state": "COMPLETE",
        "stage": None,
        "progress": 1.0,
        "message": "Skeleton mode.",
    }


async def write_iteration(ctx: dict) -> None:
    """Persist an AssessmentIteration to Firestore."""
    # TODO(Phase 1): implement
    raise NotImplementedError


async def latest_iteration(bundle_id: str) -> dict | None:
    """Fetch the most recent AssessmentIteration for a bundle."""
    # TODO(Phase 1): implement
    return None


async def list_iterations(bundle_id: str) -> list[dict]:
    """List all AssessmentIterations in chronological order."""
    # TODO(Phase 1): implement
    return []
