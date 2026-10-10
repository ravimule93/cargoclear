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

Who may start a run: the API runs as ONE instance, so the claim is an in-process lock per bundle. ``start_run`` holds
it while it reaps a dead run, checks that no live run exists, picks the iteration number and writes the run record;
two simultaneous starts yield one 202 and one 409 even when the store really yields. (Iteration documents are
create-only, a durable backstop.)

How a run proves it is alive: a heartbeat task touches the run record every ``RUN_HEARTBEAT_SECONDS``. A RUNNING
record untouched for ``RUN_STALE_AFTER_SECONDS`` belongs to a dead process; ``reap_stale`` marks it ERROR and audits
it once, and runs inside ``start_run`` and in the SSE poll loop.

How a run ends: the whole pipeline runs under ``RUN_TIMEOUT_SECONDS``. Cancellation (server shutdown) is recorded
(ERROR + ANALYSIS_FAILED, bounded to a few seconds) and then re-raised. Whatever a client or the audit log is told
comes from ``public_error``: raw exception text (paths, bucket names, document content) goes to the logs only.
"""

from __future__ import annotations

import asyncio
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
from app.repo import firestore
from app.services import audit, run_events, storage

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


async def _ensure_claim(bundle_id: str, run_id: str) -> None:
    """Fencing: raise unless the run record for THIS run is still RUNNING.

    A run that was reaped while merely slow (its record is ERROR) or superseded must not write another stage,
    an iteration or an audit event: the bundle may already belong to a newer run.
    """
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


async def reap_stale(bundle_id: str) -> bool:
    """Mark a dead run ERROR and audit it once. Returns True if a run was reaped.

    Dead = state RUNNING and not touched for ``RUN_STALE_AFTER_SECONDS`` (its process is gone, so nobody will ever
    finish it). Idempotent because it only ever acts on RUNNING: once the record is ERROR, later calls do nothing.
    """
    async with _lock(_REAP_LOCKS, bundle_id):
        run = await firestore.get_run_state(bundle_id)
        if run.get("state") != "RUNNING" or not _is_stale(run):
            return False

        run_id = str(run.get("run_id") or "unknown")
        iteration, mode = await _started_event_of(bundle_id, run_id)
        error = RunInterruptedError(INTERRUPTED_MESSAGE)
        logger.warning("run_reaped", bundle_id=bundle_id, run_id=run_id, stage=run.get("stage"), age_seconds=_age_seconds(run))
        await firestore.set_run_error(bundle_id, run_id, error=public_error(error, run_id)["message"])
        run_events.notify(bundle_id)
        await _record_failure(
            bundle_id=bundle_id, run_id=run_id, iteration=iteration, mode=mode,
            stage=run.get("stage"), exc=error, reason="interrupted",
        )
        return True


async def start_run(bundle_id: str, mode: str = "full") -> str:
    """Claim the bundle and start the assessment pipeline as a background asyncio task.

    Enforces, atomically per bundle (see the module docstring):
      - Bundle empty check: 0 documents -> 422 ValidationError.
      - In-flight guard: a live RUNNING run (one that is still heartbeating) -> 409 ConflictError. A dead one is
        reaped first, so it never blocks.
    """
    async with _lock(_START_LOCKS, bundle_id):
        bundle = await firestore.get_bundle(bundle_id)
        documents = bundle.get("documents", []) if bundle else []

        # T2.4c: Bundle with zero documents returns 422
        if not documents:
            raise ValidationError("Cannot analyze an empty bundle. Upload trade documents first.")

        # T2.4b: In-flight guard for active runs (after reaping any run whose heartbeat stopped)
        await reap_stale(bundle_id)
        latest_run = await firestore.get_run_state(bundle_id)
        if latest_run.get("state") == "RUNNING":
            raise ConflictError(
                f"An assessment run is already in progress for bundle '{bundle_id}'.",
                detail={"run_id": latest_run.get("run_id")},
            )

        # MAX_CONCURRENT_RUNS: refuse before anything is written. Reserve the slot in the same synchronous step as the
        # check; the reservation is released once the task counts as running (or the claim failed).
        cap = settings.max_concurrent_runs
        if cap > 0 and _live_runs() >= cap:
            raise ServiceBusyError(
                "The service is busy analysing other bundles. Try again shortly.",
                detail={"max_concurrent_runs": cap},
                headers={"Retry-After": "5"},
            )
        global _starting_runs
        _starting_runs += 1
        try:
            run_id = f"run-{uuid.uuid4().hex[:12]}"
            prev_iteration = await firestore.latest_iteration(bundle_id)
            current_iter_num = max(
                bundle.get("current_iteration", 0) or 0,
                prev_iteration.get("iteration", 0) if prev_iteration else 0,
            ) + 1

            ctx: dict[str, Any] = {
                "bundle_id": bundle_id,
                "run_id": run_id,
                "mode": mode,
                "iteration": current_iter_num,
                "destination_country": bundle.get("destination_country", "SG"),
                "documents": documents,
                "previous_iteration": prev_iteration,
            }

            # Initialize run record in Firestore / in-memory store: from here on the claim is visible to everybody
            await _set_stage(bundle_id, run_id, "initializing", 0.05)

            # T2.4a: Maintain strong reference to asyncio task
            task = asyncio.create_task(_execute_pipeline(ctx), name=f"run-{run_id}")
            _RUNNING_TASKS.add(task)
            task.add_done_callback(_RUNNING_TASKS.discard)
        finally:
            _starting_runs -= 1

    return run_id


async def shutdown(timeout: float = 5.0) -> None:
    """Cancel every running pipeline and wait (up to ``timeout`` s) for their failure bookkeeping to finish."""
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
            all_processed_pages.extend(sub_res.get("processed_pages", []))
            all_transform_meta.extend(sub_res.get("transform_meta", []))
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


async def _fail_run(
    *, bundle_id: str, run_id: str, iteration: int, mode: str, stage: str | None, exc: BaseException,
    reason: str | None = None,
) -> None:
    """Mark the run ERROR (what unblocks clients and the next /analyze) and audit the failure, bounded in time."""

    async def work() -> None:
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

    await _bounded(work(), _CLEANUP_TIMEOUT_SECONDS)


async def _heartbeat(bundle_id: str, run_id: str) -> None:
    """Touch the run record every RUN_HEARTBEAT_SECONDS so that a live run can be told from a dead one."""
    interval = settings.run_heartbeat_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            await firestore.touch_run(bundle_id, run_id)
        except Exception as exc:  # noqa: BLE001 - a missed beat is survivable; the stale window allows several
            logger.warning("run_heartbeat_failed", bundle_id=bundle_id, run_id=run_id, error_type=type(exc).__name__)


async def _stop_heartbeat(task: asyncio.Task[Any]) -> None:
    """Cancel the heartbeat and wait until it is really gone (safe to call twice)."""
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _run_stages(ctx: dict[str, Any], tracker: dict[str, Any]) -> None:
    """ANALYSIS_STARTED -> preprocess -> stages -> finalize -> iteration persisted -> ASSESSMENT_COMPLETED."""
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
            "document_ids": [d.get("document_id") for d in ctx.get("documents", []) if isinstance(d, dict)],
        },
        "actor": "system",
    })

    await _preprocess_documents(ctx)

    for stage in PIPELINE_STAGES:
        ctx["stage"] = tracker["stage"] = stage
        progress = _STAGE_PROGRESS[stage]

        # T2.3: Synthesize status before running synthesize stage
        if stage == "synthesize":
            ctx["final_status"] = resolve_final_status(ctx)

        await _ensure_claim(bundle_id, run_id)  # a stage write on a reaped run would turn its ERROR back into RUNNING
        await _set_stage(bundle_id, run_id, stage, progress)
        logger.info("stage_running", bundle_id=bundle_id, stage=stage, progress=progress)

        # Route through decoupled stage dispatcher
        ctx = await dispatch(stage, ctx)

    # T2.3: Re-verify final status resolution
    ctx["final_status"] = resolve_final_status(ctx)

    # Finalize: persist the immutable iteration FIRST, then audit it (the caller then marks the run complete).
    ctx["stage"] = tracker["stage"] = "finalize"
    await _ensure_claim(bundle_id, run_id)
    await _set_stage(bundle_id, run_id, "finalize", _STAGE_PROGRESS["finalize"])
    await _ensure_claim(bundle_id, run_id)  # the last look before the immutable iteration is written
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
        },
        "actor": "system",
    })
    tracker["final_status"] = ctx["final_status"]


async def _execute_pipeline(ctx: dict[str, Any]) -> None:
    """Execute the pipeline stages sequentially, under a deadline and a heartbeat, with error containment."""
    bundle_id = ctx["bundle_id"]
    run_id = ctx["run_id"]
    iteration_number = ctx["iteration"]
    mode = ctx["mode"]
    tracker: dict[str, Any] = {"stage": None}
    logger.info("pipeline_started", bundle_id=bundle_id, run_id=run_id, mode=mode)

    heartbeat = asyncio.create_task(_heartbeat(bundle_id, run_id), name=f"heartbeat-{run_id}")
    failure = {"bundle_id": bundle_id, "run_id": run_id, "iteration": iteration_number, "mode": mode}
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
            applied = await firestore.set_run_state(
                bundle_id, run_id, state="COMPLETE", progress=1.0, only_if_state="RUNNING"
            )
            if applied:
                run_events.notify(bundle_id)
                logger.info("pipeline_finished_successfully", bundle_id=bundle_id, status=tracker.get("final_status"))
            else:  # reaped between the last claim check and now: the record stays as the reaper left it
                logger.warning("run_complete_not_applied", bundle_id=bundle_id, run_id=run_id)

        except asyncio.CancelledError as exc:
            await _stop_heartbeat(heartbeat)
            logger.warning("pipeline_cancelled", bundle_id=bundle_id, run_id=run_id, stage=tracker["stage"])
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
