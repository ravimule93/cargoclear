"""The shape of the model's answer (the "wire shape") and how it becomes an ``ExtractedDocument``.

Why the answer is not shaped like ``ExtractedDocument``. Gemini compiles the response schema into a constrained-decoding grammar and
refuses one that is too large ("too many states for serving", HTTP 400). ``ExtractedDocument`` is nested: about 25 header fields, each
an object holding a value, a confidence and a box, plus line items and certificate rows. Measured against ``gemini-2.5-flash`` and
``gemini-3.5-flash`` (2026-10-14), that shape was refused, and so was every variant that kept the nesting: a string-only value, a
flatter box or all properties required each fitted only by a margin too thin to survive one more field. What the grammar pays for is the
number of distinct nested objects, not the number of bytes.

So the model is asked for lists of entries instead, each list with ONE object shape and the field name as an enum value:

    fields        one entry per header value: ``name`` (which field), ``value``, ``unit``, ``confidence``, ``page``, ``box``
    heat_numbers  one entry per heat, cast or lot number
    line_cells    one entry per value of a commodity line: ``row`` (the line's number), ``name`` (the column) and the same five
    test_results  one entry per certificate value: ``heat_number``, ``parameter`` and the same five

A new field is a new enum value, not a new nested object, so the grammar does not grow with it. ``answer_to_document`` rebuilds the
``ExtractedDocument``-shaped dict (no model is involved); everything after it (the sanitiser, ``ExtractedDocument.model_validate``, the
engines, the corrections, the audit trail) is unchanged. The field names are derived from ``ExtractedDocument`` and ``LineItem``
themselves, so a reference field added there is added here (``tests/unit/test_extraction_wire.py`` pins the schema's size).

``box`` is ``[ymin, xmin, ymax, xmax]`` normalised to 0-1000 (the order Gemini is trained to produce) and ``page`` sits beside it; the
rebuilt ``bbox`` is the ``{page, ymin, xmin, ymax, xmax}`` object the rest of the system uses.
"""

from __future__ import annotations

from typing import Any, Iterator, Literal, Optional, get_args, get_origin

from pydantic import BaseModel, Field

from app.domain.schemas import DocType, ExtractedDocument, FieldRef, LineItem, QuantityRef, TextRef

ExtractionWarning = dict[str, str]

# ---------------------------------------------------------------------------
# which fields exist, derived from the document model
# ---------------------------------------------------------------------------


def _classes(annotation: Any) -> Iterator[type]:
    if isinstance(annotation, type):
        yield annotation
    for arg in get_args(annotation):
        yield from _classes(arg)


def _kind(annotation: Any) -> str | None:
    """"quantity" (value and unit), "text" or "number" for a reference field; None for anything else. Subclasses first."""
    classes = list(_classes(annotation))
    for cls, kind in ((QuantityRef, "quantity"), (TextRef, "text"), (FieldRef, "number")):
        if any(issubclass(found, cls) for found in classes):
            return kind
    return None


def _scalar_reference_fields(model: type[BaseModel]) -> dict[str, str]:
    return {
        name: kind
        for name, field in model.model_fields.items()
        if get_origin(field.annotation) is not list and (kind := _kind(field.annotation)) is not None
    }


HEADER_FIELDS: dict[str, str] = _scalar_reference_fields(ExtractedDocument)  # name -> kind
LINE_FIELDS: dict[str, str] = _scalar_reference_fields(LineItem)
# A line item the document model cannot do without: a cell the model leaves out is rebuilt as "not printed" (null, confidence 0).
REQUIRED_LINE_FIELDS = tuple(name for name, field in LineItem.model_fields.items() if field.is_required())

HeaderName = Literal[tuple(HEADER_FIELDS)]  # type: ignore[valid-type]
LineName = Literal[tuple(LINE_FIELDS)]  # type: ignore[valid-type]

# ---------------------------------------------------------------------------
# the schema the model is given
# ---------------------------------------------------------------------------

_VALUE = "the value exactly as printed, as text; null if it is not legible"
_CONFIDENCE = "how clearly the value is printed, 0.0 to 1.0"
_PAGE = "1-based page number where the value is printed"
_BOX = "[ymin, xmin, ymax, xmax] of the printed value, normalised to 0-1000 from the top-left of the page"
_UNIT = "unit exactly as printed (for a weight: KGS, MT, LBS, ...; for a certificate value: %, ppm, MPa, ...); null if none is printed"


class HeaderEntry(BaseModel):
    name: HeaderName = Field(description="which header field this value is")  # type: ignore[valid-type]
    value: Optional[str] = Field(description=_VALUE)
    unit: Optional[str] = Field(description=_UNIT)
    confidence: float = Field(ge=0.0, le=1.0, description=_CONFIDENCE)
    page: Optional[int] = Field(description=_PAGE)
    box: Optional[list[float]] = Field(description=_BOX)


class HeatEntry(BaseModel):
    value: Optional[str] = Field(description="the heat, cast or lot number exactly as printed")
    confidence: float = Field(ge=0.0, le=1.0, description=_CONFIDENCE)
    page: Optional[int] = Field(description=_PAGE)
    box: Optional[list[float]] = Field(description=_BOX)


class LineEntry(BaseModel):
    row: int = Field(description="the 1-based number of the commodity line in the table; every value of one line has the same row")
    name: LineName = Field(description="which column of the line this value is")  # type: ignore[valid-type]
    value: Optional[str] = Field(description=_VALUE)
    unit: Optional[str] = Field(description=_UNIT)
    confidence: float = Field(ge=0.0, le=1.0, description=_CONFIDENCE)
    page: Optional[int] = Field(description=_PAGE)
    box: Optional[list[float]] = Field(description=_BOX)


class LabEntry(BaseModel):
    heat_number: Optional[str] = Field(description="heat / cast / lot id of the row this value is in, as printed")
    parameter: str = Field(description="column heading as printed: element symbol (C, Mn, Cr, ...) or YS / UTS / EL")
    value: Optional[str] = Field(description=_VALUE)
    unit: Optional[str] = Field(description=_UNIT)
    confidence: float = Field(ge=0.0, le=1.0, description=_CONFIDENCE)
    page: Optional[int] = Field(description=_PAGE)
    box: Optional[list[float]] = Field(description=_BOX)


class Answer(BaseModel):
    """What the model is asked to return. Every property is required (a list may be empty), in this order."""

    doc_type: DocType
    doc_type_confidence: float = Field(ge=0.0, le=1.0)
    fields: list[HeaderEntry] = Field(description="one entry per header value that is printed on the document")
    heat_numbers: list[HeatEntry] = Field(description="every heat / cast / lot number printed on the document, each once")
    line_cells: list[LineEntry] = Field(description="one entry per value of each commodity line item")
    test_results: list[LabEntry] = Field(description="every chemistry and mechanical value printed: one entry per heat and parameter")


# ---------------------------------------------------------------------------
# answer -> ExtractedDocument-shaped dict (no model, no I/O)
# ---------------------------------------------------------------------------


def is_answer(raw: Any) -> bool:
    """True for an answer in the wire shape. An ``ExtractedDocument``-shaped dict (stored or fake answers) has neither key."""
    return isinstance(raw, dict) and ("fields" in raw or "line_cells" in raw)


def _entries(raw: dict[str, Any], key: str, warnings: list[ExtractionWarning]) -> list[tuple[int, dict[str, Any]]]:
    found = raw.get(key)
    if found is None:
        return []
    if not isinstance(found, list):
        warnings.append({"path": key, "reason": "not a list; ignored"})
        return []
    out = []
    for index, entry in enumerate(found):
        if isinstance(entry, dict):
            out.append((index, entry))
        else:
            warnings.append({"path": f"{key}[{index}]", "reason": "entry is not an object; dropped"})
    return out


def _bbox(entry: dict[str, Any], page_count: int | None) -> Any:
    """The ``bbox`` of an entry. A malformed box is passed on in a form the sanitiser rejects, so it is dropped with a reason."""
    box = entry.get("box")
    if box is None:
        return None
    if not isinstance(box, (list, tuple)):
        return box  # not a list: the sanitiser reports "bbox is not an object"
    if len(box) != 4:
        return {"page": entry.get("page")}  # incomplete: the sanitiser reports the missing coordinate
    page = entry.get("page")
    if page is None and page_count == 1:
        page = 1  # one page was sent: the page is not in doubt
    return {"page": page, "ymin": box[0], "xmin": box[1], "ymax": box[2], "xmax": box[3]}


def _reference(entry: dict[str, Any], kind: str, page_count: int | None) -> dict[str, Any]:
    node: dict[str, Any] = {
        "value": entry.get("value"),
        "confidence": entry.get("confidence", 0.0),
        "bbox": _bbox(entry, page_count),
    }
    if kind == "quantity":
        node["unit"] = entry.get("unit")
    return node


def _row_key(entry: dict[str, Any]) -> int | None:
    row = entry.get("row")
    if isinstance(row, bool):
        return None
    if isinstance(row, int):
        return row
    if isinstance(row, float) and row.is_integer():
        return int(row)
    return None


def answer_to_document(raw: dict[str, Any], page_count: int | None = None) -> tuple[dict[str, Any], list[ExtractionWarning]]:
    """The ``ExtractedDocument``-shaped dict (without ``document_id``) that the model's answer describes, and a warning for every
    entry that could not be placed: an unknown name, a second value for a single-valued field, a line value without a usable row.
    Nothing the model said is changed; what is dropped is only what has no place. A required line cell the model left out is
    rebuilt as "not printed" (``value`` null, ``confidence`` 0.0), which is what the prompt asks for. Warnings carry paths and
    reasons only, never a value or a name taken from the document."""
    warnings: list[ExtractionWarning] = []
    out: dict[str, Any] = {"doc_type": raw.get("doc_type"), "doc_type_confidence": raw.get("doc_type_confidence")}

    for index, entry in _entries(raw, "fields", warnings):
        name = entry.get("name")
        kind = HEADER_FIELDS.get(name) if isinstance(name, str) else None
        if kind is None:
            warnings.append({"path": f"fields[{index}]", "reason": "not a known header field; dropped"})
        elif name in out:
            warnings.append({"path": f"fields[{index}]", "reason": "a second value for a field that has one; dropped"})
        else:
            out[name] = _reference(entry, kind, page_count)

    out["heat_numbers"] = [_reference(entry, "text", page_count) for _, entry in _entries(raw, "heat_numbers", warnings)]

    out["test_results"] = []
    for _, entry in _entries(raw, "test_results", warnings):
        row = _reference(entry, "text", page_count)
        row.update(parameter=entry.get("parameter"), heat_number=entry.get("heat_number"), unit=entry.get("unit"))
        out["test_results"].append(row)

    lines: dict[int, dict[str, Any]] = {}
    for index, entry in _entries(raw, "line_cells", warnings):
        row, name = _row_key(entry), entry.get("name")
        kind = LINE_FIELDS.get(name) if isinstance(name, str) else None
        if row is None:
            warnings.append({"path": f"line_cells[{index}]", "reason": "row is not a whole number; dropped"})
        elif kind is None:
            warnings.append({"path": f"line_cells[{index}]", "reason": "not a known line field; dropped"})
        elif name in lines.setdefault(row, {}):
            warnings.append({"path": f"line_cells[{index}]", "reason": "a second value for a line field that has one; dropped"})
        else:
            lines[row][name] = _reference(entry, kind, page_count)
    out["line_items"] = []
    for row in sorted(lines):  # the document's own numbering; lines of equal number cannot occur (they are one line)
        item = lines[row]
        for name in REQUIRED_LINE_FIELDS:
            item.setdefault(name, {"value": None, "confidence": 0.0, "bbox": None})
        out["line_items"].append(item)
    return out, warnings


# ---------------------------------------------------------------------------
# ExtractedDocument -> answer (the inverse: fixtures, fakes and tests)
# ---------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _entry(ref: FieldRef) -> dict[str, Any]:
    box = ref.bbox
    return {
        "value": _text(ref.value),
        "unit": getattr(ref, "unit", None),
        "confidence": ref.confidence,
        "page": None if box is None else box.page,
        "box": None if box is None else [box.ymin, box.xmin, box.ymax, box.xmax],
    }


def document_to_answer(doc: ExtractedDocument) -> dict[str, Any]:
    """The answer a faithful model would give for ``doc``: ``answer_to_document`` of it is ``doc`` again (values as text)."""
    fields = [{"name": name, **_entry(ref)} for name in HEADER_FIELDS if (ref := getattr(doc, name)) is not None]
    heats = [{k: v for k, v in _entry(ref).items() if k != "unit"} for ref in doc.heat_numbers]
    cells = [
        {"row": number, "name": name, **_entry(ref)}
        for number, item in enumerate(doc.line_items, start=1)
        for name in LINE_FIELDS
        if (ref := getattr(item, name)) is not None
    ]
    results = [{"heat_number": row.heat_number, "parameter": row.parameter, **_entry(row)} for row in doc.test_results]
    return {
        "doc_type": doc.doc_type,
        "doc_type_confidence": doc.doc_type_confidence,
        "fields": fields,
        "heat_numbers": heats,
        "line_cells": cells,
        "test_results": results,
    }
