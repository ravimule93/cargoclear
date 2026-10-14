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

Run lifecycle (audit events are written by this module, not by a pipeline stage):
  claim -> ANALYSIS_STARTED -> stages 1-6 -> "finalize" -> iteration persisted -> ASSESSMENT_COMPLETED -> run COMPLETE
  Any failure -> ANALYSIS_FAILED (best effort) -> run ERROR. ASSESSMENT_COMPLETED is only ever written
  for an iteration that was persisted.

Run modes: ``full`` (analyze) and ``reassess`` read every document; ``recompute`` reuses the extraction stored with the
latest assessment (no preprocessing, no model call) and re-runs the checks, which is how an agent's corrections take effect
quickly. In EVERY mode the corrections of the authorised agent (services/corrections.py) are laid over the extraction right
after the ``extract`` stage, so a reassessment never drops them and the iteration lists the ones it used.

Who may run an assessment: the bundle's LEASE (repo/leases.py), claimed atomically across API instances. ``start_run`` reaps
a dead run, claims the lease (a live one is a 409), picks the iteration number, writes the run record and either spawns the
pipeline as a background task in this process (``RUN_DISPATCH=local``) or enqueues a Cloud Task (``cloudtasks``: the lease is
QUEUED until a worker request calls ``execute_queued``, which acquires it and runs the pipeline inside that request). A run
holds the lease with a FENCE; its critical writes (the iteration, the terminal state) are transactions that check the fence,
so an executor that was paused past its lease and wakes up cannot write. The in-process lock stays as a cheap first line.
(Iteration documents are create-only, a durable backstop.)

How a run proves it is alive: a heartbeat task touches the run record and extends the lease every ``RUN_HEARTBEAT_SECONDS``.
A lease that expired (or a RUNNING record untouched for ``RUN_STALE_AFTER_SECONDS``) belongs to a dead executor;
``reap_stale`` marks the run ERROR and audits it once, wherever it runs (``start_run``, the SSE poll loop). A dead executor of
a dispatched run is instead taken over when Cloud Tasks delivers the task again (a new fence; the pipeline restarts).

How a run ends: the whole pipeline runs under ``RUN_TIMEOUT_SECONDS``. Cancellation (server shutdown) is recorded
(ERROR + ANALYSIS_FAILED, bounded to a few seconds) and then re-raised. Whatever a client or the audit log is told
comes from ``public_error``: raw exception text (paths, bucket names, document content) goes to the logs only.
"""

from __future__ import annotations

import asyncio
import functools
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.config import settings
from app.domain.status import Status, resolve_status
from app.gateway.dispatch import dispatch
from app.gateway.errors import (
    INTERRUPTED_MESSAGE,
    TIMEOUT_MESSAGE,
    ConflictError,
    PipelineError,
    RunInterruptedError,
    RunTimeoutError,
    ServiceBusyError,
    ValidationError,
    public_error,
)
from app.domain.schemas import ExtractedDocument
from app.repo import firestore, leases
from app.services import audit, corrections, run_events, run_queue, signing, storage
from app.services.engines import get_engine

logger = structlog.get_logger(__name__)

__all__ = ["public_error", "RunInterruptedError", "RunTimeoutError"]  # re-exported: callers (and tests) reach them through this module

PIPELINE_STAGES = [
    "preprocess",
    "extract",
    "discrepancy",
    "ground",
    "confidence",
    "synthesize",
]

# Progress fractions per stage ("finalize" is run by the orchestrator itself, after the stages)
_STAGE_PROGRESS = {
    "preprocess": 0.15,
    "extract": 0.40,
    "discrepancy": 0.60,
    "ground": 0.75,
    "confidence": 0.85,
    "synthesize": 0.95,
    "finalize": 0.98,
}

# Strong references to running asyncio background tasks to prevent GC garbage collection
_RUNNING_TASKS: set[asyncio.Task[Any]] = set()

# Per-bundle locks (this process is the only instance). _START_LOCKS serialise the claim in start_run;
# _REAP_LOCKS make sure two reapers (a start and the SSE poll loop) write ONE ANALYSIS_FAILED for a dead run.
# Lock order is always start -> reap, never the reverse.
_START_LOCKS: dict[str, asyncio.Lock] = {}
_REAP_LOCKS: dict[str, asyncio.Lock] = {}

# Claims between "the MAX_CONCURRENT_RUNS check passed" and "the task is registered in _RUNNING_TASKS": they count
# against the cap, so that starts on DIFFERENT bundles (which hold different locks) cannot overshoot it together.
_starting_runs = 0

# Set by ``shutdown``: a dispatched run that is cancelled by it is NOT failed (its lease expires and Cloud Tasks delivers the
# task again, which takes the run over); an ordinary cancellation still ends the run in ERROR.
_SHUTTING_DOWN = False

# Upper bound for the best-effort "run failed" bookkeeping (run state + audit), also when the task is being cancelled
_CLEANUP_TIMEOUT_SECONDS = 5.0


def _live_runs() -> int:
    """Analyses running or being claimed right now, across all bundles."""
    return sum(1 for task in _RUNNING_TASKS if not task.done()) + _starting_runs


def _lock(registry: dict[str, asyncio.Lock], bundle_id: str) -> asyncio.Lock:
    lock = registry.get(bundle_id)
    if lock is None:
        lock = registry[bundle_id] = asyncio.Lock()
    return lock


async def _ensure_claim(bundle_id: str, run_id: str, fence: int | None = None) -> None:
    """Fencing: raise unless this run still owns the bundle (its lease, when it has a fence) and its record is RUNNING.

    A run that was reaped while merely slow, taken over by a newer executor, or superseded must not write another stage,
    an iteration or an audit event: the bundle may already belong to somebody else.
    """
    if fence is not None:
        try:
            await leases.verify(bundle_id, run_id, fence)
        except leases.LeaseLost as exc:
            raise RunInterruptedError("the run lost its claim") from exc
    record = await firestore.get_run_state(bundle_id, run_id)
    if record.get("state") != "RUNNING":
        raise RunInterruptedError("the run lost its claim")


async def _set_stage(bundle_id: str, run_id: str, stage: str, progress: float) -> None:
    """Write the RUNNING record and wake the streams that watch this bundle."""
    await firestore.set_run_stage(bundle_id, run_id, stage=stage, progress=progress)
    run_events.notify(bundle_id)


def resolve_final_status(ctx: dict[str, Any]) -> str:
    """Synthesize final status using the 4-status precedence rule."""
    candidates: list[Status] = []
    if ctx.get("missing_evidence"):
        candidates.append(Status.MISSING_EVIDENCE)
    if ctx.get("math_status") == Status.MATERIAL_CONTRADICTION:
        candidates.append(Status.MATERIAL_CONTRADICTION)
    if ctx.get("grounding_ambiguous") or ctx.get("math_status") == Status.SPECIALIST_REVIEW_REQUIRED:
        candidates.append(Status.SPECIALIST_REVIEW_REQUIRED)
    if ctx.get("confidence", {}).get("action") in ("AUTO_FLAG", "INTERACTIVE_REVIEW", "MANUAL_ENTRY"):
        candidates.append(Status.SPECIALIST_REVIEW_REQUIRED)
    if ctx.get("force_status"):
        candidates.append(Status(ctx["force_status"]))

    final_status = resolve_status(candidates)
    return final_status.value



def _age_seconds(run: dict[str, Any]) -> float | None:
    """Seconds since the run record was last touched; None if it carries no usable timestamp."""
    stamp = run.get("updated_at")
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds()


def _is_stale(run: dict[str, Any]) -> bool:
    """A record that cannot show a recent heartbeat (older than the window, or no usable timestamp) is dead."""
    age = _age_seconds(run)
    return age is None or age > settings.run_stale_after_seconds


async def _started_event_of(bundle_id: str, run_id: str) -> tuple[int, str]:
    """(iteration, mode) of a run, read back from its ANALYSIS_STARTED audit event; (0, "unknown") if it has none."""
    try:
        events = await audit.list_audit_events(bundle_id)
    except Exception:  # noqa: BLE001 - reaping must not depend on the audit read working
        return 0, "unknown"
    for event in reversed(events):
        payload = event.get("payload") or {}
        if event.get("event_type") == "ANALYSIS_STARTED" and payload.get("run_id") == run_id:
            return int(event.get("iteration", 0)), str(payload.get("mode", "unknown"))
    return 0, "unknown"


async def _mark_dead(bundle_id: str, run_id: str, *, iteration: int, mode: str, stage: str | None) -> None:
    """The run's executor is gone: ERROR on its record, the SSE streams woken, one ANALYSIS_FAILED in the audit chain."""
    error = RunInterruptedError(INTERRUPTED_MESSAGE)
    logger.warning("run_reaped", bundle_id=bundle_id, run_id=run_id, stage=stage)
    await firestore.set_run_error(bundle_id, run_id, error=public_error(error, run_id)["message"])
    run_events.notify(bundle_id)
    await _record_failure(
        bundle_id=bundle_id, run_id=run_id, iteration=iteration, mode=mode, stage=stage, exc=error, reason="interrupted"
    )


async def reap_stale(bundle_id: str) -> bool:
    """Mark a dead run ERROR and audit it once. Returns True if a run was reaped.

    Dead = its LEASE has expired (a queued run nobody picked up, or an executor that stopped heartbeating; the expired lease
    is deleted in the same atomic step, so exactly one caller on any instance gets to reap it), or its record is RUNNING and
    untouched for ``RUN_STALE_AFTER_SECONDS`` (a heartbeat touches both, so the two agree; the record check also covers a run
    started before leases existed). Idempotent: once the record is ERROR, later calls do nothing.
    """
    async with _lock(_REAP_LOCKS, bundle_id):
        run = await firestore.get_run_state(bundle_id)

        lease = await leases.reap_expired(bundle_id)
        if lease is not None:
            same_record = run.get("run_id") == lease.run_id
            await _mark_dead(
                bundle_id, lease.run_id, iteration=lease.iteration, mode=lease.mode,
                stage=run.get("stage") if same_record else None,
            )
            return True

        if run.get("state") != "RUNNING" or not _is_stale(run):
            return False
        run_id = str(run.get("run_id") or "unknown")
        await leases.release(bundle_id, run_id)  # a live-looking lease must not outlive its dead run
        iteration, mode = await _started_event_of(bundle_id, run_id)
        await _mark_dead(bundle_id, run_id, iteration=iteration, mode=mode, stage=run.get("stage"))
        return True


async def _claim(bundle_id: str, run_id: str, mode: str, queued: bool) -> leases.Lease:
    """Claim the bundle's lease for the run (atomic across instances); 409 when a live run holds it."""
    try:
        claim = await leases.claim(
            bundle_id, run_id=run_id, mode=mode,
            state=leases.QUEUED if queued else leases.RUNNING, owner=None if queued else leases.INSTANCE_ID,
        )
    except leases.LeaseHeld as held:
        raise ConflictError(
            f"An assessment run is already in progress for bundle '{bundle_id}'.", detail={"run_id": held.lease.run_id}
        ) from held
    if claim.superseded is not None:  # an expired lease nobody had reaped yet: its run is dead
        await _mark_dead(
            bundle_id, claim.superseded.run_id, iteration=claim.superseded.iteration, mode=claim.superseded.mode, stage=None
        )
    return claim.lease


async def _plan(
    bundle_id: str, bundle: dict[str, Any], documents: list[dict[str, Any]], mode: str
) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
    """(iteration number, previous iteration, stored extraction to reuse for a recompute); 409 when a recompute has none."""
    prev_iteration = await firestore.latest_iteration(bundle_id)
    base_extraction = await _recompute_base(bundle_id, documents, prev_iteration) if mode == "recompute" else None
    iteration = max(
        bundle.get("current_iteration", 0) or 0,
        prev_iteration.get("iteration", 0) if prev_iteration else 0,
    ) + 1
    return iteration, prev_iteration, base_extraction


async def _release_quietly(bundle_id: str, run_id: str, fence: int | None) -> None:
    try:
        await leases.release(bundle_id, run_id, fence)
    except Exception as exc:  # noqa: BLE001 - the lease expires by itself; never mask the error being handled
        logger.warning("lease_release_failed", bundle_id=bundle_id, run_id=run_id, error_type=type(exc).__name__)


async def _expire_quietly(bundle_id: str, run_id: str, fence: int) -> None:
    """Make this execution's lease count as expired now, so that the next delivery of the task takes the run over."""
    try:
        await leases.expire(bundle_id, run_id, fence)
    except Exception as exc:  # noqa: BLE001 - the lease expires by itself within RUN_STALE_AFTER_SECONDS
        logger.warning("lease_expire_failed", bundle_id=bundle_id, run_id=run_id, error_type=type(exc).__name__)


async def start_run(bundle_id: str, mode: str = "full") -> str:
    """Claim the bundle and start the assessment pipeline (a background task here, or a Cloud Task for a worker).

    Enforces, atomically per bundle across instances (see the module docstring):
      - Bundle empty check: 0 documents -> 422 ValidationError.
      - In-flight guard: a live run (its lease is held, or its record is RUNNING and still heartbeating) -> 409
        ConflictError. A dead one is reaped first, so it never blocks.
      - A recompute needs a previous assessment over the same documents with a stored extraction (else 409).
    """
    async with _lock(_START_LOCKS, bundle_id):
        bundle = await firestore.get_bundle(bundle_id) or {}  # an unknown bundle has no documents: the 422 below
        documents = bundle.get("documents", [])

        # T2.4c: Bundle with zero documents returns 422
        if not documents:
            raise ValidationError("Cannot analyze an empty bundle. Upload trade documents first.")

        # T2.4b: In-flight guard for active runs (after reaping any run whose lease expired or whose heartbeat stopped)
        await reap_stale(bundle_id)
        latest_run = await firestore.get_run_state(bundle_id)
        if latest_run.get("state") == "RUNNING":  # (a live run holds the lease too; this also covers records from before leases)
            raise ConflictError(
                f"An assessment run is already in progress for bundle '{bundle_id}'.",
                detail={"run_id": latest_run.get("run_id")},
            )

        # MAX_CONCURRENT_RUNS: the runs of THIS process (RUN_DISPATCH=local). Refuse before anything is claimed. Reserve the
        # slot in the same synchronous step as the check; the reservation is released once the task counts as running (or the
        # claim failed). With cloudtasks the service-wide cap is the queue's max-concurrent-dispatches.
        queued = settings.run_dispatch == "cloudtasks"
        cap = settings.max_concurrent_runs
        if not queued and cap > 0 and _live_runs() >= cap:
            raise ServiceBusyError(
                "The service is busy analysing other bundles. Try again shortly.",
                detail={"max_concurrent_runs": cap},
                headers={"Retry-After": "5"},
            )
        global _starting_runs
        _starting_runs += 1
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        lease: leases.Lease | None = None
        try:
            lease = await _claim(bundle_id, run_id, mode, queued)
            iteration, prev_iteration, base_extraction = await _plan(bundle_id, bundle, documents, mode)
            lease = await leases.update(bundle_id, run_id, lease.fence, iteration=iteration)

            if queued:
                # The run record says QUEUED until a worker picks it up; if the queue refuses it, nothing stays claimed
                await firestore.set_run_queued(bundle_id, run_id)
                run_events.notify(bundle_id)
                try:
                    await run_queue.enqueue(bundle_id, run_id)
                except BaseException as exc:
                    await firestore.set_run_error(bundle_id, run_id, error=public_error(exc, run_id)["message"])
                    run_events.notify(bundle_id)
                    raise
            else:
                ctx: dict[str, Any] = {
                    "bundle_id": bundle_id,
                    "run_id": run_id,
                    "mode": mode,
                    "iteration": iteration,
                    "fence": lease.fence,
                    "destination_country": bundle.get("destination_country", "SG"),
                    "documents": documents,
                    "previous_iteration": prev_iteration,
                }
                if base_extraction is not None:
                    ctx["base_extraction"] = base_extraction

                # Initialize run record in Firestore / in-memory store: from here on the claim is visible to everybody
                await _set_stage(bundle_id, run_id, "initializing", 0.05)

                # T2.4a: Maintain strong reference to asyncio task
                task = asyncio.create_task(_execute_pipeline(ctx), name=f"run-{run_id}")
                _RUNNING_TASKS.add(task)
                task.add_done_callback(_RUNNING_TASKS.discard)
        except BaseException:
            if lease is not None:
                await _release_quietly(bundle_id, run_id, lease.fence)
            raise
        finally:
            _starting_runs -= 1

    return run_id


async def execute_queued(bundle_id: str, run_id: str) -> str:
    """A worker request for a dispatched run: acquire its lease and run the pipeline to the end, inside this call.

    Returns what the worker endpoint answers Cloud Tasks with: ``"done"`` (the run ended: complete OR failed: a failure is
    recorded on the run, and retrying a deterministic failure helps nobody), ``"busy"`` (another executor is running it: a
    duplicate delivery) or ``"obsolete"`` (the run no longer owns the bundle: it was reaped or superseded). An executor that
    dies mid-run answers nothing; the next delivery finds its lease expired and TAKES THE RUN OVER (a new fence, a restart).
    """
    try:
        lease, taken_over = await leases.acquire(bundle_id, run_id)
    except leases.LeaseLost:
        logger.info("run_task_obsolete", bundle_id=bundle_id, run_id=run_id)
        return "obsolete"
    except leases.LeaseHeld:
        logger.info("run_task_busy", bundle_id=bundle_id, run_id=run_id)
        return "busy"

    if taken_over:
        logger.warning("run_taken_over", bundle_id=bundle_id, run_id=run_id, fence=lease.fence)
    failure: dict[str, Any] = {"bundle_id": bundle_id, "run_id": run_id, "iteration": lease.iteration, "mode": lease.mode, "fence": lease.fence}
    try:
        await _set_stage(bundle_id, run_id, "initializing", 0.05)  # QUEUED -> RUNNING on the run record: what clients watch
        bundle = await firestore.get_bundle(bundle_id) or {}
        documents = bundle.get("documents", [])
        ctx: dict[str, Any] = {
            "bundle_id": bundle_id,
            "run_id": run_id,
            "mode": lease.mode,
            "iteration": lease.iteration,
            "fence": lease.fence,
            "dispatched": True,
            "destination_country": bundle.get("destination_country", "SG"),
            "documents": documents,
            "previous_iteration": await firestore.latest_iteration(bundle_id),
        }
        if lease.mode == "recompute":
            ctx["base_extraction"] = await _recompute_base(bundle_id, documents, ctx["previous_iteration"])
    except ConflictError as exc:  # e.g. a document was uploaded while the recompute waited in the queue: deterministic, final
        await _fail_run(**failure, stage=None, exc=exc)
        return "done"
    except Exception:
        # Not the run's fault (a store that hiccuped before any stage ran): answer an error so that Cloud Tasks delivers the task
        # again, and let the next delivery take the run over at once instead of waiting out the lease (and spending attempts on
        # "busy" answers for an executor that is already gone).
        await _expire_quietly(bundle_id, run_id, lease.fence)
        raise

    task = asyncio.create_task(_execute_pipeline(ctx), name=f"run-{run_id}")
    _RUNNING_TASKS.add(task)
    task.add_done_callback(_RUNNING_TASKS.discard)
    await asyncio.shield(task)  # this request returns when the run has ended (or the request itself is cancelled)
    return "done"


async def _recompute_base(
    bundle_id: str, documents: list[dict[str, Any]], prev_iteration: dict[str, Any] | None
) -> dict[str, Any]:
    """The stored extraction a recompute reuses: {iteration, extractions, extraction_source, data_source}; 409 if there is none.

    It is only valid for the documents it was extracted from, so a bundle that gained a document since needs a reassessment.
    """
    detail = {"bundle_id": bundle_id}
    if prev_iteration is None:
        raise ConflictError("Run the analysis first: there is nothing to recompute yet.", detail=detail)
    iteration = int(prev_iteration.get("iteration", 0))
    analysed = {d for d in prev_iteration.get("documents", []) if d}
    current = {d.get("document_id") for d in documents if d.get("document_id")}
    if analysed != current:
        raise ConflictError(
            "The documents changed since the last analysis. Use Reassess, which reads them.",
            detail={**detail, "iteration": iteration},
        )
    record = await firestore.get_extraction_record(bundle_id, iteration)
    if not record or not record.get("extractions"):
        raise ConflictError(
            "The last assessment has no stored extraction to reuse. Use Reassess.", detail={**detail, "iteration": iteration}
        )
    return {
        "iteration": iteration,
        "extractions": record["extractions"],
        "extraction_source": record.get("extraction_source") or _source_of(prev_iteration.get("data_source")),
        "pages_iteration": record.get("pages_iteration"),
    }


def _source_of(data_source: Any) -> str | None:
    """The extraction source an older record (stored without one) most likely had, from its iteration's data_source."""
    return data_source if data_source in ("live", "fixture") else None


async def _reuse_extraction(ctx: dict[str, Any]) -> None:
    """The ``extract`` stage of a recompute: the previous extraction, as the model read it, becomes this run's extraction.

    A copy is stored under the new iteration number (so the evidence view of any iteration finds its extraction) and says
    which iteration it really came from.
    """
    base = ctx.pop("base_extraction")
    raw = base["extractions"]
    ctx["extracted"] = [ExtractedDocument.model_validate(doc) for doc in raw]
    source = base.get("extraction_source")
    if source:
        ctx["extraction_source"] = source
    ctx["extraction_warnings"] = []
    ctx["extraction_stats"] = []
    ctx["processed_pages"] = []
    ctx["transform_meta"] = []
    ctx["pages_iteration"] = base.get("pages_iteration")  # a recompute shows the model nothing: its pages are the ones it copied
    await firestore.save_extractions(
        ctx["bundle_id"], ctx["iteration"], raw, extraction_source=source, derived_from=base["iteration"],
        pages_iteration=base.get("pages_iteration"),
    )


async def shutdown(timeout: float = 5.0) -> None:
    """Cancel every running pipeline and wait (up to ``timeout`` s) for their failure bookkeeping to finish.

    A dispatched run (``RUN_DISPATCH=cloudtasks``) is only stopped, not failed: its lease expires and Cloud Tasks delivers the
    task again, which takes the run over."""
    global _SHUTTING_DOWN
    _SHUTTING_DOWN = True
    tasks = [task for task in _RUNNING_TASKS if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            logger.error("shutdown_runs_still_running", count=len(pending))


async def _preprocess_documents(ctx: dict[str, Any]) -> None:
    """Download and preprocess every document in the bundle (T2.4d).

    In demo mode a document that cannot be processed is skipped with a warning (the offline extractor
    only needs filenames). In live mode it is fatal: continuing would silently analyse a partial bundle.
    """
    bundle_id = ctx["bundle_id"]
    all_processed_pages: list[dict[str, Any]] = []
    all_transform_meta: list[dict[str, Any]] = []

    for doc in ctx.get("documents", []):
        doc_id = doc.get("document_id")
        if not doc_id:
            continue
        try:
            raw_bytes = await storage.download_raw(bundle_id, doc_id)
            sub_ctx = {
                "raw_bytes": raw_bytes,
                "bundle_id": bundle_id,
                "document_id": doc_id,
            }
            sub_res = await dispatch("preprocess", sub_ctx)
            transform_meta = sub_res.get("transform_meta", [])
            await storage.upload_processed_artifacts(bundle_id, doc_id, sub_res.get("processed_artifacts", []))
            if settings.persist_processed_pages:
                # what the model is about to be shown, kept: "what did it see" must be answerable afterwards
                uris = await storage.upload_processed_pages(
                    bundle_id, doc_id, sub_res.get("processed_pages", []), ctx.get("iteration")
                )
                if uris:
                    ctx["pages_iteration"] = ctx.get("iteration")  # recorded with the extraction: which assessment these pages belong to
                for entry in transform_meta:
                    uri = uris.get(entry.get("source_page", entry.get("page")))
                    if uri:
                        entry["processed_uri"] = uri
            transform_meta_uri = await storage.upload_transform_meta(bundle_id, doc_id, transform_meta)
            await firestore.update_document_transform_meta_uri(bundle_id, doc_id, transform_meta_uri)
            doc["transform_meta_uri"] = transform_meta_uri
            all_processed_pages.extend(sub_res.get("processed_pages", []))
            all_transform_meta.extend(transform_meta)
        except PipelineError:
            # A preprocessing stage that explicitly reports an unrecoverable
            # compliance failure must fail the run in every mode.  Demo mode
            # may tolerate an unavailable optional rasterizer, but it must not
            # claim to have created a required split artifact when it has not.
            raise
        except Exception as exc:
            if settings.app_mode == "live":
                # the class name only: the text of the exception can carry paths or content
                raise PipelineError(
                    f"Preprocessing failed for document {doc_id}: {type(exc).__name__}",
                    detail={"bundle_id": bundle_id, "document_id": doc_id},
                ) from exc
            logger.warning("preprocess_document_failed", bundle_id=bundle_id, doc_id=doc_id, error=str(exc))

    ctx["processed_pages"] = all_processed_pages
    ctx["transform_meta"] = all_transform_meta


async def _record_failure(
    *,
    bundle_id: str,
    run_id: str,
    iteration: int,
    mode: str,
    stage: str | None,
    exc: BaseException,
    reason: str | None = None,
) -> None:
    """Best-effort ANALYSIS_FAILED audit event; an audit failure must never mask the original error.

    The payload is public: ``{run_id, mode, stage, error_type, code, message}`` (plus ``reason`` for a cancelled,
    timed-out or interrupted run). ``message`` comes from ``public_error``, never from the raw exception text.
    """
    public = public_error(exc, run_id)
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "stage": stage,
        "error_type": type(exc).__name__,
        "code": public["code"],
        "message": public["message"],
    }
    if reason is not None:
        payload["reason"] = reason
    try:
        await audit.record({
            "bundle_id": bundle_id,
            "iteration": iteration,
            "audit_event_type": "ANALYSIS_FAILED",
            "audit_payload": payload,
            "actor": "system",
        })
    except Exception as audit_exc:
        logger.error("analysis_failed_audit_write_failed", bundle_id=bundle_id, run_id=run_id, error=str(audit_exc))


async def _bounded(work: Any, timeout: float) -> None:
    """Run best-effort cleanup for at most ``timeout`` s. Never raises, and keeps going if the caller is cancelled
    again (``asyncio.wait`` does not cancel what it waits for)."""
    task = asyncio.ensure_future(work)
    task.add_done_callback(lambda finished: finished.cancelled() or finished.exception())  # never "not retrieved"
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        task.cancel()
        logger.error("run_failure_bookkeeping_timed_out", timeout_seconds=timeout)


async def _still_owns(bundle_id: str, run_id: str, fence: int) -> bool:
    """Whether this execution still holds the bundle's lease. Unreadable counts as "yes": the writes that follow would fail the
    same way, and a failure that cannot be recorded is better attempted than silently dropped."""
    try:
        await leases.verify(bundle_id, run_id, fence)
    except leases.LeaseLost:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("lease_check_failed", bundle_id=bundle_id, run_id=run_id, error_type=type(exc).__name__)
    return True


async def _fail_run(
    *, bundle_id: str, run_id: str, iteration: int, mode: str, stage: str | None, exc: BaseException,
    reason: str | None = None, fence: int | None = None,
) -> None:
    """Mark the run ERROR (what unblocks clients and the next /analyze) and audit the failure, bounded in time."""

    async def work() -> None:
        if fence is not None and not await _still_owns(bundle_id, run_id, fence):
            # This execution no longer owns the run (a take-over under the same run id, or a reaper got there first): the run record
            # and the audit trail now belong to the new owner. A stale executor's failure must not mark ITS run failed.
            logger.warning("run_failure_not_recorded_lease_lost", bundle_id=bundle_id, run_id=run_id, fence=fence)
            return
        try:
            stored = await firestore.get_run_state(bundle_id, run_id)
        except Exception as read_exc:  # noqa: BLE001 - unreadable: assume it still needs the ERROR
            logger.warning("run_state_read_failed", bundle_id=bundle_id, run_id=run_id, error_type=type(read_exc).__name__)
            stored = {}
        if stored.get("state") == "ERROR":
            # the run already ended in ERROR (the reaper got there first): nothing to overwrite, nothing to audit twice
            logger.info("run_failure_already_recorded", bundle_id=bundle_id, run_id=run_id)
            return
        try:
            await firestore.set_run_error(bundle_id, run_id, error=public_error(exc, run_id)["message"])
            run_events.notify(bundle_id)
        except Exception as state_exc:
            logger.error("run_error_state_write_failed", bundle_id=bundle_id, run_id=run_id, error=str(state_exc))
        await _record_failure(
            bundle_id=bundle_id, run_id=run_id, iteration=iteration, mode=mode, stage=stage, exc=exc, reason=reason
        )
        await _release_quietly(bundle_id, run_id, fence)  # the bundle accepts a new run at once (a fence: only OUR lease)

    await _bounded(work(), _CLEANUP_TIMEOUT_SECONDS)


async def _heartbeat(bundle_id: str, run_id: str, fence: int | None = None) -> None:
    """Touch the run record and extend the lease every RUN_HEARTBEAT_SECONDS so that a live run can be told from a dead one."""
    interval = settings.run_heartbeat_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            await firestore.touch_run(bundle_id, run_id)
            if fence is not None:
                await leases.heartbeat(bundle_id, run_id, fence)
        except leases.LeaseLost:
            # Somebody else owns the bundle now (a take-over, or a reaper): stop pretending. The run's next claim check ends it.
            logger.error("run_lease_lost", bundle_id=bundle_id, run_id=run_id, fence=fence)
            return
        except Exception as exc:  # noqa: BLE001 - a missed beat is survivable; the stale window allows several
            logger.warning("run_heartbeat_failed", bundle_id=bundle_id, run_id=run_id, error_type=type(exc).__name__)


async def _stop_heartbeat(task: asyncio.Task[Any]) -> None:
    """Cancel the heartbeat and wait until it is really gone (safe to call twice)."""
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _stage(stage: str, ctx: dict[str, Any], *, tracker: dict[str, Any]) -> dict[str, Any]:
    """Run ONE pipeline stage: the only callable an engine uses (bound to the run's tracker, it is ``run_stage(stage, ctx)``).

    Marks the stage as current (ctx and tracker, which names the stage in a failure's audit event), resolves the status
    before ``synthesize``, checks the run still owns the bundle (fencing: a stage write on a reaped run would turn its
    ERROR back into RUNNING), writes the progress BEFORE the work, then does the work and logs ``stage_finished`` with its
    duration. ``dispatch`` is looked up on this module at call time, so a test that patches ``orchestrator.dispatch``
    sees every stage whichever engine runs it.

    The "preprocess" stage is the bundle preprocessing: it renders EVERY document (one ``dispatch("preprocess", ...)`` per
    document, each with that document's bytes) and fills ``ctx["processed_pages"]`` for the stages that follow. Dispatching
    it with the pipeline ctx, which carries no ``raw_bytes``, would answer an empty page list and wipe the pages.
    """
    bundle_id = ctx["bundle_id"]
    run_id = ctx["run_id"]
    ctx["stage"] = tracker["stage"] = stage
    progress = _STAGE_PROGRESS[stage]

    # T2.3: Synthesize status before running synthesize stage
    if stage == "synthesize":
        ctx["final_status"] = resolve_final_status(ctx)

    await _ensure_claim(bundle_id, run_id, ctx.get("fence"))
    await _set_stage(bundle_id, run_id, stage, progress)
    logger.info("stage_running", bundle_id=bundle_id, stage=stage, progress=progress)

    started = time.perf_counter()
    recompute = ctx.get("mode") == "recompute"
    if stage == "preprocess":
        if not recompute:  # a recompute reads no document: the stored extraction is reused
            await _preprocess_documents(ctx)
    elif stage == "extract" and recompute:
        await _reuse_extraction(ctx)
    else:
        ctx = await dispatch(stage, ctx)  # route through the decoupled stage dispatcher
    if stage == "extract":
        await corrections.apply_to_ctx(ctx)  # the agent's corrections lie over the extraction, in every run mode
    logger.info(
        "stage_finished", bundle_id=bundle_id, run_id=run_id, stage=stage,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return ctx


async def _run_stages(ctx: dict[str, Any], tracker: dict[str, Any]) -> None:
    """ANALYSIS_STARTED -> the stages (driven by the engine) -> finalize -> iteration persisted -> ASSESSMENT_COMPLETED."""
    bundle_id = ctx["bundle_id"]
    run_id = ctx["run_id"]

    # T2.11: ANALYSIS_STARTED is part of the run, so a failure to record it ends the run in ERROR
    # instead of leaving it RUNNING forever.
    await audit.record({
        "bundle_id": bundle_id,
        "iteration": ctx["iteration"],
        "audit_event_type": "ANALYSIS_STARTED",
        "audit_payload": {
            "run_id": run_id,
            "mode": ctx["mode"],
            "attempt": ctx.get("fence") or 1,  # 2 or more: the run was taken over from an executor that died
            "document_ids": [d.get("document_id") for d in ctx.get("documents", []) if isinstance(d, dict)],
        },
        "actor": "system",
    })

    # The engine drives the stage loop (native: a plain loop; adk: a google-adk Workflow); everything else is identical.
    engine = get_engine(settings.pipeline_engine)
    ctx = await engine(ctx, PIPELINE_STAGES, functools.partial(_stage, tracker=tracker))

    # T2.3: Re-verify final status resolution
    ctx["final_status"] = resolve_final_status(ctx)

    # Finalize: persist the immutable iteration FIRST, then audit it (the caller then marks the run complete).
    ctx["stage"] = tracker["stage"] = "finalize"
    await _ensure_claim(bundle_id, run_id, ctx.get("fence"))
    await _set_stage(bundle_id, run_id, "finalize", _STAGE_PROGRESS["finalize"])
    await _ensure_claim(bundle_id, run_id, ctx.get("fence"))  # the last look before the immutable iteration is written
    iteration = await firestore.write_iteration(ctx)
    run_events.notify(bundle_id)

    await audit.record({
        "bundle_id": bundle_id,
        "iteration": ctx["iteration"],
        "audit_event_type": "ASSESSMENT_COMPLETED",
        "audit_payload": {
            "iteration": ctx["iteration"],
            "status": iteration.get("status", ctx["final_status"]),
            "document_ids": [d.get("document_id") for d in ctx.get("documents", []) if isinstance(d, dict)],
            "data_source": iteration.get("data_source"),
            "mode": ctx["mode"],
            "corrections": [c["correction_id"] for c in ctx.get("corrections", []) if c.get("status") == "applied"],
        },
        "actor": "system",
    })
    await signing.sign_head_quietly(bundle_id, iteration=ctx["iteration"])  # tamper-evidence beyond the hash chain; never fails a run
    tracker["final_status"] = ctx["final_status"]


async def _execute_pipeline(ctx: dict[str, Any]) -> None:
    """Execute the pipeline stages sequentially, under a deadline and a heartbeat, with error containment."""
    bundle_id = ctx["bundle_id"]
    run_id = ctx["run_id"]
    iteration_number = ctx["iteration"]
    mode = ctx["mode"]
    tracker: dict[str, Any] = {"stage": None}
    logger.info("pipeline_started", bundle_id=bundle_id, run_id=run_id, mode=mode)

    fence = ctx.get("fence")
    heartbeat = asyncio.create_task(_heartbeat(bundle_id, run_id, fence), name=f"heartbeat-{run_id}")
    failure = {"bundle_id": bundle_id, "run_id": run_id, "iteration": iteration_number, "mode": mode, "fence": fence}
    try:
        try:
            deadline = asyncio.timeout(settings.run_timeout_seconds)
            try:
                async with deadline:
                    await _run_stages(ctx, tracker)
            except TimeoutError as timeout_exc:
                if not deadline.expired():
                    raise  # a TimeoutError from inside a stage (socket, client): an ordinary failure
                raise RunTimeoutError(TIMEOUT_MESSAGE) from timeout_exc
            await _stop_heartbeat(heartbeat)  # before the terminal write: a late beat must not touch a finished run
            try:
                # fenced when the run holds a lease: the check, the write and the release of the lease are one atomic step
                applied = await firestore.set_run_state(
                    bundle_id, run_id, state="COMPLETE", progress=1.0, only_if_state="RUNNING",
                    **({"fence": fence} if fence is not None else {}),
                )
            except leases.LeaseLost:
                applied = False
            if applied:
                run_events.notify(bundle_id)
                logger.info("pipeline_finished_successfully", bundle_id=bundle_id, status=tracker.get("final_status"))
            else:  # reaped between the last claim check and now: the record stays as the reaper left it
                logger.warning("run_complete_not_applied", bundle_id=bundle_id, run_id=run_id)

        except asyncio.CancelledError as exc:
            await _stop_heartbeat(heartbeat)
            logger.warning("pipeline_cancelled", bundle_id=bundle_id, run_id=run_id, stage=tracker["stage"])
            if ctx.get("dispatched") and _SHUTTING_DOWN:
                # shutting down: the lease expires and Cloud Tasks hands the run to the next worker. Failing it here would lose it.
                logger.warning("run_abandoned_for_retry", bundle_id=bundle_id, run_id=run_id)
                raise
            await _fail_run(**failure, stage=tracker["stage"], exc=exc, reason="cancelled")
            raise

        except Exception as exc:
            await _stop_heartbeat(heartbeat)
            # the raw text is for the operator's log only; clients and the audit log get public_error()
            logger.exception("pipeline_failed", bundle_id=bundle_id, run_id=run_id, error=str(exc))
            await _fail_run(
                **failure, stage=tracker["stage"], exc=exc,
                reason="timeout" if isinstance(exc, RunTimeoutError) else None,
            )
    finally:
        await _stop_heartbeat(heartbeat)
