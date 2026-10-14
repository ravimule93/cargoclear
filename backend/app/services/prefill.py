"""Builds the declaration pre-fill pack (domain/prefill.py) from an assessment and the extraction behind it.

``assemble`` is pure (dicts in, a pack out) and carries all the rules; ``build`` only gathers its inputs. The rules:

* One value per declaration field, taken from the document that is the best source for it (the table ``FIELDS`` says which
  document types, in order of preference). The other documents' values are listed beside it, and when they disagree the field
  is marked as a conflict. The pack never chooses silently between conflicting documents.
* A value the model was unsure of (below the "auto-accept" confidence), a conflict, a value no document states, and a value
  that an open finding of the assessment cites are all marked for review, with the reason.
* A bundle that is not cleared (or whose corrections are not all in the assessment, or that is not the latest assessment)
  says so in a banner at the top of the pack.
* Lines are the commercial invoice's (else the packing list's). Nothing joins lines across documents: there is no safe key.
* The duty figures are the assessment's indicative estimate, copied as it is.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from app.domain.hs import hs_digits
from app.domain.prefill import (
    PrefillAlternative,
    PrefillAssessment,
    PrefillCommercial,
    PrefillDeclaration,
    PrefillDocument,
    PrefillFinding,
    PrefillInput,
    PrefillIntegrity,
    PrefillLine,
    PrefillMaterial,
    PrefillPack,
    PrefillParties,
    PrefillProvenance,
    PrefillShipment,
    PrefillSource,
    PrefillValue,
)
from app.domain.schemas import AppliedCorrection, BBox, ValuationEstimate
from app.domain.units import parse_number, to_kg, trailing_unit
from app.gateway.errors import ConflictError, NotFoundError
from app.reference.loader import Reference, get_reference
from app.repo import firestore
from app.services import audit, corrections
from app.services.calculation import ABS_TOL, REL_TOL, normalize_entity_name
from app.services.confidence import HIGH_CONF_THRESHOLD

Kind = Literal["entity", "text", "number", "weight", "hs"]

INVOICE, BOL, PACKING, COO, MTC = (
    "COMMERCIAL_INVOICE", "BILL_OF_LADING", "PACKING_LIST", "CERTIFICATE_OF_ORIGIN", "MILL_TEST_CERTIFICATE",
)

# field -> (document field, comparison kind, document types in order of preference)
FIELDS: dict[str, tuple[str, Kind, tuple[str, ...]]] = {
    "consignee": ("consignee", "entity", (INVOICE, BOL, PACKING)),
    "consignor": ("consignor", "entity", (INVOICE, BOL, PACKING)),
    "invoice_number": ("document_number", "text", (INVOICE,)),
    "bill_of_lading_number": ("document_number", "text", (BOL,)),
    "packing_list_number": ("document_number", "text", (PACKING,)),
    "vessel_or_flight": ("vessel_or_flight", "entity", (BOL, INVOICE, PACKING)),
    "port_of_loading": ("port_of_loading", "entity", (BOL, INVOICE, PACKING)),
    "port_of_discharge": ("port_of_discharge", "entity", (BOL, INVOICE, PACKING)),
    "shipment_date": ("shipment_date", "text", (BOL, INVOICE, PACKING)),
    "incoterm": ("incoterm", "text", (INVOICE, BOL)),
    "country_of_origin": ("country_of_origin", "text", (INVOICE, COO, PACKING, MTC)),
    "package_count": ("package_count", "number", (PACKING, BOL)),
    "total_gross_weight": ("total_gross_weight_kg", "weight", (BOL, PACKING)),
    "total_net_weight": ("total_net_weight_kg", "weight", (PACKING, BOL)),
    "invoice_value": ("invoice_value", "number", (INVOICE,)),
    "invoice_currency": ("invoice_currency", "text", (INVOICE,)),
    "freight_amount": ("freight_amount", "number", (INVOICE, BOL)),
    "freight_currency": ("freight_currency", "text", (INVOICE, BOL)),
    "insurance_amount": ("insurance_amount", "number", (INVOICE, BOL)),
    "insurance_currency": ("insurance_currency", "text", (INVOICE, BOL)),
}

# line field in the pack -> (line-item field, comparison kind is irrelevant: one source)
LINE_FIELDS = {
    "description": "description",
    "hs_code": "hs_code_declared",
    "quantity": "quantity",
    "unit_price": "unit_price",
    "unit_price_basis": "unit_price_basis",
    "line_value": "total_value",
    "currency": "currency",
    "net_weight": "net_weight_kg",
    "gross_weight": "gross_weight_kg",
}


# ---------------------------------------------------------------------------
# small readers
# ---------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def _has_value(ref: Any) -> bool:
    return isinstance(ref, dict) and _text(ref.get("value")) is not None


def _evidence_path(entry: dict[str, Any]) -> str | None:
    """The address of the value a check's evidence entry points at (the same grammar as a correction's path)."""
    field = entry.get("field")
    if not isinstance(field, str):
        return None
    if isinstance(entry.get("row"), int):
        return f"{field}[{entry['row']}]"
    if isinstance(entry.get("line_item"), int):
        return f"line_items[{entry['line_item']}].{field}"
    return field


def _flag_index(checks: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    """(document id, address) -> the open findings (MATERIAL / WARN) whose evidence cites that value."""
    index: dict[tuple[str, str], list[str]] = {}
    for check in checks:
        if check.get("severity") not in ("MATERIAL", "WARN"):
            continue
        note = f"{check.get('check_id')} ({str(check.get('severity')).lower()}) cites this value"
        for entry in check.get("evidence") or []:
            path = _evidence_path(entry) if isinstance(entry, dict) else None
            if path and entry.get("doc"):
                notes = index.setdefault((entry["doc"], path), [])
                if note not in notes:
                    notes.append(note)
    return index


def _same(kind: Kind, a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Do two documents state the same thing in this field? Conservative: when in doubt the values differ."""
    x, y = _text(a.get("value")) or "", _text(b.get("value")) or ""
    if kind == "entity":
        return normalize_entity_name(x) == normalize_entity_name(y)
    if kind == "hs":
        dx, dy = hs_digits(x), hs_digits(y)
        n = min(len(dx), len(dy))
        return n >= 4 and dx[:n] == dy[:n]
    if kind in ("number", "weight"):
        px, py = parse_number(x), parse_number(y)
        if px is None or py is None:
            return " ".join(x.casefold().split()) == " ".join(y.casefold().split())
        if kind == "number":
            return abs(px.value - py.value) <= 1e-6 * max(1.0, abs(px.value))
        kx = to_kg(px.value, _text(a.get("unit")) or trailing_unit(x))
        ky = to_kg(py.value, _text(b.get("unit")) or trailing_unit(y))
        if kx.error or ky.error:
            return False
        return abs(kx.kg - ky.kg) <= max(REL_TOL * max(kx.kg, ky.kg), ABS_TOL)
    return " ".join(x.casefold().split()) == " ".join(y.casefold().split())


def _source(doc: dict[str, Any], ref: dict[str, Any], filenames: dict[str, str]) -> PrefillSource:
    bbox = ref.get("bbox")
    parsed = BBox.model_validate(bbox) if isinstance(bbox, dict) else None
    return PrefillSource(
        document_id=doc["document_id"],
        filename=filenames.get(doc["document_id"]),
        doc_type=doc.get("doc_type", "UNKNOWN"),
        page=parsed.page if parsed else None,
        bbox=parsed,
    )


def _confidence(ref: dict[str, Any]) -> float:
    if ref.get("corrected") is True:
        return 1.0
    try:
        return float(ref.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _value(
    candidates: list[tuple[dict[str, Any], dict[str, Any]]],
    kind: Kind,
    filenames: dict[str, str],
    flags: dict[tuple[str, str], list[str]],
    path_of: Any,
) -> PrefillValue:
    """One pack value from the candidates (document, reference) in order of preference; the first is the value."""
    if not candidates:
        return PrefillValue(review=["not stated on any document"])
    (doc, ref), rest = candidates[0], candidates[1:]
    confidence = _confidence(ref)
    corrected = ref.get("corrected") is True
    review: list[str] = []

    conflicting = [(d, r) for d, r in rest if not _same(kind, ref, r)]
    if conflicting:
        seen = "; ".join(
            f"{d.get('doc_type')} says {_text(r.get('value'))}{(' ' + u) if (u := _text(r.get('unit'))) else ''}" for d, r in conflicting
        )
        review.append(f"documents disagree: {seen}")
    if not corrected and confidence < HIGH_CONF_THRESHOLD:
        review.append(f"read with confidence {confidence:.2f}")
    review.extend(flags.get((doc["document_id"], path_of(doc)), []))

    return PrefillValue(
        value=_text(ref.get("value")),
        unit=_text(ref.get("unit")),
        source=_source(doc, ref, filenames),
        confidence=round(confidence, 4),
        corrected=corrected,
        alternatives=[
            PrefillAlternative(document_id=d["document_id"], doc_type=d.get("doc_type", "UNKNOWN"), value=_text(r.get("value")), unit=_text(r.get("unit")))
            for d, r in rest
        ],
        conflict=bool(conflicting),
        review=review,
    )


def _header_value(
    docs: list[dict[str, Any]], name: str, filenames: dict[str, str], flags: dict[tuple[str, str], list[str]]
) -> PrefillValue:
    field, kind, doc_types = FIELDS[name]
    candidates = [
        (doc, doc[field])
        for doc_type in doc_types
        for doc in docs
        if doc.get("doc_type") == doc_type and _has_value(doc.get(field))
    ]
    return _value(candidates, kind, filenames, flags, lambda _doc, f=field: f)


def _line_value(
    doc: dict[str, Any], index: int, field: str, filenames: dict[str, str], flags: dict[tuple[str, str], list[str]]
) -> PrefillValue:
    ref = (doc.get("line_items") or [])[index].get(field)
    candidates = [(doc, ref)] if _has_value(ref) else []
    kind: Kind = "hs" if field == "hs_code_declared" else "text"
    return _value(candidates, kind, filenames, flags, lambda _doc, i=index, f=field: f"line_items[{i}].{f}")


# ---------------------------------------------------------------------------
# the pack
# ---------------------------------------------------------------------------

_STATUS_WORDS = {
    "COMPLIANT_FOR_SUBMISSION": "compliant for submission",
    "MISSING_EVIDENCE": "missing evidence",
    "MATERIAL_CONTRADICTION": "material contradiction",
    "SPECIALIST_REVIEW_REQUIRED": "specialist review required",
}


def _findings(checks: list[dict[str, Any]], severity: str) -> list[PrefillFinding]:
    return [
        PrefillFinding(check_id=str(c.get("check_id")), severity=severity, message=str(c.get("message", "")))
        for c in checks
        if c.get("severity") == severity
    ]


def _banner(status: str, blocking: int, review: int, missing: int, pending: int, superseded_by: int | None, iteration: int) -> str | None:
    lines: list[str] = []
    if status != "COMPLIANT_FOR_SUBMISSION":
        lines.append(
            f"NOT CLEARED. The assessment is {_STATUS_WORDS.get(status, status)}: {blocking} contradiction(s), "
            f"{missing} missing document(s), {review} item(s) for specialist review. Resolve them before these values are used."
        )
    if pending:
        lines.append(
            f"{pending} correction change(s) made after this assessment are NOT included in these values. Recompute first."
        )
    if superseded_by is not None:
        lines.append(f"SUPERSEDED. This pack is for assessment {iteration}; assessment {superseded_by} is newer.")
    return " ".join(lines) or None


def assemble(
    *,
    bundle: dict[str, Any],
    iteration: dict[str, Any],
    extracted: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
    reference: Reference,
    pending_corrections: int = 0,
    latest_iteration: int | None = None,
    now: datetime | None = None,
) -> PrefillPack:
    """The pack for one assessment. Pure: everything it needs is passed in."""
    filenames = {d["document_id"]: d.get("filename", "") for d in bundle.get("documents", []) if d.get("document_id")}
    checks: list[dict[str, Any]] = [c for c in iteration.get("checks", []) if isinstance(c, dict)]
    flags = _flag_index(checks)
    destination = str(bundle.get("destination_country", "SG")).upper()

    def header(name: str) -> PrefillValue:
        return _header_value(extracted, name, filenames, flags)

    # lines: the invoice's, else the packing list's
    line_doc = next((d for t in (INVOICE, PACKING) for d in extracted if d.get("doc_type") == t and d.get("line_items")), None)
    lines: list[PrefillLine] = []
    if line_doc is not None:
        for index in range(len(line_doc["line_items"])):
            values = {
                name: _line_value(line_doc, index, field, filenames, flags) for name, field in LINE_FIELDS.items()
            }
            lines.append(PrefillLine(line_no=index + 1, document_id=line_doc["document_id"], **values))

    certificate = next((d for d in extracted if d.get("doc_type") == MTC), None)
    if certificate is not None:
        heats = list(dict.fromkeys(t for h in certificate.get("heat_numbers") or [] if isinstance(h, dict) and (t := _text(h.get("value")))))
        spec = certificate.get("specification")
        spec_candidates = [(certificate, spec)] if isinstance(spec, dict) and _has_value(spec) else []
        material = PrefillMaterial(
            certificate_document_id=certificate["document_id"],
            specification=_value(spec_candidates, "text", filenames, flags, lambda _d: "specification"),
            heat_numbers=heats,
        )
    else:
        material = PrefillMaterial(specification=PrefillValue(review=["no mill test certificate in the bundle"]))

    blocking = _findings(checks, "MATERIAL")
    review = _findings(checks, "WARN")
    missing = [str(m.get("document_label", m.get("id"))) for m in iteration.get("missing_evidence", []) if isinstance(m, dict)]
    status = str(iteration.get("status", ""))
    number = int(iteration.get("iteration", 0))
    superseded_by = latest_iteration if latest_iteration is not None and latest_iteration > number else None

    declaration = reference.declaration_inputs.for_destination(destination)
    events = audit_events
    verified, _reason = audit.verify_audit_chain(events)
    valuation = iteration.get("valuation")
    assessed = set(iteration.get("documents", []))

    pack = PrefillPack(
        generated_at=(now or datetime.now(timezone.utc)).isoformat(),
        banner=_banner(status, len(blocking), len(review), len(missing), pending_corrections, superseded_by, number),
        bundle_id=str(bundle["id"]),
        reference=bundle.get("reference"),
        declaration=PrefillDeclaration(
            destination_country=destination,
            declaration=declaration.declaration,
            rule_set=reference.declaration_inputs.rule_set,
            regulation_ref=reference.declaration_inputs.regulation_ref,
        ),
        assessment=PrefillAssessment(
            iteration=number,
            status=status,
            run_mode=iteration.get("run_mode"),
            created_at=iteration.get("created_at"),
            data_source=iteration.get("data_source"),
            blocking=blocking,
            review=review,
            missing_documents=missing,
            pending_corrections=pending_corrections,
        ),
        parties=PrefillParties(consignee=header("consignee"), consignor=header("consignor")),
        shipment=PrefillShipment(
            **{name: header(name) for name in (
                "invoice_number", "bill_of_lading_number", "packing_list_number", "vessel_or_flight", "port_of_loading",
                "port_of_discharge", "shipment_date", "incoterm", "country_of_origin", "package_count",
                "total_gross_weight", "total_net_weight",
            )}
        ),
        commercial=PrefillCommercial(
            **{name: header(name) for name in (
                "invoice_value", "invoice_currency", "freight_amount", "freight_currency", "insurance_amount", "insurance_currency",
            )}
        ),
        lines=lines,
        material=material,
        valuation=ValuationEstimate.model_validate(valuation) if valuation else None,
        to_be_supplied=[PrefillInput(id=i.id, label=i.label) for i in declaration.inputs],
        corrections=[AppliedCorrection.model_validate(c) for c in iteration.get("corrections", []) if isinstance(c, dict)],
        documents=[
            PrefillDocument(
                document_id=d["document_id"], filename=d.get("filename", ""), doc_type=d.get("doc_type", "UNKNOWN"),
                sha256=d.get("sha256", ""), bytes=int(d.get("bytes", 0)),
            )
            for d in bundle.get("documents", [])
            if d.get("document_id") in assessed
        ],
        provenance=PrefillProvenance(
            audit_events=len(events),
            audit_head_hash=events[-1]["hash"] if events else None,
            audit_chain_verified=verified,
            reference_data=iteration.get("reference_data"),
        ),
        integrity=PrefillIntegrity(content_sha256=""),
    )
    pack.integrity.content_sha256 = content_hash(pack)
    return pack


def content_hash(pack: PrefillPack) -> str:
    """SHA-256 of the pack's canonical JSON without its integrity block: anyone can recompute it from the file."""
    body = pack.model_dump(mode="json", exclude={"integrity"})
    return hashlib.sha256(audit.canonical_json(body).encode("utf-8")).hexdigest()


async def build(bundle_id: str, iteration: int | None = None) -> PrefillPack:
    """The pack for the latest assessment of a bundle, or for ``iteration``. 404 unknown bundle / iteration, 409 nothing assessed."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})
    latest = await firestore.latest_iteration(bundle_id)
    if latest is None:
        raise ConflictError("Run the analysis first: there is nothing to pre-fill from yet.", detail={"bundle_id": bundle_id})
    chosen = latest if iteration is None else await firestore.get_iteration(bundle_id, iteration)
    if chosen is None:
        raise NotFoundError(f"Assessment {iteration} not found for bundle '{bundle_id}'.", detail={"bundle_id": bundle_id, "iteration": iteration})

    number = int(chosen.get("iteration", 0))
    extracted = await corrections.effective_extraction(bundle_id, iteration=number)
    if not extracted:
        raise ConflictError("That assessment has no stored extraction to pre-fill from.", detail={"bundle_id": bundle_id, "iteration": number})
    latest_number = int(latest.get("iteration", 0))
    state = await corrections.state(bundle_id)
    return assemble(
        bundle=bundle,
        iteration=chosen,
        extracted=extracted,
        audit_events=await audit.list_audit_events(bundle_id),
        reference=get_reference(),
        pending_corrections=state.pending if number == latest_number else 0,
        latest_iteration=latest_number,
    )
