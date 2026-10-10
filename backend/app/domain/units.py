"""Unit layer: parse printed numbers and convert printed weights to kilograms.

Pure functions, no I/O. Every function reports the ASSUMPTIONS it had to make; the deterministic
rule engine (services/calculation.py) turns any assumption into a WARN instead of a PASS/MATERIAL, so a
compliance verdict never rests on an undisclosed guess.

  parse_number("14,280.50")  -> ParsedNumber(14280.5, [])
  parse_number("14,280")     -> ParsedNumber(14280.0, ["thousands separator assumed for '14,280'"])
  to_kg(14.28, "MT")         -> Quantity(kg=14280.0)
  to_kg(14000, None)         -> Quantity(kg=14000.0, assumptions=["no unit stated; assumed kg"])
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedNumber:
    """A number read from a printed value, plus the assumptions that were needed to read it."""

    value: float
    assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Quantity:
    """A weight expressed in kilograms.

    ``error`` is set when the unit could not be recognised; ``kg`` then merely echoes the printed
    number and callers must not compute with it.
    """

    kg: float
    assumptions: list[str] = field(default_factory=list)
    error: str | None = None


class UnknownUnit(ValueError):
    """A non-empty unit string that is not a recognised weight unit."""

    def __init__(self, raw: str) -> None:
        super().__init__(f"unrecognised unit '{raw}'")
        self.raw = raw


# ---------------------------------------------------------------------------
# B1  parse_number
# ---------------------------------------------------------------------------

# Space, no-break space, narrow no-break space, thin space, figure space: all read as a plain space.
_SPACE_CHARS = "    "
_SPACE_TABLE = {ord(c): " " for c in _SPACE_CHARS}

# "14,280.50 KGS", "14280KG", "5 M/T", "14 METRIC TONS": a number followed by a unit word.
_NUMBER_THEN_UNIT = re.compile(r"^(?P<num>.*[0-9])\s*(?P<unit>[A-Za-z][A-Za-z./ ]*)$", re.ASCII)
# digits grouped by single spaces, optionally followed by one decimal mark: "14 280.5", "1 234 567,5"
_SPACE_GROUPED = re.compile(r"^(?P<int>[0-9]{1,3}(?: [0-9]{3})+)(?:(?P<sep>[.,])(?P<frac>[0-9]+))?$")
_DIGITS = re.compile(r"^[0-9]+$")
_ONLY_NUMBER_CHARS = re.compile(r"^[0-9.,]+$")


def _groups_ok(parts: list[str]) -> bool:
    """First group 1-3 digits, every following group exactly 3 digits (a valid thousands grouping)."""
    return (
        len(parts) >= 2
        and _DIGITS.match(parts[0]) is not None
        and 1 <= len(parts[0]) <= 3
        and all(_DIGITS.match(p) is not None and len(p) == 3 for p in parts[1:])
    )


def _normalise_spaces(raw: str) -> str:
    return raw.translate(_SPACE_TABLE).strip()


def _split_trailing_unit(text: str) -> tuple[str, str | None]:
    """('14,280 KGS') -> ('14,280', 'KGS'); text without a trailing unit word is returned unchanged."""
    match = _NUMBER_THEN_UNIT.match(text)
    if match is None:
        return text, None
    return match.group("num").strip(), match.group("unit").strip()


def trailing_unit(raw: object) -> str | None:
    """The unit text printed inside a value string ("14,280 KGS" -> "KGS"), or None."""
    if not isinstance(raw, str):
        return None
    return _split_trailing_unit(_normalise_spaces(raw))[1] or None


def parse_number(raw: str | float | int | None) -> ParsedNumber | None:
    """Parse a printed weight/quantity; None when it is empty or not a plain non-negative number.

    Accepted: "14280", "14,280", "14,280.50", "14 280.5", "14280.50" (also no-break space grouping).
    If both "," and "." appear the LAST one is the decimal mark. A lone "," before exactly three digits is a
    thousands separator, before one or two digits a decimal comma; both are readings that need an assumption,
    which is recorded. A lone "." before exactly three digits ("14.280") is read as a decimal point, also
    recorded. A trailing unit word is ignored (use :func:`trailing_unit` / the `unit` field for it).
    Letters, signs, scientific notation, repeated decimal marks and malformed grouping give None.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return ParsedNumber(value) if math.isfinite(value) and value >= 0 else None
    if not isinstance(raw, str):
        return None

    text = _normalise_spaces(raw)
    if not text:
        return None
    text, _unit = _split_trailing_unit(text)  # the number part is never empty: it ends in a digit

    assumptions: list[str] = []

    if " " in text:
        grouped = _SPACE_GROUPED.match(text)
        if grouped is None:
            return None
        whole = grouped.group("int").replace(" ", "")
        sep, frac = grouped.group("sep"), grouped.group("frac")
        if sep == ",":
            assumptions.append(f"decimal comma assumed for '{raw.strip()}'")
        return ParsedNumber(float(f"{whole}.{frac}" if frac else whole), assumptions)

    if not _ONLY_NUMBER_CHARS.match(text):
        return None

    commas, dots = text.count(","), text.count(".")

    if commas and dots:
        last = max(text.rfind(","), text.rfind("."))
        decimal_mark = text[last]
        thousands_mark = "," if decimal_mark == "." else "."
        whole_part, frac = text[:last], text[last + 1:]
        if decimal_mark in whole_part or not _DIGITS.match(frac):
            return None
        parts = whole_part.split(thousands_mark)
        if not _groups_ok(parts):
            return None
        return ParsedNumber(float(f"{''.join(parts)}.{frac}"))

    if commas:
        if commas > 1:
            parts = text.split(",")
            return ParsedNumber(float("".join(parts))) if _groups_ok(parts) else None
        whole_part, frac = text.split(",")
        if not _DIGITS.match(whole_part) or not _DIGITS.match(frac):
            return None
        thousands_shape = len(frac) == 3 and 1 <= len(whole_part) <= 3 and not whole_part.startswith("0")
        if thousands_shape:
            assumptions.append(f"thousands separator assumed for '{raw.strip()}'")
            return ParsedNumber(float(whole_part + frac), assumptions)
        if len(frac) <= 3:
            assumptions.append(f"decimal comma assumed for '{raw.strip()}'")
            return ParsedNumber(float(f"{whole_part}.{frac}"), assumptions)
        return None

    if dots:
        if dots > 1:
            return None
        whole_part, frac = text.split(".")
        if not _DIGITS.match(whole_part) or not _DIGITS.match(frac):
            return None
        if len(frac) == 3 and 1 <= len(whole_part) <= 3 and not whole_part.startswith("0"):
            assumptions.append(f"decimal point assumed for '{raw.strip()}'")
        return ParsedNumber(float(f"{whole_part}.{frac}"), assumptions)

    return ParsedNumber(float(text))


# ---------------------------------------------------------------------------
# B2  normalize_unit
# ---------------------------------------------------------------------------

# Keys are the alias with everything but letters removed and upper-cased ("M/T" -> "MT", "KG." -> "KG").
# Plain "TON"/"TONS" are deliberately absent: a short ton is 907 kg, a long ton 1016 kg, a tonne 1000 kg.
_UNIT_ALIASES: dict[str, str] = {
    **dict.fromkeys(("KG", "KGS", "KILO", "KILOS", "KILOGRAM", "KILOGRAMS"), "KG"),
    **dict.fromkeys(
        ("MT", "TONNE", "TONNES", "TONSMETRIC", "TONMETRIC", "METRICTON", "METRICTONS"),
        "MT",
    ),
    **dict.fromkeys(("LB", "LBS", "POUND", "POUNDS"), "LB"),
    **dict.fromkeys(("G", "GM", "GRAM", "GRAMS"), "G"),
}


def normalize_unit(raw: str | None) -> str | None:
    """Canonical weight unit ("KG", "MT", "LB", "G") for a printed unit, or None if empty/unknown."""
    if raw is None:
        return None
    key = re.sub(r"[^A-Z]", "", str(raw).upper())
    return _UNIT_ALIASES.get(key)


def require_known_unit(raw: str | None) -> str | None:
    """Like :func:`normalize_unit`, but an unrecognised NON-EMPTY unit raises :class:`UnknownUnit`."""
    if raw is None or not str(raw).strip():
        return None
    canonical = normalize_unit(raw)
    if canonical is None:
        raise UnknownUnit(str(raw).strip())
    return canonical


# ---------------------------------------------------------------------------
# B3  to_kg
# ---------------------------------------------------------------------------

_LB_TO_KG = 0.45359237  # exact by definition of the international pound


def to_kg(value: float, unit: str | None) -> Quantity:
    """Convert a printed weight to kilograms, reporting any assumption or unit error."""
    if unit is None or not str(unit).strip():
        return Quantity(kg=value, assumptions=["no unit stated; assumed kg"])
    try:
        canonical = require_known_unit(unit)
    except UnknownUnit as exc:
        return Quantity(kg=value, error=f"unrecognised unit '{exc.raw}'")
    if canonical == "MT":
        return Quantity(kg=value * 1000.0)
    if canonical == "LB":
        return Quantity(kg=value * _LB_TO_KG)
    if canonical == "G":
        return Quantity(kg=value / 1000.0)
    return Quantity(kg=value)
