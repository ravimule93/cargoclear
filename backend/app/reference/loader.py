"""Loads and validates the curated reference data (the JSON files next to this module).

Why a loader with strict models: a rule table decides verdicts. A misspelt key or a rate typed as text must stop the
service at start-up (``require_reference`` is called from the lifespan), not quietly become "no rule found". Models
forbid unknown keys for the same reason.

Every table carries its own provenance (``rule_set`` + ``regulation_ref``) and a ``verification`` block. The rule sets
are labelled ``demo-curated`` until a reviewer replaces that label: the application never presents them as official.
``fingerprint()`` gives each file's SHA-256 prefix; it is stored with every assessment iteration, so a verdict can be
tied to the exact tables it was computed from.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.hs import hs_digits

REFERENCE_DIR = Path(__file__).resolve().parent

AlloyClass = Literal["non_alloy", "alloy", "stainless", "any"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Verification(_Strict):
    status: Literal["unverified", "verified"] = "unverified"
    reviewer: str | None = None
    date: str | None = None


class _Table(_Strict):
    rule_set: str
    regulation_ref: str
    verification: Verification


# ---------------------------------------------------------------------------
# hs_rules.json
# ---------------------------------------------------------------------------


class AlloyRule(_Strict):
    prefix: str
    alloy_class: AlloyClass = Field(alias="class")


class StainlessRule(_Strict):
    cr_min_pct: float
    c_max_pct: float


class HsRules(_Table):
    note_1f_alloy_thresholds_pct: dict[str, float]
    stainless: StainlessRule
    alloy_class_by_prefix: list[AlloyRule]
    alloy_twin_subheading: dict[str, dict[str, str]]

    def alloy_class_of(self, hs: str) -> AlloyRule | None:
        """The rule of the LONGEST prefix that matches the code's digits, or None."""
        digits = hs_digits(hs)
        matches = [rule for rule in self.alloy_class_by_prefix if digits.startswith(rule.prefix)]
        return max(matches, key=lambda rule: len(rule.prefix), default=None)


# ---------------------------------------------------------------------------
# specs.json
# ---------------------------------------------------------------------------


class MechanicalLimit(_Strict):
    min: float | None = None
    max: float | None = None
    unit: str = "MPa"


class SpecEntry(_Strict):
    id: str
    title: str
    match_all: list[str]
    element_max_pct: dict[str, float]
    element_min_pct: dict[str, float]
    ce_iiw_max: float | None
    pcm_max: float | None
    pcm_applies_when_c_at_most: float | None
    mechanical: dict[str, MechanicalLimit]
    assumes: list[str]


class Specs(_Table):
    specs: list[SpecEntry]

    def match(self, text: str | None) -> SpecEntry | None:
        """The spec whose every ``match_all`` pattern is found in the printed specification; None if none (or several
        match: an ambiguous specification is not guessed at)."""
        import re

        if not text:
            return None
        upper = text.upper()
        found = [s for s in self.specs if all(re.search(pattern, upper) for pattern in s.match_all)]
        return found[0] if len(found) == 1 else None


# ---------------------------------------------------------------------------
# duty_rates.json, valuation_defaults.json, exchange_rates.json, anti_dumping.json
# ---------------------------------------------------------------------------


class DutyEntry(_Strict):
    prefix: str
    bcd_pct: float | None = None
    sws_pct_of_bcd: float | None = None
    igst_pct: float | None = None
    customs_duty_pct: float | None = None
    gst_pct: float | None = None


class DutyDestination(_Strict):
    currency: str
    model: Literal["IN_BCD_SWS_IGST", "SG_GST"]
    note: str
    entries: list[DutyEntry]

    def entry_for(self, hs: str) -> DutyEntry | None:
        digits = hs_digits(hs)
        matches = [e for e in self.entries if digits.startswith(e.prefix)]
        return max(matches, key=lambda e: len(e.prefix), default=None)


class DutyRates(_Table):
    destinations: dict[str, DutyDestination]


class ValuationDefault(_Strict):
    freight_pct_of_fob: float | None
    insurance_pct_of_fob: float | None


class ValuationDefaults(_Table):
    destinations: dict[str, ValuationDefault]


class FxRate(_Strict):
    from_: str = Field(alias="from")
    to: str
    rate: float
    effective_from: str | None
    reference: str | None
    illustrative: bool


class ExchangeRates(_Table):
    rates: list[FxRate]

    def rate(self, source: str, target: str) -> FxRate | None:
        if source == target:
            return FxRate.model_validate({"from": source, "to": target, "rate": 1.0, "effective_from": None,
                                          "reference": None, "illustrative": False})
        return next((r for r in self.rates if r.from_ == source and r.to == target), None)


class AntiDumpingEntry(_Strict):
    id: str
    destination: str
    origins: list[str]
    hs_prefixes: list[str]
    scope: str
    rate_pct_of_assessable_value: float
    notification_ref: str | None
    valid_from: str | None
    valid_until: str | None
    producer_specific: bool


class AntiDumping(_Table):
    entries: list[AntiDumpingEntry]

    def matches(self, destination: str, origin: str, hs: str) -> list[AntiDumpingEntry]:
        digits = hs_digits(hs)
        return [
            e for e in self.entries
            if e.destination == destination and origin in e.origins and any(digits.startswith(p) for p in e.hs_prefixes)
        ]


# ---------------------------------------------------------------------------
# declaration_inputs.json
# ---------------------------------------------------------------------------


class DeclarationInput(_Strict):
    id: str
    label: str


class DeclarationDestination(_Strict):
    declaration: str
    inputs: list[DeclarationInput]


class DeclarationInputs(_Table):
    """What the declarant must supply that no trade document carries, per destination (the pre-fill pack lists it)."""

    destinations: dict[str, DeclarationDestination]
    default: DeclarationDestination

    def for_destination(self, destination: str) -> DeclarationDestination:
        return self.destinations.get(destination.upper(), self.default)


# ---------------------------------------------------------------------------
# the whole set
# ---------------------------------------------------------------------------

FILES: dict[str, tuple[str, type[_Table]]] = {
    "hs_rules": ("hs_rules.json", HsRules),
    "specs": ("specs.json", Specs),
    "duty_rates": ("duty_rates.json", DutyRates),
    "valuation_defaults": ("valuation_defaults.json", ValuationDefaults),
    "exchange_rates": ("exchange_rates.json", ExchangeRates),
    "anti_dumping": ("anti_dumping.json", AntiDumping),
    "declaration_inputs": ("declaration_inputs.json", DeclarationInputs),
}


class Reference(_Strict):
    hs_rules: HsRules
    specs: Specs
    duty_rates: DutyRates
    valuation_defaults: ValuationDefaults
    exchange_rates: ExchangeRates
    anti_dumping: AntiDumping
    declaration_inputs: DeclarationInputs


def load_reference(directory: Path = REFERENCE_DIR) -> Reference:
    """Read and validate every table in ``directory``; raises ``pydantic.ValidationError`` / ``FileNotFoundError``."""
    tables = {
        name: model.model_validate(json.loads((directory / filename).read_text(encoding="utf-8")))
        for name, (filename, model) in FILES.items()
    }
    return Reference.model_validate(tables)


@lru_cache(maxsize=1)
def get_reference() -> Reference:
    """The reference data, loaded once per process."""
    return load_reference()


def require_reference() -> Reference:
    """Called at start-up: a broken table stops the service here, not in the middle of an assessment."""
    return get_reference()


def fingerprint(directory: Path = REFERENCE_DIR) -> dict[str, str]:
    """{file name: first 16 hex chars of its SHA-256}: which exact tables an assessment used."""
    if directory == REFERENCE_DIR:
        return dict(_default_fingerprint())
    return _fingerprint_of(directory)


def _fingerprint_of(directory: Path) -> dict[str, str]:
    return {
        filename: hashlib.sha256((directory / filename).read_bytes()).hexdigest()[:16]
        for filename, _model in FILES.values()
    }


@lru_cache(maxsize=1)
def _default_fingerprint() -> tuple[tuple[str, str], ...]:
    """The shipped tables do not change while the process runs: hash them once."""
    return tuple(_fingerprint_of(REFERENCE_DIR).items())
