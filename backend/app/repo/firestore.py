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

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.core.config import settings
from app.core.mode import no_credentials_message, use_live_gcp
from app.domain.provenance import derive_data_source
from app.gateway.errors import PipelineError, UpstreamError
from app.repo import leases

logger = structlog.get_logger(__name__)

# In-memory storage fallback for local development / testing without GCP credentials
_IN_MEMORY_BUNDLES: dict[str, dict[str, Any]] = {}
_IN_MEMORY_DOCS: dict[str, dict[str, Any]] = {}
_IN_MEMORY_RUNS: dict[str, dict[str, Any]] = {}
_IN_MEMORY_ITERATIONS: dict[str, list[dict[str, Any]]] = {}
_IN_MEMORY_EXTRACTIONS: dict[str, dict[int, dict[str, Any]]] = {}
_IN_MEMORY_DAILY_TOKENS: dict[str, int] = {}  # UTC day (YYYYMMDD) -> model tokens the service spent that day
_IN_MEMORY_USAGE: dict[str, dict[str, dict[str, Any]]] = {}  # bundle -> run id -> what that run's model calls cost
_IN_MEMORY_EXTRACTION_CACHE: dict[str, dict[str, dict[str, Any]]] = {}  # bundle -> request fingerprint -> the model's answer

# Lazy initialized Firestore client
_firestore_client = None


def _get_firestore_client() -> Any:
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


async def _attach_bundle_documents(doc_ref: Any, b_data: dict[str, Any]) -> dict[str, Any]:
    try:
        docs_stream = doc_ref.collection("documents").stream()
        b_data["documents"] = [d.to_dict() async for d in docs_stream]
    except Exception as exc:
        logger.warning("attach_documents_failed", bundle_id=b_data.get("id"), error=str(exc))
        b_data["documents"] = []
    return b_data


async def list_bundles(tenant_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List recent bundles with optional tenant scoping. Returns list of bundle dicts with attached documents."""
    client = _get_firestore_client()

    if client is not None:
        try:
            from google.cloud.firestore import Query

            col = client.collection("bundles")
            query = col
            if tenant_id and tenant_id != "*":
                query = query.where("tenant_id", "==", tenant_id)
            query = query.order_by("created_at", direction=Query.DESCENDING).limit(limit)
            snapshots = await query.get()
            bundles = [doc.to_dict() for doc in snapshots]
            await asyncio.gather(*[_attach_bundle_documents(doc.reference, b) for doc, b in zip(snapshots, bundles)])
            return bundles
        except Exception as exc:
            logger.warning("firestore_list_bundles_order_query_failed", error=str(exc))
            try:
                col = client.collection("bundles")
                query = col
                if tenant_id and tenant_id != "*":
                    query = query.where("tenant_id", "==", tenant_id)
                snapshots = await query.limit(limit).get()
                bundles = [doc.to_dict() for doc in snapshots]
                await asyncio.gather(*[_attach_bundle_documents(doc.reference, b) for doc, b in zip(snapshots, bundles)])
                bundles.sort(key=lambda b: b.get("created_at", ""), reverse=True)
                return bundles
            except Exception as e2:
                logger.error("firestore_list_bundles_failed", error=str(e2))
                return []

    bundles = []
    for b_id, b_data in _IN_MEMORY_BUNDLES.items():
        b = dict(b_data)
        b["documents"] = list(_IN_MEMORY_DOCS.get(b_id, {}).values())
        if not tenant_id or tenant_id == "*" or b.get("tenant_id") == tenant_id:
            bundles.append(b)
    bundles.sort(key=lambda b: b.get("created_at", ""), reverse=True)
    return bundles[:limit]


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


async def delete_evidence_document(bundle_id: str, document_id: str, gate_tokens: int = 0) -> bool:
    """Remove a document's record from its bundle. True when there was one; removing a record that is already gone is not an error.

    ``gate_tokens`` (what the document's upload check cost) is added to the bundle's ``deleted_gate_tokens`` in the SAME write that removes
    the record, and only when there was a record: the figure leaves with the record otherwise, and a repeated delete never counts it twice.
    """
    client = _get_firestore_client()
    now = datetime.now(timezone.utc).isoformat()

    if client is not None:
        from google.cloud.firestore_v1 import Increment

        bundle_ref = client.collection("bundles").document(bundle_id)
        doc_ref = bundle_ref.collection("documents").document(document_id)
        existed = bool((await doc_ref.get()).exists)
        changes: dict[str, Any] = {"updated_at": now}
        if existed and gate_tokens:
            changes["deleted_gate_tokens"] = Increment(gate_tokens)
        batch = client.batch()
        batch.delete(doc_ref)
        batch.update(bundle_ref, changes)
        await batch.commit()
        logger.info("document_deleted_firestore", bundle_id=bundle_id, document_id=document_id)
        return existed

    existed = _IN_MEMORY_DOCS.get(bundle_id, {}).pop(document_id, None) is not None
    if bundle_id in _IN_MEMORY_BUNDLES:
        bundle = _IN_MEMORY_BUNDLES[bundle_id]
        bundle["updated_at"] = now
        if existed and gate_tokens:
            bundle["deleted_gate_tokens"] = int(bundle.get("deleted_gate_tokens") or 0) + gate_tokens
    logger.info("document_deleted_in_memory", bundle_id=bundle_id, document_id=document_id)
    return existed


async def update_document_doc_type(bundle_id: str, document_id: str, doc_type: str) -> None:
    """Update the doc_type of an existing document after classification."""
    client = _get_firestore_client()

    if client is not None:
        doc_ref = client.collection("bundles").document(bundle_id).collection("documents").document(document_id)
        await doc_ref.update({"doc_type": doc_type})
    else:
        if bundle_id in _IN_MEMORY_DOCS and document_id in _IN_MEMORY_DOCS[bundle_id]:
            _IN_MEMORY_DOCS[bundle_id][document_id]["doc_type"] = doc_type


async def update_document_transform_meta_uri(bundle_id: str, document_id: str, transform_meta_uri: str) -> None:
    """Associate a document with its durable preprocessing-transform metadata."""
    client = _get_firestore_client()

    if client is not None:
        doc_ref = client.collection("bundles").document(bundle_id).collection("documents").document(document_id)
        await doc_ref.update({"transform_meta_uri": transform_meta_uri})
    elif bundle_id in _IN_MEMORY_DOCS and document_id in _IN_MEMORY_DOCS[bundle_id]:
        _IN_MEMORY_DOCS[bundle_id][document_id]["transform_meta_uri"] = transform_meta_uri


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


async def set_run_queued(bundle_id: str, run_id: str) -> None:
    """The run record of a run that is waiting for a worker (RUN_DISPATCH=cloudtasks): state QUEUED, stage "queued"."""
    run_state = {
        "kind": "status",
        "bundle_id": bundle_id,
        "run_id": run_id,
        "state": "QUEUED",
        "stage": "queued",
        "progress": 0.02,
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
    bundle_id: str, run_id: str, state: str, progress: float, only_if_state: str | None = None, fence: int | None = None
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

    if fence is not None:
        return await _set_run_state_fenced(bundle_id, run_id, run_state, only_if_state, fence, client)

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


async def _set_run_state_fenced(
    bundle_id: str, run_id: str, run_state: dict[str, Any], only_if_state: str | None, fence: int, client: Any
) -> bool:
    """``set_run_state`` of an execution that holds the bundle's lease: the lease check, the (conditional) write and, for a
    terminal state, the release of the lease are ONE atomic step. ``LeaseLost`` (raised) when the execution no longer owns the
    bundle; the record then stays as the new owner (or the reaper) left it."""
    applied = False

    async def work(transaction: Any) -> None:
        nonlocal applied
        applied = False  # Firestore runs this again on contention: only the attempt that is committed may say "applied"
        if transaction is None:  # demo mode
            record = _IN_MEMORY_RUNS.get(f"{bundle_id}:{run_id}")
            if only_if_state is not None and (record is None or record.get("state") != only_if_state):
                return
            if record is not None:
                record.update(run_state)
            else:
                _IN_MEMORY_RUNS[f"{bundle_id}:{run_id}"] = run_state
            applied = True
            return
        run_ref = client.collection("bundles").document(bundle_id).collection("runs").document(run_id)
        snapshot = await run_ref.get(transaction=transaction)
        stored = snapshot.to_dict() if snapshot.exists else None
        if only_if_state is not None and (stored is None or stored.get("state") != only_if_state):
            return
        transaction.set(run_ref, run_state, merge=True)
        applied = True

    terminal = run_state.get("state") in ("COMPLETE", "ERROR")
    await leases.fenced_transaction(bundle_id, run_id, fence, work, release_after=terminal)
    return applied


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
        "valuation": ctx.get("valuation"),
        "reference_data": ctx.get("reference_data"),
        "corrections": ctx.get("corrections", []),
        "run_mode": ctx.get("mode"),
        "token_usage": ctx.get("token_usage"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    client = _get_firestore_client()
    already_exists = f"iteration {iteration_num} already exists for bundle {bundle_id}"
    fence = ctx.get("fence")
    run_id = ctx.get("run_id")

    if client is not None:
        from google.api_core.exceptions import AlreadyExists

        bundle_ref = client.collection("bundles").document(bundle_id)
        iter_ref = bundle_ref.collection("iterations").document(str(iteration_num))
        bundle_update = {
            "status": iteration_data["status"],
            "current_iteration": iteration_num,
            "updated_at": iteration_data["created_at"],
        }
        try:
            if fence is not None and run_id:
                # the lease check and both writes are ONE transaction: an executor that lost its lease cannot write
                async def work(transaction: Any) -> None:
                    transaction.create(iter_ref, iteration_data)  # create-only: an iteration is immutable and never overwritten
                    transaction.update(bundle_ref, bundle_update)

                await leases.fenced_transaction(bundle_id, run_id, fence, work)
            else:
                await iter_ref.create(iteration_data)  # create-only: an iteration is immutable and never overwritten
                await bundle_ref.update(bundle_update)
        except AlreadyExists as exc:
            raise PipelineError(already_exists, detail={"bundle_id": bundle_id, "iteration": iteration_num}) from exc
    else:
        async def write_memory(_transaction: Any) -> None:
            if bundle_id not in _IN_MEMORY_ITERATIONS:
                _IN_MEMORY_ITERATIONS[bundle_id] = []
            if any(existing.get("iteration") == iteration_num for existing in _IN_MEMORY_ITERATIONS[bundle_id]):
                raise PipelineError(already_exists, detail={"bundle_id": bundle_id, "iteration": iteration_num})
            _IN_MEMORY_ITERATIONS[bundle_id].append(iteration_data)
            if bundle_id in _IN_MEMORY_BUNDLES:
                _IN_MEMORY_BUNDLES[bundle_id]["status"] = iteration_data["status"]
                _IN_MEMORY_BUNDLES[bundle_id]["current_iteration"] = iteration_num

        if fence is not None and run_id:
            await leases.fenced_transaction(bundle_id, run_id, fence, write_memory)
        else:
            await write_memory(None)

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


async def get_iteration(bundle_id: str, iteration: int) -> dict[str, Any] | None:
    """One AssessmentIteration by number; None if there is none."""
    client = _get_firestore_client()

    if client is not None:
        ref = client.collection("bundles").document(bundle_id).collection("iterations").document(str(iteration))
        snap = await ref.get()
        return snap.to_dict() if snap.exists else None

    return next((it for it in _IN_MEMORY_ITERATIONS.get(bundle_id, []) if it.get("iteration") == iteration), None)


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


async def save_extractions(
    bundle_id: str,
    iteration: int,
    extractions: list[dict[str, Any]],
    extraction_source: str | None = None,
    derived_from: int | None = None,
    pages_iteration: int | None = None,
    page_plans: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Persist per-document extraction JSON for an iteration: exactly what the model read, never the corrected view.

    ``page_plans`` ({document id: which pages were read, skipped, or left out by the cap}) is stored with it: it says what the model
    was NOT shown, and a recompute, which reads no document, still has to say so.

    ``extraction_source`` ("live" / "fixture") travels with it so a recompute (which reuses this record) knows where the
    data came from; ``derived_from`` is set on a copy a recompute made, naming the iteration that was really extracted;
    ``pages_iteration`` names the assessment whose page images the model was shown (a recompute shows none of its own: it
    carries the number of the assessment it copied), None when no page image was kept.
    """
    client = _get_firestore_client()

    data = {
        "bundle_id": bundle_id,
        "iteration": iteration,
        "extractions": extractions,
        "extraction_source": extraction_source,
        "derived_from": derived_from,
        "pages_iteration": pages_iteration,
        "page_plans": page_plans,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if client is not None:
        ref = client.collection("bundles").document(bundle_id).collection("extractions").document(str(iteration))
        await ref.set(data)
    else:
        if bundle_id not in _IN_MEMORY_EXTRACTIONS:
            _IN_MEMORY_EXTRACTIONS[bundle_id] = {}
        _IN_MEMORY_EXTRACTIONS[bundle_id][iteration] = data


async def get_daily_tokens(day: str) -> int:
    """Model tokens the service spent on this UTC day (``YYYYMMDD``); 0 when nothing was counted."""
    client = _get_firestore_client()

    if client is not None:
        snap = await client.collection("token_budget").document(day).get()
        return int((snap.to_dict() or {}).get("tokens", 0)) if snap.exists else 0

    return _IN_MEMORY_DAILY_TOKENS.get(day, 0)


async def add_daily_tokens(day: str, tokens: int) -> None:
    """Add ``tokens`` to this day's count, atomically (Firestore ``Increment``: concurrent runs on any instance add up, none is lost).
    The document carries ``expires_at`` for a TTL policy (infra/firestore/setup_ttl.sh): a day's counter is not read again after it."""
    client = _get_firestore_client()

    if client is not None:
        from google.cloud.firestore_v1 import Increment

        expires = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc) + timedelta(days=3)
        await client.collection("token_budget").document(day).set(
            {"tokens": Increment(tokens), "updated_at": datetime.now(timezone.utc).isoformat(), "expires_at": expires}, merge=True
        )
    else:
        _IN_MEMORY_DAILY_TOKENS[day] = _IN_MEMORY_DAILY_TOKENS.get(day, 0) + tokens


async def save_usage(bundle_id: str, run_id: str, record: dict[str, Any]) -> None:
    """Keep what one run's model calls cost, for a completed run (it has an iteration) and for a failed one (it has none): a failed
    run spends tokens too. One record per run, keyed by the run id."""
    client = _get_firestore_client()
    data = {**record, "bundle_id": bundle_id, "run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat()}

    if client is not None:
        await client.collection("bundles").document(bundle_id).collection("usage").document(run_id).set(data)
    else:
        _IN_MEMORY_USAGE.setdefault(bundle_id, {})[run_id] = data


async def list_usage(bundle_id: str) -> list[dict[str, Any]]:
    """Every run's usage record of a bundle, oldest first."""
    client = _get_firestore_client()

    if client is not None:
        records = [snap.to_dict() async for snap in client.collection("bundles").document(bundle_id).collection("usage").stream()]
    else:
        records = list(_IN_MEMORY_USAGE.get(bundle_id, {}).values())
    return sorted((r for r in records if r), key=lambda r: str(r.get("created_at", "")))


async def get_cached_answer(bundle_id: str, fingerprint: str) -> dict[str, Any] | None:
    """The model's answer stored for this bundle under this request fingerprint (agents/extraction.py), or None."""
    client = _get_firestore_client()

    if client is not None:
        ref = client.collection("bundles").document(bundle_id).collection("extraction_cache").document(fingerprint)
        snap = await ref.get()
        entry = snap.to_dict() if snap.exists else None
    else:
        entry = _IN_MEMORY_EXTRACTION_CACHE.get(bundle_id, {}).get(fingerprint)
    expires = (entry or {}).get("expires_at")
    if isinstance(expires, datetime) and expires <= datetime.now(timezone.utc):
        return None  # past its life: Firestore's TTL deletes it within a day or two, and until then it is not used
    return entry


async def put_cached_answer(bundle_id: str, fingerprint: str, entry: dict[str, Any]) -> None:
    """Keep the model's answer for this bundle under this request fingerprint. Scoped to the bundle: a file uploaded to another
    bundle is read again, so no bundle's document values are ever served to another."""
    client = _get_firestore_client()
    now = datetime.now(timezone.utc)
    data = {
        **entry, "bundle_id": bundle_id, "fingerprint": fingerprint, "created_at": now.isoformat(),
        "expires_at": now + timedelta(days=settings.extraction_cache_ttl_days),  # for the TTL policy (infra/firestore/setup_ttl.sh)
    }

    if client is not None:
        ref = client.collection("bundles").document(bundle_id).collection("extraction_cache").document(fingerprint)
        await ref.set(data)
    else:
        _IN_MEMORY_EXTRACTION_CACHE.setdefault(bundle_id, {})[fingerprint] = data


async def delete_cached_answers(bundle_id: str, document_id: str) -> int:
    """Remove the model's answers kept for one document of a bundle (the extraction cache stores the document_id with each).
    Returns how many were removed."""
    client = _get_firestore_client()

    if client is not None:
        cache = client.collection("bundles").document(bundle_id).collection("extraction_cache")
        removed = 0
        async for snap in cache.where("document_id", "==", document_id).stream():
            await snap.reference.delete()
            removed += 1
        return removed

    entries = _IN_MEMORY_EXTRACTION_CACHE.get(bundle_id, {})
    stale = [fingerprint for fingerprint, entry in entries.items() if entry.get("document_id") == document_id]
    for fingerprint in stale:
        del entries[fingerprint]
    return len(stale)


async def get_extraction_record(bundle_id: str, iteration: int) -> dict[str, Any] | None:
    """The stored extraction record of one iteration (``extractions``, ``extraction_source``, ...); None if there is none."""
    client = _get_firestore_client()

    if client is not None:
        ref = client.collection("bundles").document(bundle_id).collection("extractions").document(str(iteration))
        snap = await ref.get()
        return snap.to_dict() if snap.exists else None

    return _IN_MEMORY_EXTRACTIONS.get(bundle_id, {}).get(iteration)


async def get_extractions(bundle_id: str, iteration: int | None = None) -> list[dict[str, Any]]:
    """Get per-document extraction JSON for a bundle (the latest iteration's when ``iteration`` is None)."""
    if iteration is None:
        latest = await latest_iteration(bundle_id)
        iteration = latest.get("iteration", 1) if latest else 1

    record = await get_extraction_record(bundle_id, iteration)
    return list(record.get("extractions", [])) if record else []


# ---------------------------------------------------------------------------
# User Identity, Commercial Registration & Audit Persistence
# ---------------------------------------------------------------------------

_IN_MEMORY_USERS: dict[str, dict[str, Any]] = {}
_IN_MEMORY_USER_AUDIT: dict[str, list[dict[str, Any]]] = {}


async def get_user(email: str) -> dict[str, Any] | None:
    """Retrieve registered commercial user profile by corporate email."""
    normalized_email = email.strip().lower()
    client = _get_firestore_client()
    if client is not None:
        ref = client.collection("users").document(normalized_email)
        snap = await ref.get()
        return snap.to_dict() if snap.exists else None
    return _IN_MEMORY_USERS.get(normalized_email)


async def create_user(user_data: dict[str, Any]) -> dict[str, Any]:
    """Persist new commercial user registration with audit metadata."""
    email = user_data["email"].strip().lower()
    client = _get_firestore_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        **user_data,
        "email": email,
        "created_at": user_data.get("created_at") or now_iso,
        "last_login_at": user_data.get("last_login_at") or now_iso,
        "status": user_data.get("status", "ACTIVE"),
    }
    if client is not None:
        ref = client.collection("users").document(email)
        await ref.set(record)
    else:
        _IN_MEMORY_USERS[email] = record
    return record


async def update_user(email: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Update existing user record (e.g. last_login_at, role, profile details)."""
    normalized_email = email.strip().lower()
    client = _get_firestore_client()
    if client is not None:
        ref = client.collection("users").document(normalized_email)
        snap = await ref.get()
        if not snap.exists:
            return None
        current = snap.to_dict()
        current.update(updates)
        await ref.set(current)
        return current
    if normalized_email in _IN_MEMORY_USERS:
        _IN_MEMORY_USERS[normalized_email].update(updates)
        return _IN_MEMORY_USERS[normalized_email]
    return None


async def record_user_audit(email: str, action: str, details: dict[str, Any] | None = None) -> None:
    """Append a tamper-evident audit record for user login, signup, or security event."""
    normalized_email = email.strip().lower()
    audit_id = f"aud-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    audit_entry = {
        "event_id": audit_id,
        "email": normalized_email,
        "action": action,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    client = _get_firestore_client()
    if client is not None:
        ref = client.collection("users").document(normalized_email).collection("audit").document(audit_id)
        await ref.set(audit_entry)
    else:
        if normalized_email not in _IN_MEMORY_USER_AUDIT:
            _IN_MEMORY_USER_AUDIT[normalized_email] = []
        _IN_MEMORY_USER_AUDIT[normalized_email].append(audit_entry)
