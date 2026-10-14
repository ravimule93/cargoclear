"""Corrections by the authorised agent: recording them, listing them, and laying them on an extraction.

The tamper-evident audit log IS the store. A correction is one audit event (FIELD_CORRECTED / FIELD_CONFIRMED /
CORRECTION_REVERTED), so recording it is a single atomic append: there is no second copy that could disagree with the
audit trail, and a correction that is in force is, by construction, a correction that is audited. ``domain/corrections.py``
turns those events back into the overlay.

What a correction is checked against: the extraction of the LATEST assessment (what the agent was looking at). The model's
original value, and the value just before this entry, are recorded with it so the trail shows what changed.

Who sees the overlay: the pipeline lays it on after the ``extract`` stage in every run mode (``apply_to_ctx``), so a
reassessment after a new upload keeps the agent's corrections, and a ``recompute`` run (which reuses the stored extraction)
is the cheap way to re-run the checks after correcting.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.core.config import settings
from app.domain import corrections as overlay
from app.domain.corrections import (
    EVENT_CONFIRMED,
    EVENT_CORRECTED,
    EVENT_REVERTED,
    Address,
    CorrectionError,
)
from app.domain.schemas import (
    CorrectionRecord,
    CorrectionRequest,
    CorrectionsResponse,
    ExtractedDocument,
)
from app.gateway.errors import ConflictError, NotFoundError, ValidationError
from app.repo import firestore
from app.services import audit

logger = structlog.get_logger(__name__)

ACTOR = "user"  # there is no authentication yet: the audit actor for a person is the literal "user", as for uploads


async def history(bundle_id: str) -> list[CorrectionRecord]:
    """Every correction entry of the bundle, oldest first."""
    return (await _read(bundle_id))[0]


async def _read(bundle_id: str) -> tuple[list[CorrectionRecord], int]:
    """(the correction entries, the sequence number of the chain's newest event): what a writer decides on, and the head it must
    still find when it appends (``audit.record(after_seq=...)``)."""
    events = await audit.list_audit_events(bundle_id)
    return overlay.parse_events(events), (int(events[-1]["seq"]) if events else 0)


async def state(bundle_id: str) -> CorrectionsResponse:
    """The history, the overlay in force, and how much of it the latest assessment does not include yet."""
    records = await history(bundle_id)
    in_force = overlay.effective(records)
    latest = await firestore.latest_iteration(bundle_id)
    used = {c.get("correction_id") for c in (latest or {}).get("corrections", []) if isinstance(c, dict)}
    wanted = {r.correction_id for r in in_force}
    return CorrectionsResponse(
        corrections=records,
        effective=in_force,
        pending=len(wanted ^ used) if latest else len(wanted),
        latest_iteration=latest.get("iteration") if latest else None,
    )


async def _base(bundle_id: str) -> tuple[int, list[dict[str, Any]]]:
    """(iteration, raw extraction) of the latest assessment: what a correction is made against."""
    latest = await firestore.latest_iteration(bundle_id)
    if latest is None:
        raise ConflictError(
            "Run the analysis before correcting: there is nothing extracted to correct yet.",
            detail={"bundle_id": bundle_id},
        )
    iteration = int(latest.get("iteration", 0))
    record = await firestore.get_extraction_record(bundle_id, iteration)
    if not record or not record.get("extractions"):
        raise ConflictError(
            "The latest assessment has no stored extraction to correct.",
            detail={"bundle_id": bundle_id, "iteration": iteration},
        )
    return iteration, list(record["extractions"])


def _count_guard(records: list[CorrectionRecord]) -> None:
    if len(records) >= settings.max_corrections_per_bundle:
        raise ValidationError(
            f"A bundle can hold at most {settings.max_corrections_per_bundle} correction entries.",
            detail={"max_corrections": settings.max_corrections_per_bundle},
        )


# A writer decides on what it read from the chain; if somebody appended in between (a second tab, another instance, the pipeline),
# it reads again and decides again, a few times, before telling the caller to retry.
_ATTEMPTS = 4


async def submit(bundle_id: str, request: CorrectionRequest) -> CorrectionRecord:
    """Record one correction (or confirmation) of a value in the latest extraction.

    Refused with 409 before any analysis exists, 404 for a document or row that is not in it, 422 for a value the engines
    could not read without guessing. The entry is FIELD_CONFIRMED when the value equals the one already in force (the agent
    checked the document and the model was right), FIELD_CORRECTED otherwise. The entry records the value in force just before
    it, so it is appended only if the chain is still as it was read: a concurrent correction makes this one read again.
    """
    for _ in range(_ATTEMPTS):
        iteration, event_type, payload, head = await _prepare(bundle_id, request)
        try:
            event = await _append(bundle_id, iteration, event_type, payload, after_seq=head)
        except audit.ChainMoved:
            continue
        logger.info("correction_recorded", bundle_id=bundle_id, correction_id=f"cor-{event['seq']}", kind=event_type, path=payload["path"])
        return _record_of(event)
    raise ConflictError("The bundle's history kept changing while the correction was recorded. Try again.", detail={"bundle_id": bundle_id})


async def _prepare(bundle_id: str, request: CorrectionRequest) -> tuple[int, str, dict[str, Any], int]:
    """Validate the request against the extraction and the corrections in force; (iteration, event type, payload, chain head read)."""
    iteration, raw = await _base(bundle_id)
    records, head = await _read(bundle_id)
    _count_guard(records)

    doc = overlay.find_document(raw, request.document_id)
    if doc is None:
        raise NotFoundError(
            f"Document '{request.document_id}' is not part of the latest assessment.",
            detail={"bundle_id": bundle_id, "document_id": request.document_id},
        )
    try:
        address = overlay.parse_path(request.path)
    except CorrectionError as exc:
        raise ValidationError(exc.message, detail={"path": request.path}) from exc

    original = overlay.read_value(doc, address)
    if original is None:
        raise NotFoundError(
            f"'{request.path}' does not exist in this document's extraction.",
            detail={"bundle_id": bundle_id, "document_id": request.document_id, "path": request.path},
        )
    original_value, original_unit = original

    in_force = overlay.effective(records)
    corrected_doc = overlay.find_document(overlay.apply(raw, in_force).docs, request.document_id) or doc
    previous_value, previous_unit = overlay.read_value(corrected_doc, address) or (None, None)

    if request.clear:
        if request.value not in (None, ""):
            raise ValidationError("Give either a value or clear, not both.", detail={"path": request.path})
        if address.scope == "row" or address.scope == "doc_type":
            raise ValidationError("This value cannot be cleared; correct it instead.", detail={"path": request.path})
        value, unit = None, None
    else:
        if request.value is None:
            raise ValidationError("Give the corrected value, or clear it.", detail={"path": request.path})
        try:
            value, unit = overlay.validate_value(
                address, request.value, request.unit, existing_unit=previous_unit if address.has_unit else None
            )
        except CorrectionError as exc:
            raise ValidationError(exc.message, detail={"path": request.path}) from exc

    anchor = _anchor(doc, address)
    unit_in_force = unit if unit is not None else previous_unit
    unchanged = value == previous_value and (not address.has_unit or unit_in_force == previous_unit)
    event_type = EVENT_CONFIRMED if unchanged else EVENT_CORRECTED
    reason = (request.reason or "").strip() or None
    payload = overlay.payload_of({
        "document_id": request.document_id,
        "path": address.path,
        "anchor": anchor,
        "value": value,
        "unit": unit,
        "original_value": original_value,
        "original_unit": original_unit,
        "previous_value": previous_value,
        "previous_unit": previous_unit,
        "reason": reason,
    })
    return iteration, event_type, payload, head


async def revert(bundle_id: str, correction_id: str, reason: str | None = None) -> CorrectionRecord:
    """Undo one entry that is in force: the value goes back to the entry before it, or to what the model read.

    Not subject to the cap on entries: an undo needs an entry in force to undo, so there are at most as many as the cap allows
    (an agent who reached the cap must still be able to take a wrong correction back)."""
    for _ in range(_ATTEMPTS):
        records, head = await _read(bundle_id)
        target = next((r for r in overlay.effective(records) if r.correction_id == correction_id), None)
        if target is None:
            raise NotFoundError(
                f"'{correction_id}' is not a correction in force for this bundle.",
                detail={"bundle_id": bundle_id, "correction_id": correction_id},
            )
        latest = await firestore.latest_iteration(bundle_id)
        try:
            event = await _append(
                bundle_id,
                int(latest.get("iteration", 0)) if latest else 0,
                EVENT_REVERTED,
                overlay.payload_of({
                    "document_id": target.document_id,
                    "path": target.path,
                    "reverts": target.correction_id,
                    "reason": (reason or "").strip() or None,
                }),
                after_seq=head,
            )
        except audit.ChainMoved:
            continue
        logger.info("correction_reverted", bundle_id=bundle_id, correction_id=correction_id)
        return _record_of(event)
    raise ConflictError("The bundle's history kept changing while the undo was recorded. Try again.", detail={"bundle_id": bundle_id})


async def _append(bundle_id: str, iteration: int, event_type: str, payload: dict[str, Any], *, after_seq: int) -> dict[str, Any]:
    recorded = await audit.record({
        "bundle_id": bundle_id,
        "iteration": iteration,
        "audit_event_type": event_type,
        "audit_payload": payload,
        "actor": ACTOR,
        "after_seq": after_seq,
    })
    event: dict[str, Any] = recorded["audit_event"]
    return event


def _record_of(event: dict[str, Any]) -> CorrectionRecord:
    parsed = overlay.parse_events([event])
    if not parsed:  # only possible if payload_of and parse_events disagree: a programming error
        raise RuntimeError("a recorded correction could not be read back")
    return parsed[0]


def _anchor(doc: dict[str, Any], address: Address) -> str | None:
    """The identity of the row a list address points at (None for a header field)."""
    if address.scope not in ("line", "row"):
        return None
    rows = overlay.rows_of(doc, address)
    row = rows[address.index] if address.index is not None and 0 <= address.index < len(rows) else None
    return overlay.row_anchor(address, row) if isinstance(row, dict) else None


# ---------------------------------------------------------------------------
# In the pipeline
# ---------------------------------------------------------------------------


async def apply_to_ctx(ctx: dict[str, Any]) -> None:
    """Lay the overlay in force on ``ctx["extracted"]`` and record what happened in ``ctx["corrections"]``.

    Runs after the ``extract`` stage in every run mode. The stored extraction is not touched (it stays what the model read);
    ``ctx["extracted"]`` becomes the corrected view every later stage reads. A corrected document type is also written to the
    document record, so the rail and the missing-evidence logic agree with the checks.
    """
    bundle_id: str = ctx["bundle_id"]
    in_force = overlay.effective(await history(bundle_id))
    ctx["corrections"] = []
    if not in_force:
        return

    raw = [doc.model_dump(mode="json") for doc in ctx.get("extracted", [])]
    result = overlay.apply(raw, in_force)
    ctx["extracted"] = [ExtractedDocument.model_validate(doc) for doc in result.docs]
    ctx["corrections"] = [outcome.model_dump(mode="json") for outcome in result.outcomes]

    for outcome in result.outcomes:
        if outcome.status == "applied" and outcome.path == "doc_type" and outcome.value:
            await firestore.update_document_doc_type(bundle_id, outcome.document_id, outcome.value)
    logger.info(
        "corrections_applied",
        bundle_id=bundle_id,
        run_id=ctx.get("run_id"),
        applied=sum(1 for o in result.outcomes if o.status == "applied"),
        skipped=sum(1 for o in result.outcomes if o.status == "skipped"),
    )


async def effective_extraction(bundle_id: str, iteration: int | None = None) -> list[dict[str, Any]]:
    """The extraction of an iteration as its checks saw it: what the model read with that iteration's corrections laid on,
    each corrected field marked (``corrected``, ``original_value``). The raw record is unchanged."""
    if iteration is None:
        latest = await firestore.latest_iteration(bundle_id)
        iteration = int(latest.get("iteration", 1)) if latest else 1
    raw = await firestore.get_extractions(bundle_id, iteration=iteration)
    stored = await firestore.get_iteration(bundle_id, iteration)
    used = [
        entry
        for entry in ((stored or {}).get("corrections") or [])
        if isinstance(entry, dict) and entry.get("status") == "applied"
    ]
    if not used:
        return raw
    return overlay.apply(raw, [_record_from_applied(entry) for entry in used]).docs


def _record_from_applied(entry: dict[str, Any]) -> CorrectionRecord:
    """An iteration's stored applied-correction entry, as a record ``apply`` can lay on a raw extraction again."""
    return CorrectionRecord(
        correction_id=entry["correction_id"],
        kind="correction",
        seq=int(entry["seq"]),
        created_at=str(entry.get("created_at", "")),
        iteration=0,
        document_id=entry["document_id"],
        path=entry["path"],
        anchor=entry.get("anchor"),
        value=entry.get("value"),
        unit=entry.get("unit"),
        original_value=entry.get("original_value"),
        original_unit=entry.get("original_unit"),
        reason=entry.get("reason"),
    )
