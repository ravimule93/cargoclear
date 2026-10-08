"""Firestore repository — async CRUD operations for all CargoClear Firestore collections.

Hierarchy:
  bundles/{id}                   → TradeBundle
  bundles/{id}/documents/{id}    → EvidenceDocument
  bundles/{id}/runs/{run_id}     → RunState
  bundles/{id}/iterations/{n}    → AssessmentIteration
  bundles/{id}/audit/{event_id}  → AuditEvent (append-only)

Implements clean error handling and graceful in-memory fallback for local development
and testing environments where GCP credentials are not configured.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# In-memory storage fallback for local development / testing without GCP credentials
_IN_MEMORY_BUNDLES: dict[str, dict[str, Any]] = {}
_IN_MEMORY_DOCS: dict[str, dict[str, Any]] = {}
_IN_MEMORY_RUNS: dict[str, dict[str, Any]] = {}
_IN_MEMORY_ITERATIONS: dict[str, list[dict[str, Any]]] = {}

# Lazy initialized Firestore client
_firestore_client = None


def _get_firestore_client():
    """Lazily initialize the async Firestore client."""
    global _firestore_client
    if _firestore_client is not None:
        return _firestore_client

    # Check if credentials or project are present
    has_creds = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("K_SERVICE"))
    if not has_creds and os.getenv("USE_FIRESTORE_EMULATOR") != "true":
        logger.info("firestore_in_memory_mode", reason="No GCP credentials found, running in-memory repository")
        return None

    try:
        from google.cloud.firestore_v1.async_client import AsyncClient

        _firestore_client = AsyncClient(
            project=settings.project_id,
            database=settings.firestore_database,
        )
        return _firestore_client
    except Exception as exc:
        logger.warning("firestore_client_init_failed", error=str(exc), fallback="in_memory")
        return None


# ---------------------------------------------------------------------------
# Bundle operations
# ---------------------------------------------------------------------------


async def create_bundle(bundle_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new TradeBundle document in Firestore."""
    bundle_id = bundle_data["id"]
    client = _get_firestore_client()

    if client is not None:
        doc_ref = client.collection("bundles").document(bundle_id)
        await doc_ref.set(bundle_data)
        logger.info("bundle_persisted_firestore", bundle_id=bundle_id)
    else:
        _IN_MEMORY_BUNDLES[bundle_id] = bundle_data
        _IN_MEMORY_DOCS[bundle_id] = {}
        logger.info("bundle_persisted_in_memory", bundle_id=bundle_id)

    return bundle_data


async def get_bundle(bundle_id: str) -> dict[str, Any] | None:
    """Fetch a TradeBundle by ID with its attached documents. Returns None if not found."""
    client = _get_firestore_client()

    if client is not None:
        doc_ref = client.collection("bundles").document(bundle_id)
        snapshot = await doc_ref.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict()
        # Fetch child documents
        docs_collection = doc_ref.collection("documents")
        docs_stream = docs_collection.stream()
        docs = [d.to_dict() async for d in docs_stream]
        data["documents"] = docs
        return data

    if bundle_id not in _IN_MEMORY_BUNDLES:
        return None

    bundle = dict(_IN_MEMORY_BUNDLES[bundle_id])
    bundle["documents"] = list(_IN_MEMORY_DOCS.get(bundle_id, {}).values())
    return bundle


# ---------------------------------------------------------------------------
# Document operations
# ---------------------------------------------------------------------------


async def create_evidence_document(bundle_id: str, doc_data: dict[str, Any]) -> dict[str, Any]:
    """Register a new EvidenceDocument under a bundle."""
    doc_id = doc_data["document_id"]
    client = _get_firestore_client()

    if client is not None:
        bundle_ref = client.collection("bundles").document(bundle_id)
        doc_ref = bundle_ref.collection("documents").document(doc_id)
        await doc_ref.set(doc_data)

        # Update bundle document count/status
        await bundle_ref.update({
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("document_persisted_firestore", bundle_id=bundle_id, document_id=doc_id)
    else:
        if bundle_id not in _IN_MEMORY_DOCS:
            _IN_MEMORY_DOCS[bundle_id] = {}
        _IN_MEMORY_DOCS[bundle_id][doc_id] = doc_data
        if bundle_id in _IN_MEMORY_BUNDLES:
            _IN_MEMORY_BUNDLES[bundle_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("document_persisted_in_memory", bundle_id=bundle_id, document_id=doc_id)

    return doc_data


async def get_evidence_document(document_id: str) -> dict[str, Any] | None:
    """Lookup document metadata by document_id across bundles."""
    client = _get_firestore_client()

    if client is not None:
        # Collection group query across all 'documents' subcollections
        query = client.collection_group("documents").where("document_id", "==", document_id).limit(1)
        results = [doc.to_dict() async for doc in query.stream()]
        return results[0] if results else None

    for bundle_docs in _IN_MEMORY_DOCS.values():
        if document_id in bundle_docs:
            return bundle_docs[document_id]
    return None


# ---------------------------------------------------------------------------
# Run & Pipeline state operations
# ---------------------------------------------------------------------------


async def set_run_stage(bundle_id: str, run_id: str, stage: str, progress: float) -> None:
    """Update pipeline stage and progress for SSE status polling."""
    run_state = {
        "kind": "status",
        "bundle_id": bundle_id,
        "run_id": run_id,
        "state": "RUNNING",
        "stage": stage,
        "progress": progress,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    client = _get_firestore_client()

    if client is not None:
        run_ref = client.collection("bundles").document(bundle_id).collection("runs").document(run_id)
        await run_ref.set(run_state, merge=True)
    else:
        _IN_MEMORY_RUNS[f"{bundle_id}:{run_id}"] = run_state


async def set_run_state(bundle_id: str, run_id: str, state: str, progress: float) -> None:
    """Update terminal pipeline state (COMPLETE/ERROR)."""
    run_state = {
        "kind": "status",
        "bundle_id": bundle_id,
        "run_id": run_id,
        "state": state,
        "progress": progress,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    client = _get_firestore_client()

    if client is not None:
        run_ref = client.collection("bundles").document(bundle_id).collection("runs").document(run_id)
        await run_ref.set(run_state, merge=True)
    else:
        key = f"{bundle_id}:{run_id}"
        if key in _IN_MEMORY_RUNS:
            _IN_MEMORY_RUNS[key].update(run_state)
        else:
            _IN_MEMORY_RUNS[key] = run_state


async def set_run_error(bundle_id: str, run_id: str, error: str) -> None:
    """Record an error on the run document."""
    run_state = {
        "kind": "status",
        "bundle_id": bundle_id,
        "run_id": run_id,
        "state": "ERROR",
        "message": error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    client = _get_firestore_client()

    if client is not None:
        run_ref = client.collection("bundles").document(bundle_id).collection("runs").document(run_id)
        await run_ref.set(run_state, merge=True)
    else:
        _IN_MEMORY_RUNS[f"{bundle_id}:{run_id}"] = run_state


async def get_run_state(bundle_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Fetch the latest run state for a bundle to power SSE stream."""
    client = _get_firestore_client()

    if client is not None:
        runs_ref = client.collection("bundles").document(bundle_id).collection("runs")
        if run_id:
            doc = await runs_ref.document(run_id).get()
            if doc.exists:
                return doc.to_dict()
        else:
            query = runs_ref.order_by("updated_at", direction="DESCENDING").limit(1)
            results = [doc.to_dict() async for doc in query.stream()]
            if results:
                return results[0]

    # In-memory lookup
    if run_id:
        key = f"{bundle_id}:{run_id}"
        if key in _IN_MEMORY_RUNS:
            return _IN_MEMORY_RUNS[key]
    else:
        matching = [v for k, v in _IN_MEMORY_RUNS.items() if k.startswith(f"{bundle_id}:")]
        if matching:
            return matching[-1]

    return {
        "kind": "status",
        "bundle_id": bundle_id,
        "run_id": run_id or "default",
        "state": "COMPLETE",
        "stage": None,
        "progress": 1.0,
        "message": "Ready",
    }


# ---------------------------------------------------------------------------
# Assessment iteration operations
# ---------------------------------------------------------------------------


async def write_iteration(ctx: dict[str, Any]) -> dict[str, Any]:
    """Persist an immutable AssessmentIteration point-in-time snapshot."""
    bundle_id = ctx["bundle_id"]
    iteration_num = ctx.get("iteration", 1)

    iteration_data = {
        "iteration": iteration_num,
        "bundle_id": bundle_id,
        "status": ctx.get("final_status", "COMPLIANT_FOR_SUBMISSION"),
        "checks": ctx.get("checks", []),
        "grounding": ctx.get("grounding", []),
        "missing_evidence": ctx.get("missing_evidence", []),
        "confidence": ctx.get("confidence"),
        "reasoning_delta": ctx.get("reasoning_delta"),
        "documents": [d.get("document_id") for d in ctx.get("documents", []) if isinstance(d, dict)],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    client = _get_firestore_client()

    if client is not None:
        bundle_ref = client.collection("bundles").document(bundle_id)
        iter_ref = bundle_ref.collection("iterations").document(str(iteration_num))
        await iter_ref.set(iteration_data)

        # Update bundle current status and current iteration
        await bundle_ref.update({
            "status": iteration_data["status"],
            "current_iteration": iteration_num,
            "updated_at": iteration_data["created_at"],
        })
    else:
        if bundle_id not in _IN_MEMORY_ITERATIONS:
            _IN_MEMORY_ITERATIONS[bundle_id] = []
        _IN_MEMORY_ITERATIONS[bundle_id].append(iteration_data)
        if bundle_id in _IN_MEMORY_BUNDLES:
            _IN_MEMORY_BUNDLES[bundle_id]["status"] = iteration_data["status"]
            _IN_MEMORY_BUNDLES[bundle_id]["current_iteration"] = iteration_num

    return iteration_data


async def latest_iteration(bundle_id: str) -> dict[str, Any] | None:
    """Fetch the most recent AssessmentIteration for a bundle."""
    client = _get_firestore_client()

    if client is not None:
        iters_ref = client.collection("bundles").document(bundle_id).collection("iterations")
        query = iters_ref.order_by("iteration", direction="DESCENDING").limit(1)
        results = [doc.to_dict() async for doc in query.stream()]
        return results[0] if results else None

    iters = _IN_MEMORY_ITERATIONS.get(bundle_id, [])
    return iters[-1] if iters else None


async def list_iterations(bundle_id: str) -> list[dict[str, Any]]:
    """List all AssessmentIterations in chronological order."""
    client = _get_firestore_client()

    if client is not None:
        iters_ref = client.collection("bundles").document(bundle_id).collection("iterations")
        query = iters_ref.order_by("iteration", direction="ASCENDING")
        return [doc.to_dict() async for doc in query.stream()]

    return list(_IN_MEMORY_ITERATIONS.get(bundle_id, []))
