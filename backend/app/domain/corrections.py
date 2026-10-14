"""Corrections by the authorised agent: an overlay on what the model read.

Pure functions, no I/O. The extraction stays exactly as the model produced it (an immutable record per iteration); a
correction says "the document actually states X at this address", and ``apply`` lays the corrections on top of a copy of
the extraction before any check runs. So a correction is never a silent edit: it is an audited entry (services/corrections.py
writes it to the hash-chained audit log), it is listed on every assessment that used it, and removing it restores what the
model read.

Addresses (``path``) are a small closed grammar, validated against explicit tables (not by reflection), so a typo cannot
write to a field no engine reads:

    consignee                       a header field of the document
    line_items[2].hs_code_declared  a field of one invoice / packing-list line
    heat_numbers[0]                 one heat number printed on the document
    test_results[7]                 the value of one certificate cell (one heat x one parameter)
    doc_type                        what kind of document it is

Rows can move when a bundle is read again (a model may order a table differently the next time), so a row address
carries an ``anchor``, the row's identity (a heat and a parameter, a description, a heat number). ``apply`` finds the row by
index when the anchor still matches, by the anchor when it is unique, and otherwise SKIPS the correction and says so: a
correction is never applied to a row it was not made for.

A corrected value has confidence 1.0 (a person read it) and keeps the box of the printed value it replaces, so the viewer
still points at the right place. It may also fill a field the model left empty, or (``clear``) empty one the model invented.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, get_args

from app.domain.hs import hs_digits
from app.domain.measures import canonical_parameter, normalize_heat, parse_measure
from app.domain.schemas import AppliedCorrection, CorrectionRecord, DocType
from app.domain.units import normalize_unit, parse_number, to_kg, trailing_unit

Kind = Literal["text", "long_text", "currency", "hs", "number", "weight", "heat", "lab", "doc_type"]

# Audit event types the overlay is read from (the audit log is the only store of corrections).
EVENT_CORRECTED = "FIELD_CORRECTED"
EVENT_CONFIRMED = "FIELD_CONFIRMED"
EVENT_REVERTED = "CORRECTION_REVERTED"
CORRECTION_EVENT_TYPES = (EVENT_CORRECTED, EVENT_CONFIRMED, EVENT_REVERTED)

_KIND_OF_EVENT: dict[str, Literal["correction", "confirmation", "revert"]] = {
    EVENT_CORRECTED: "correction",
    EVENT_CONFIRMED: "confirmation",
    EVENT_REVERTED: "revert",
}

# Every FieldRef the engines read, by where it lives. A test pins these tables to the schema, so a field added to
# ExtractedDocument / LineItem is a deliberate choice here (correctable or not), never an accident.
HEADER_FIELDS: dict[str, Kind] = {
    "document_number": "text",
    "consignee": "text",
    "consignor": "text",
    "vessel_or_flight": "text",
    "port_of_loading": "text",
    "port_of_discharge": "text",
    "shipment_date": "text",
    "invoice_value": "number",
    "invoice_currency": "currency",
    "total_net_weight_kg": "weight",
    "total_gross_weight_kg": "weight",
    "tare_weight_kg": "weight",
    "package_count": "number",
    "hs_code_header": "hs",
    "incoterm": "text",
    "country_of_origin": "text",
    "freight_amount": "number",
    "freight_currency": "currency",
    "insurance_amount": "number",
    "insurance_currency": "currency",
    "specification": "text",
}
LINE_FIELDS: dict[str, Kind] = {
    "description": "long_text",
    "quantity": "text",
    "net_weight_kg": "weight",
    "gross_weight_kg": "weight",
    "hs_code_declared": "hs",
    "unit_price": "number",
    "total_value": "number",
    "currency": "currency",
    "unit_price_basis": "text",
}
ROW_LISTS: dict[str, Kind] = {"heat_numbers": "heat", "test_results": "lab"}

_UNIT_KINDS = frozenset({"weight", "lab"})  # kinds whose FieldRef carries a printed unit
_TEXT_LIMIT = 200
_LONG_TEXT_LIMIT = 500
_HEAT_LIMIT = 60
_UNIT_LIMIT = 24
_MAX_INDEX = 9999
_DOC_TYPES = tuple(t for t in get_args(DocType) if t != "UNKNOWN")  # a person never classifies a document as "unknown"

_HEADER_PATH = re.compile(r"^(?P<field>[a-z_]+)$")
_LINE_PATH = re.compile(r"^line_items\[(?P<index>\d{1,4})\]\.(?P<field>[a-z_]+)$")
_ROW_PATH = re.compile(r"^(?P<field>[a-z_]+)\[(?P<index>\d{1,4})\]$")
_CURRENCY = re.compile(r"^[A-Za-z]{3}$")
_HS_CHARS = re.compile(r"^[0-9][0-9. \-]*$")
_UNIT_CHARS = re.compile(r"^[A-Za-z0-9%/.·µ°^ \-]+$")


class CorrectionError(ValueError):
    """A correction that cannot be accepted. ``message`` is written for the person who made it, and is safe to show."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Address:
    """Where in an extracted document a correction applies."""

    scope: Literal["header", "line", "row", "doc_type"]
    field: str                   # header / line field, the list name for a row, or "doc_type"
    index: int | None = None     # line index (scope "line") or row index (scope "row")

    @property
    def path(self) -> str:
        if self.scope == "line":
            return f"line_items[{self.index}].{self.field}"
        if self.scope == "row":
            return f"{self.field}[{self.index}]"
        return self.field

    @property
    def kind(self) -> Kind:
        if self.scope == "header":
            return HEADER_FIELDS[self.field]
        if self.scope == "line":
            return LINE_FIELDS[self.field]
        if self.scope == "row":
            return ROW_LISTS[self.field]
        return "doc_type"

    @property
    def has_unit(self) -> bool:
        return self.kind in _UNIT_KINDS


def path_label(path: str) -> str:
    """A short human label for an address: "Consignee", "Line 2 · Hs code declared", "Certificate cell 7", "Heat number 1".

    The same words as ``pathLabel`` in frontend/lib/corrections.ts; the vectors in docs/schemas/path-labels.json pin the two to each other.
    """
    def words(name: str) -> str:
        spaced = re.sub(r"_kg$", "", name).replace("_", " ")
        return spaced[:1].upper() + spaced[1:]

    line = re.fullmatch(r"line_items\[(\d+)\]\.([a-z_]+)", path)
    if line:
        return f"Line {int(line.group(1)) + 1} · {words(line.group(2))}"
    row = re.fullmatch(r"([a-z_]+)\[(\d+)\]", path)
    if row:
        return f"{'Heat number' if row.group(1) == 'heat_numbers' else 'Certificate cell'} {int(row.group(2)) + 1}"
    return words(path)


def parse_path(path: str) -> Address:
    """The address a path names; ``CorrectionError`` for anything outside the grammar and the field tables."""
    text = (path or "").strip()
    if text == "doc_type":
        return Address("doc_type", "doc_type")

    line = _LINE_PATH.match(text)
    if line:
        field = line["field"]
        if field not in LINE_FIELDS:
            raise CorrectionError(f"'{field}' is not a line-item field that can be corrected.")
        return Address("line", field, _index(line["index"]))

    row = _ROW_PATH.match(text)
    if row:
        field = row["field"]
        if field not in ROW_LISTS:
            raise CorrectionError(f"'{field}' is not a list that can be corrected.")
        return Address("row", field, _index(row["index"]))

    header = _HEADER_PATH.match(text)
    if header and header["field"] in HEADER_FIELDS:
        return Address("header", header["field"])
    raise CorrectionError(f"'{text}' is not a field that can be corrected.")


def _index(digits: str) -> int:
    value = int(digits)
    if value > _MAX_INDEX:
        raise CorrectionError("The row number is out of range.")
    return value


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _clean_text(raw: str | None, *, limit: int, what: str = "value") -> str:
    """Control characters removed, whitespace collapsed; empty or over-long is refused (never silently cut)."""
    cleaned = " ".join("".join(ch for ch in (raw or "") if unicodedata.category(ch) != "Cc").split())
    if not cleaned:
        raise CorrectionError(f"The {what} is empty. To say the document does not state it, clear the value instead.")
    if len(cleaned) > limit:
        raise CorrectionError(f"The {what} is longer than {limit} characters.")
    return cleaned


def _clean_unit(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    unit = _clean_text(raw, limit=_UNIT_LIMIT, what="unit")
    if not _UNIT_CHARS.match(unit):
        raise CorrectionError("The unit contains characters a unit is not printed with.")
    return unit


def validate_value(
    address: Address, value: str, unit: str | None, *, existing_unit: str | None = None
) -> tuple[str, str | None]:
    """The (value, unit) to store for a correction, or ``CorrectionError`` explaining what to change.

    Values stay as the person typed them (like the model's, they are "as printed"), but each kind must be readable by the
    engines WITHOUT guessing: a number whose reading needs an assumption ("14,280": thousands or decimals?) is refused, a
    weight must carry a unit the engines know, a lab value must be a number, a "<number" or "ND".
    """
    kind = address.kind
    if kind == "doc_type":
        cleaned = _clean_text(value, limit=40, what="document type")
        if cleaned not in _DOC_TYPES:
            raise CorrectionError(f"Document type must be one of: {', '.join(_DOC_TYPES)}.")
        return cleaned, None

    if kind in ("text", "long_text", "heat"):
        limit = {"text": _TEXT_LIMIT, "long_text": _LONG_TEXT_LIMIT, "heat": _HEAT_LIMIT}[kind]
        return _clean_text(value, limit=limit), None

    if kind == "currency":
        cleaned = _clean_text(value, limit=20)
        if not _CURRENCY.match(cleaned):
            raise CorrectionError("A currency is a 3-letter code such as USD, INR or SGD.")
        return cleaned.upper(), None

    if kind == "hs":
        cleaned = _clean_text(value, limit=20)
        digits = hs_digits(cleaned)
        if not _HS_CHARS.match(cleaned) or not 4 <= len(digits) <= 10:
            raise CorrectionError("An HS code is 4 to 10 digits (dots and spaces allowed), for example 7304.19.00.")
        return cleaned, None

    if kind == "number":
        cleaned = _clean_text(value, limit=_TEXT_LIMIT)
        parsed = _read_number(cleaned)
        if address.field == "package_count" and not float(parsed).is_integer():
            raise CorrectionError("A package count is a whole number.")
        return cleaned, None

    if kind == "weight":
        cleaned = _clean_text(value, limit=_TEXT_LIMIT)
        number = _read_number(cleaned)
        printed = trailing_unit(cleaned)  # "14,280.50 KGS" typed into the value
        given = _clean_unit(unit)
        if printed and given and normalize_unit(printed) != normalize_unit(given):
            raise CorrectionError(f"The value says '{printed}' but the unit says '{given}'. State the unit once.")
        effective = given or existing_unit or printed
        if not effective:
            raise CorrectionError("State the unit of the weight (KGS, MT, LBS, ...).")
        converted = to_kg(number, effective)
        if converted.error:
            raise CorrectionError(f"{converted.error[0].upper()}{converted.error[1:]}.")
        return cleaned, given

    if kind == "lab":
        cleaned = _clean_text(value, limit=40)
        measure = parse_measure(cleaned, "%")  # the number's shape only: whether it is a % or MPa is the row's parameter
        if measure.error:
            raise CorrectionError(f"{measure.error[0].upper()}{measure.error[1:]}. Use a number, '<number' or 'ND'.")
        return cleaned, _clean_unit(unit)

    raise CorrectionError("This value cannot be corrected.")  # unreachable: every kind is handled above


def _read_number(text: str) -> float:
    parsed = parse_number(text)
    if parsed is None:
        raise CorrectionError(f"'{text}' is not a number.")
    if parsed.assumptions:
        raise CorrectionError(f"'{text}' is ambiguous ({parsed.assumptions[0]}). Write it without a thousands separator.")
    return parsed.value


# ---------------------------------------------------------------------------
# Reading and addressing the extraction (documents as plain dicts)
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def find_document(docs: list[dict[str, Any]], document_id: str) -> dict[str, Any] | None:
    return next((d for d in docs if d.get("document_id") == document_id), None)


def rows_of(doc: dict[str, Any], address: Address) -> list[Any]:
    key = "line_items" if address.scope == "line" else address.field
    rows = doc.get(key)
    return rows if isinstance(rows, list) else []


def _norm(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def row_anchor(address: Address, row: dict[str, Any]) -> str:
    """The identity of a row, stable when the table is read again: a heat and a parameter, a description, a heat number."""
    if address.scope == "line":
        description = row.get("description")
        return _norm(description.get("value") if isinstance(description, dict) else None)
    if address.field == "test_results":
        parameter = canonical_parameter(row.get("parameter")) or _norm(row.get("parameter")).upper()
        return f"{normalize_heat(row.get('heat_number'))}|{parameter}"
    return normalize_heat(row.get("value") if isinstance(row, dict) else None)


def resolve_index(doc: dict[str, Any], address: Address, anchor: str | None) -> int | None:
    """The index of the row a correction is for in ``doc``: the stored index when its anchor still matches, else the one
    row with that anchor; None when the row is gone or the anchor is ambiguous. Always None for a non-row address."""
    if address.scope not in ("line", "row") or address.index is None:
        return None
    rows = rows_of(doc, address)
    index = address.index
    if anchor is None:
        return index if 0 <= index < len(rows) else None
    if 0 <= index < len(rows) and isinstance(rows[index], dict) and row_anchor(address, rows[index]) == anchor:
        return index
    matches = [i for i, row in enumerate(rows) if isinstance(row, dict) and row_anchor(address, row) == anchor]
    return matches[0] if len(matches) == 1 else None


def read_value(doc: dict[str, Any], address: Address, index: int | None = None) -> tuple[str | None, str | None] | None:
    """(value, unit) the document currently has at the address; ``(None, None)`` for an empty field; None when the address
    does not exist (a row index out of range)."""
    if address.scope == "doc_type":
        return _stringify(doc.get("doc_type")), None
    if address.scope == "header":
        ref = doc.get(address.field)
    else:
        rows = rows_of(doc, address)
        at = address.index if index is None else index
        if at is None or not 0 <= at < len(rows) or not isinstance(rows[at], dict):
            return None
        ref = rows[at] if address.scope == "row" else rows[at].get(address.field)
    if not isinstance(ref, dict):
        return None, None
    return _stringify(ref.get("value")), _stringify(ref.get("unit")) if address.has_unit else None


# ---------------------------------------------------------------------------
# History -> overlay
# ---------------------------------------------------------------------------


def parse_events(events: list[dict[str, Any]]) -> list[CorrectionRecord]:
    """The correction history, oldest first, read from audit events; events of other types are ignored and an event whose
    payload does not fit is skipped (only this module's writers produce them, and the chain protects them from edits)."""
    records: list[CorrectionRecord] = []
    for event in events:
        event_type = event.get("event_type")
        if event_type not in _KIND_OF_EVENT:
            continue
        payload = event.get("payload") or {}
        fields: dict[str, Any] = {k: payload.get(k) for k in _PAYLOAD_KEYS}
        try:
            records.append(
                CorrectionRecord(
                    correction_id=f"cor-{int(event['seq'])}",
                    kind=_KIND_OF_EVENT[event_type],
                    seq=int(event["seq"]),
                    created_at=str(event.get("ts", "")),
                    iteration=int(event.get("iteration", 0)),
                    actor=str(event.get("actor", "user")),
                    **fields,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return records


_PAYLOAD_KEYS = (
    "document_id", "path", "anchor", "value", "unit", "original_value", "original_unit",
    "previous_value", "previous_unit", "reverts", "reason",
)


def effective(records: list[CorrectionRecord]) -> list[CorrectionRecord]:
    """The overlay in force: for each address the newest entry that has not been reverted, oldest first.

    A revert removes the entry it names, and nothing else: undoing the newest of two corrections of one value brings back
    the older one, undoing the only one brings back what the model read.
    """
    stacks: dict[tuple[str, str], list[CorrectionRecord]] = {}
    for record in records:
        if record.kind == "revert":
            for stack in stacks.values():
                stack[:] = [r for r in stack if r.correction_id != record.reverts]
        else:
            stacks.setdefault((record.document_id, record.path), []).append(record)
    return sorted((stack[-1] for stack in stacks.values() if stack), key=lambda r: r.seq)


def payload_of(record_fields: dict[str, Any]) -> dict[str, Any]:
    """The audit payload for an entry (keys in one place, so the writer and ``parse_events`` cannot drift apart)."""
    return {key: record_fields.get(key) for key in _PAYLOAD_KEYS}


# ---------------------------------------------------------------------------
# Applying the overlay
# ---------------------------------------------------------------------------


@dataclass
class ApplyResult:
    docs: list[dict[str, Any]]                # copies of the documents with the corrections laid on
    outcomes: list[AppliedCorrection]         # one per correction, in order


def apply(raw_docs: list[dict[str, Any]], corrections: list[CorrectionRecord]) -> ApplyResult:
    """Lay the corrections on a COPY of the extracted documents (``raw_docs`` is never changed).

    Corrected fields carry ``corrected: true`` and ``original_value`` / ``original_unit`` in the returned dicts (the
    ``/extractions`` endpoint shows them; the models the engines validate into ignore them). A correction that cannot be
    placed is reported as skipped with the reason, and changes nothing.
    """
    working = copy.deepcopy(raw_docs)
    outcomes: list[AppliedCorrection] = []

    for correction in corrections:
        outcome = _outcome(correction)
        doc = find_document(working, correction.document_id)
        base = find_document(raw_docs, correction.document_id)
        if doc is None or base is None:
            outcome.status, outcome.note = "skipped", "the document is not part of this analysis"
            outcomes.append(outcome)
            continue
        try:
            address = parse_path(correction.path)
        except CorrectionError as exc:
            outcome.status, outcome.note = "skipped", str(exc)
            outcomes.append(outcome)
            continue

        index = None
        if address.scope in ("line", "row"):
            index = resolve_index(base, address, correction.anchor)  # against what the model read: rows never shift in `working`
            if index is None:
                outcome.status = "skipped"
                outcome.note = "the row it was made for is no longer in the extraction (the table was read differently)"
                outcomes.append(outcome)
                continue

        _place(doc, address, index, correction)
        outcomes.append(outcome)

    return ApplyResult(working, outcomes)


def _outcome(correction: CorrectionRecord) -> AppliedCorrection:
    return AppliedCorrection(
        correction_id=correction.correction_id,
        seq=correction.seq,
        document_id=correction.document_id,
        path=correction.path,
        anchor=correction.anchor,
        value=correction.value,
        unit=correction.unit,
        original_value=correction.original_value,
        original_unit=correction.original_unit,
        reason=correction.reason,
        created_at=correction.created_at,
        status="applied",
    )


def _place(doc: dict[str, Any], address: Address, index: int | None, correction: CorrectionRecord) -> None:
    if address.scope == "doc_type":
        doc["doc_type_original"] = doc.get("doc_type_original") or doc.get("doc_type")
        doc["doc_type"] = correction.value
        doc["doc_type_confidence"] = 1.0
        doc["doc_type_corrected"] = True
        return

    ref: dict[str, Any]
    if address.scope == "header":
        found: Any = doc.get(address.field)
        if not isinstance(found, dict):
            found = doc[address.field] = {"value": None, "confidence": 1.0, "bbox": None}
        ref = found
    elif address.scope == "line":
        item = rows_of(doc, address)[index or 0]
        found = item.get(address.field)
        if not isinstance(found, dict):
            found = item[address.field] = {"value": None, "confidence": 1.0, "bbox": None}
        ref = found
    else:
        ref = rows_of(doc, address)[index or 0]

    ref.setdefault("original_value", _stringify(ref.get("value")))
    if address.has_unit:
        ref.setdefault("original_unit", _stringify(ref.get("unit")))
    ref["value"] = correction.value
    if address.has_unit and correction.unit is not None:
        ref["unit"] = correction.unit
    ref["confidence"] = 1.0
    ref["corrected"] = True
