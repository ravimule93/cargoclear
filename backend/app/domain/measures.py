"""Printed laboratory values: chemistry (weight %) and mechanical properties (MPa), read exactly as printed.

Pure functions, no I/O. Like ``units.py``, every function reports the ASSUMPTIONS it needed; the rule engines turn any
assumption into a WARN instead of a PASS/MATERIAL, so a verdict never rests on an undisclosed guess.

  parse_measure("0.18", "%")      -> Measure(0.18)
  parse_measure("<0.005", "%")    -> Measure(0.005, bound="upper")          # below the detection limit: at most 0.005
  parse_measure("5", "ppm")       -> Measure(0.0005)                         # 5 ppm = 0.0005 %
  parse_measure("0.18", None)     -> Measure(0.18, assumptions=["no unit printed; read as weight %"])
  to_mpa(42, "ksi")               -> 289.6...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Bound = Literal["exact", "upper", "lower"]

_PERCENT_UNITS = {"%", "WT%", "WT.%", "MASS%", "PCT", "PERCENT", "% BY WEIGHT", "WT %"}
_PPM_UNITS = {"PPM", "MG/KG", "MGKG"}
_NOT_DETECTED = {"ND", "N.D.", "N/D", "NIL", "NONE", "-", "--", "—", "TRACE"}


@dataclass(frozen=True)
class Measure:
    """A number read from a printed lab value, in weight % (chemistry) or in the unit asked for.

    ``value`` is None when the entry says "not detected" (``not_detected``) or cannot be read (``error``).
    ``bound`` is "upper" for "<x" / "≤x" (the true value is at most x) and "lower" for ">x"; "exact" otherwise.
    """

    value: float | None
    bound: Bound = "exact"
    not_detected: bool = False
    assumptions: list[str] = field(default_factory=list)
    error: str | None = None


def _number(text: str) -> float | None:
    """A plain decimal: "0.18", ".18", "0,18" (decimal comma), " 1.200 ". Percentages never carry thousands separators."""
    cleaned = text.strip().replace(" ", "")
    if cleaned.count(",") == 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    if not re.fullmatch(r"\d*\.?\d+|\d+\.", cleaned):
        return None
    return float(cleaned)


def _unit_key(unit: str | None) -> str | None:
    if unit is None or not str(unit).strip():
        return None
    return re.sub(r"\s+", " ", str(unit).strip().upper())


def parse_measure(raw: str | float | int | None, unit: str | None = "%") -> Measure:
    """Read a chemistry value as weight %.

    A "<" or "≤" prefix is an upper bound; "ND", "nil", "-" and "trace" are "not detected" (no value). ppm and mg/kg are
    converted. No unit is read as % and recorded as an assumption; an unrecognised unit is an error.
    """
    if raw is None or isinstance(raw, bool):
        return Measure(None, error="no value")
    text = str(raw).strip()
    if not text:
        return Measure(None, error="no value")
    if text.upper() in _NOT_DETECTED:
        return Measure(None, not_detected=True)

    bound: Bound = "exact"
    if text[0] in "<≤":
        bound, text = "upper", text.lstrip("<≤=").strip()
    elif text[0] in ">≥":
        bound, text = "lower", text.lstrip(">≥=").strip()
    number = _number(text)
    if number is None:
        return Measure(None, error=f"unreadable value '{raw}'")

    assumptions: list[str] = []
    key = _unit_key(unit)
    if key is None:
        assumptions.append("no unit printed; read as weight %")
    elif key in _PERCENT_UNITS:
        pass
    elif key in _PPM_UNITS:
        number /= 10_000.0
    else:
        return Measure(None, error=f"unrecognised unit '{unit}' for a chemistry value")
    return Measure(number, bound, assumptions=assumptions)


_MPA_FACTORS = {"MPA": 1.0, "N/MM2": 1.0, "N/MM²": 1.0, "KSI": 6.894757293, "PSI": 0.006894757293}


def to_mpa(value: float, unit: str | None) -> Measure:
    """A strength in MPa. No unit is read as MPa and recorded as an assumption; an unknown unit is an error."""
    key = _unit_key(unit)
    if key is None:
        return Measure(value, assumptions=["no unit printed; read as MPa"])
    factor = _MPA_FACTORS.get(key.replace(" ", ""))
    if factor is None:
        return Measure(None, error=f"unrecognised strength unit '{unit}'")
    return Measure(value * factor)


# ---------------------------------------------------------------------------
# parameter names
# ---------------------------------------------------------------------------

_PARAMETER_ALIASES: dict[str, str] = {
    **dict.fromkeys(("C", "CARBON"), "C"),
    **dict.fromkeys(("MN", "MANGANESE"), "Mn"),
    **dict.fromkeys(("SI", "SILICON"), "Si"),
    **dict.fromkeys(("P", "PHOSPHORUS", "PHOSPHOROUS"), "P"),
    **dict.fromkeys(("S", "SULPHUR", "SULFUR"), "S"),
    **dict.fromkeys(("CR", "CHROMIUM", "CHROME"), "Cr"),
    **dict.fromkeys(("NI", "NICKEL"), "Ni"),
    **dict.fromkeys(("MO", "MOLYBDENUM"), "Mo"),
    **dict.fromkeys(("CU", "COPPER"), "Cu"),
    **dict.fromkeys(("V", "VANADIUM"), "V"),
    **dict.fromkeys(("NB", "NIOBIUM", "CB", "COLUMBIUM"), "Nb"),
    **dict.fromkeys(("TI", "TITANIUM"), "Ti"),
    **dict.fromkeys(("AL", "ALUMINIUM", "ALUMINUM"), "Al"),
    **dict.fromkeys(("B", "BORON"), "B"),
    **dict.fromkeys(("CO", "COBALT"), "Co"),
    **dict.fromkeys(("PB", "LEAD"), "Pb"),
    **dict.fromkeys(("W", "TUNGSTEN"), "W"),
    **dict.fromkeys(("ZR", "ZIRCONIUM"), "Zr"),
    **dict.fromkeys(("N", "NITROGEN"), "N"),
    **dict.fromkeys(("YS", "YP", "YIELD", "YIELDSTRENGTH", "YIELDPOINT", "REH", "RP02", "RP0.2"), "YS"),
    **dict.fromkeys(("UTS", "TS", "TENSILE", "TENSILESTRENGTH", "RM"), "UTS"),
    **dict.fromkeys(("EL", "ELONGATION", "A5"), "EL"),
}

CHEMISTRY_ELEMENTS = ("C", "Mn", "Si", "P", "S", "Cr", "Ni", "Mo", "Cu", "V", "Nb", "Ti", "Al", "B", "Co", "Pb", "W", "Zr", "N")
MECHANICAL = ("YS", "UTS", "EL")


def canonical_parameter(raw: str | None) -> str | None:
    """The canonical symbol of a printed column heading ("Manganese" -> "Mn", "Yield Strength" -> "YS"), or None."""
    if raw is None:
        return None
    clean = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", str(raw))
    key = re.sub(r"[^A-Z0-9.]", "", clean.upper())
    return _PARAMETER_ALIASES.get(key) or _PARAMETER_ALIASES.get(key.replace(".", ""))


def normalize_heat(raw: str | None) -> str:
    """A heat number reduced for comparison: upper case, letters and digits only ("H-24-0881" == "h 24 0881" == "H240881")."""
    return re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())
