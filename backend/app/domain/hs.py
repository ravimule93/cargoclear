"""HS (Harmonized System) code helpers: the single source of truth for reading and comparing codes.

Pure functions, no I/O. Used by the H-002 consistency check (services/calculation.py) and by tariff
grounding (agents/grounding.py), so that the same declared code gets the same reading everywhere:
"7304.19.00", "7304 19 00", 73041900 and 73041900.0 are all 73041900.
"""

from __future__ import annotations

import re
from typing import Any, Literal

HS_FULL_DIGITS: int = 8   # AHTN
HS_MIN_DIGITS: int = 6    # HS international (sub-heading)

HsMatchLevel = Literal["exact8", "subheading6", "heading4", "none", "not_declared"]

# Documents that certify a test or an origin rather than describe the goods. They state an HS code (checked against
# the invoice by H-003) but their line text is not a commodity description (so grounding does not look it up).
CERTIFICATE_DOC_TYPES: tuple[str, ...] = ("MILL_TEST_CERTIFICATE", "CERTIFICATE_OF_ORIGIN", "PHYTOSANITARY")

_HEADING_DIGITS = 4


def hs_text(value: Any) -> str:
    """Printed form of a declared code; whole-number floats lose their '.0' (73041900.0 -> '73041900')."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def hs_digits(value: Any) -> str:
    """The digits of a code and nothing else ('7304.19.00' -> '73041900'); '' when it has none."""
    return re.sub(r"\D", "", hs_text(value))


def hs_match_level(declared: str | float | int | None, candidate: str) -> HsMatchLevel:
    """How closely a declared code matches a tariff candidate, compared on digits only.

    - "not_declared": nothing usable declared (None, or fewer than 6 digits)
    - "exact8":       the first 8 digits are equal and the declaration states at least 8
                      (10-digit national lines compare on their first 8)
    - "subheading6":  the first 6 digits are equal (the 8-digit code is not confirmed)
    - "heading4":     the first 4 digits are equal (same heading, different subheading)
    - "none":         otherwise
    """
    declared_digits = hs_digits(declared)
    if len(declared_digits) < HS_MIN_DIGITS:
        return "not_declared"
    candidate_digits = hs_digits(candidate)
    if len(declared_digits) >= HS_FULL_DIGITS and declared_digits[:HS_FULL_DIGITS] == candidate_digits[:HS_FULL_DIGITS]:
        return "exact8"
    if declared_digits[:HS_MIN_DIGITS] == candidate_digits[:HS_MIN_DIGITS]:
        return "subheading6"
    if declared_digits[:_HEADING_DIGITS] == candidate_digits[:_HEADING_DIGITS]:
        return "heading4"
    return "none"


def hs_evidence_entry(
    doc_id: str,
    field_name: str,
    ref: Any = None,
    *,
    line_item: int | None = None,
) -> dict[str, Any]:
    """An evidence dict pointing at a declared HS field.

    ``{doc, field}`` plus, when known, ``line_item`` (index of the line), ``page`` and ``bbox`` (only when the
    field has a bounding box, so the UI draws a box exactly where one is known) and ``raw_value`` (as declared).
    """
    entry: dict[str, Any] = {"doc": doc_id, "field": field_name}
    if line_item is not None:
        entry["line_item"] = line_item
    bbox = getattr(ref, "bbox", None)
    if bbox is not None:
        entry["page"] = bbox.page
        entry["bbox"] = bbox.model_dump()
    raw = hs_text(getattr(ref, "value", None))
    if raw:
        entry["raw_value"] = raw
    return entry
