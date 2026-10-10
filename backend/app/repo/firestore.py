"""Firestore repository — async CRUD operations for all CargoClear Firestore collections.

Hierarchy:
  bundles/{id}                   → TradeBundle
  bundles/{id}/documents/{id}    → EvidenceDocument
  bundles/{id}/runs/{run_id}     → RunState
  bundles/{id}/iterations/{n}    → AssessmentIteration
  bundles/{id}/extractions/{n}   → Extractions record
  bundles/{id}/audit/{event_id}  → AuditEvent (append-only)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.config import settings
from app.core.mode import no_credentials_message, use_live_gcp
from app.domain.provenance import derive_data_source
from app.gateway.errors import PipelineError, UpstreamError

logger = structlog.get_logger(__name__)

# In-memory storage fallback for local development / testing without GCP credentials
_IN_MEMORY_BUNDLES: dict[str, dict[str, Any]] = {}
_IN_MEMORY_DOCS: dict[str, dict[str, Any]] = {}
_IN_MEMORY_RUNS: dict[str, dict[str, Any]] = {}
_IN_MEMORY_ITERATIONS: dict[str, list[dict[str, Any]]] = {}
_IN_MEMORY_EXTRACTIONS: dict[str, dict[int, list[dict[str, Any]]]] = {}

# Lazy initialized Firestore client
_firestore_client = None


def _get_firestore_client():
    """Lazily initialize the async Firestore client."""
    global _firestore_client
    if _firestore_client is not None:
        return _firestore_client

    if not use_live_gcp():
        if settings.app_mode == "live":
            raise UpstreamError(no_credentials_message())
        logger.info("firestore_in_memory_mode", reason="Running in demo mode without GCP credentials")
        return None

    try:
        from google.cloud.firestore_v1.async_client import AsyncClient

        _firestore_client = AsyncClient(
            project=settings.project_id,
            database=settings.firestore_database,
        )
        return _firestore_client
    except Exception as exc:
        if settings.app_mode == "live":
            raise UpstreamError(f"Firestore client init failed in live mode: {type(exc).__name__}") from exc
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


async def update_document_doc_type(bundle_id: str, document_id: str, doc_type: str) -> None:
    """Update the doc_type of an existing document after classification."""
    client = _get_firestore_client()

    if client is not None:
        doc_ref = client.collection("bundles").document(bundle_id).collection("documents").document(document_id)
        await doc_ref.update({"doc_type": doc_type})
    else:
        if bundle_id in _IN_MEMORY_DOCS and document_id in _IN_MEMORY_DOCS[bundle_id]:
            _IN_MEMORY_DOCS[bundle_id][document_id]["doc_type"] = doc_type


async def get_bundle_document(bundle_id: str, document_id: str) -> dict[str, Any] | None:
    """Lookup a document specifically within a bundle."""
    client = _get_firestore_client()

    if client is not None:
        doc_ref = client.collection("bundles").document(bundle_id).collection("documents").document(document_id)
        snap = await doc_ref.get()
        return snap.to_dict() if snap.exists else None

    if bundle_id in _IN_MEMORY_DOCS and document_id in _IN_MEMORY_DOCS[bundle_id]:
        return _IN_MEMORY_DOCS[bundle_id][document_id]
    return None


async def get_evidence_document(document_id: str) -> dict[str, Any] | None:
    """Lookup document metadata by document_id across bundles."""
    client = _get_firestore_client()

    if client is not None:
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


async def touch_run(bundle_id: str, run_id: str) -> None:
    """Heartbeat: refresh ``updated_at`` of a run, changing NOTHING else and only while its stored state is RUNNING.

    A finished (COMPLETE / ERROR) run is never touched and a missing run is never created, so a late heartbeat
    cannot revive or resurrect anything. On Firestore this is a read followed by a one-field update (not a
    transaction): the only race is a heartbeat landing just after another writer finished the run, which moves
    ``updated_at`` of a finished record and cannot change its ``state``.
    """
    now = datetime.now(timezone.utc).isoformat()
    client = _get_firestore_client()

    if client is not None:
        run_ref = client.collection("bundles").document(bundle_id).collection("runs").document(run_id)
        snapshot = await run_ref.get()
        stored = snapshot.to_dict() if snapshot.exists else None
        if stored is not None and stored.get("state") == "RUNNING":
            await run_ref.update({"updated_at": now})
        return

    record = _IN_MEMORY_RUNS.get(f"{bundle_id}:{run_id}")
    if record is not None and record.get("state") == "RUNNING":
        record["updated_at"] = now


async def set_run_state(
    bundle_id: str, run_id: str, state: str, progress: float, only_if_state: str | None = None
) -> bool:
    """Update terminal pipeline state (COMPLETE/ERROR). Returns True if the write was applied.

    With ``only_if_state`` the write is applied only while the stored state of the run equals it (a missing run counts
    as "not equal"); otherwise nothing is written and False is returned. The orchestrator uses this so that a run which
    was reaped (ERROR) while it was merely slow cannot overwrite that with COMPLETE. On Firestore the check is a read
    followed by the write, not a transaction (see ``touch_run``): the API is one instance, and the orchestrator also
    verifies its claim before it writes the iteration.
    """
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
        if only_if_state is not None:
            snapshot = await run_ref.get()
            stored = snapshot.to_dict() if snapshot.exists else None
            if stored is None or stored.get("state") != only_if_state:
                return False
        await run_ref.set(run_state, merge=True)
        return True

    key = f"{bundle_id}:{run_id}"
    if only_if_state is not None:
        record = _IN_MEMORY_RUNS.get(key)
        if record is None or record.get("state") != only_if_state:
            return False
    if key in _IN_MEMORY_RUNS:
        _IN_MEMORY_RUNS[key].update(run_state)
    else:
        _IN_MEMORY_RUNS[key] = run_state
    return True


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
    """Persist an immutable AssessmentIteration point-in-time snapshot.

    Create-only: writing an iteration number that already exists raises PipelineError instead of overwriting it.
    """
    bundle_id = ctx["bundle_id"]
    iteration_num = ctx.get("iteration", 1)
    data_source = derive_data_source(ctx)

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
        "data_source": data_source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    client = _get_firestore_client()
    already_exists = f"iteration {iteration_num} already exists for bundle {bundle_id}"

    if client is not None:
        from google.api_core.exceptions import AlreadyExists

        bundle_ref = client.collection("bundles").document(bundle_id)
        iter_ref = bundle_ref.collection("iterations").document(str(iteration_num))
        try:
            await iter_ref.create(iteration_data)  # create-only: an iteration is immutable and never overwritten
        except AlreadyExists as exc:
            raise PipelineError(already_exists, detail={"bundle_id": bundle_id, "iteration": iteration_num}) from exc

        await bundle_ref.update({
            "status": iteration_data["status"],
            "current_iteration": iteration_num,
            "updated_at": iteration_data["created_at"],
        })
    else:
        if bundle_id not in _IN_MEMORY_ITERATIONS:
            _IN_MEMORY_ITERATIONS[bundle_id] = []
        if any(existing.get("iteration") == iteration_num for existing in _IN_MEMORY_ITERATIONS[bundle_id]):
            raise PipelineError(already_exists, detail={"bundle_id": bundle_id, "iteration": iteration_num})
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


# ---------------------------------------------------------------------------
# Extractions persistence
# ---------------------------------------------------------------------------


async def save_extractions(bundle_id: str, iteration: int, extractions: list[dict[str, Any]]) -> None:
    """Persist per-document extraction JSON for an iteration."""
    client = _get_firestore_client()

    data = {
        "bundle_id": bundle_id,
        "iteration": iteration,
        "extractions": extractions,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if client is not None:
        ref = client.collection("bundles").document(bundle_id).collection("extractions").document(str(iteration))
        await ref.set(data)
    else:
        if bundle_id not in _IN_MEMORY_EXTRACTIONS:
            _IN_MEMORY_EXTRACTIONS[bundle_id] = {}
        _IN_MEMORY_EXTRACTIONS[bundle_id][iteration] = extractions


async def get_extractions(bundle_id: str, iteration: int | None = None) -> list[dict[str, Any]]:
    """Get per-document extraction JSON for a bundle."""
    client = _get_firestore_client()

    if iteration is None:
        latest = await latest_iteration(bundle_id)
        iteration = latest.get("iteration", 1) if latest else 1

    if client is not None:
        ref = client.collection("bundles").document(bundle_id).collection("extractions").document(str(iteration))
        snap = await ref.get()
        if snap.exists:
            return snap.to_dict().get("extractions", [])
        return []

    return _IN_MEMORY_EXTRACTIONS.get(bundle_id, {}).get(iteration, [])
