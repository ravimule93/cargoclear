"""Evidence entries: how a check points at the printed values it is built on.

An entry is ``{doc, field}`` plus, when known, ``line_item`` (index of the line) or ``row`` (index in a document list such
as ``test_results`` / ``heat_numbers``), ``page`` and ``bbox`` (only when the value has a box, so the UI draws a box
exactly where one is known) and ``raw_value`` (as printed) and ``unit`` (as printed, for weights and lab values). Confidence routing resolves entries back to values with
the same keys (services/confidence.py).
"""

from __future__ import annotations

from typing import Any


def evidence_entry(
    doc_id: str,
    field_name: str,
    ref: Any = None,
    *,
    line_item: int | None = None,
    row: int | None = None,
    raw_value: Any = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"doc": doc_id, "field": field_name}
    if line_item is not None:
        entry["line_item"] = line_item
    if row is not None:
        entry["row"] = row
    bbox = getattr(ref, "bbox", None)
    if bbox is not None:
        entry["page"] = bbox.page
        entry["bbox"] = bbox.model_dump()
    printed = raw_value if raw_value is not None else getattr(ref, "value", None)
    if printed is not None and str(printed).strip() != "":
        entry["raw_value"] = printed if not isinstance(printed, float) else (int(printed) if printed.is_integer() else printed)
    unit = getattr(ref, "unit", None)
    if unit is not None and str(unit).strip() != "":
        entry["unit"] = str(unit).strip()  # the unit as printed, for a weight or a lab value
    return entry
