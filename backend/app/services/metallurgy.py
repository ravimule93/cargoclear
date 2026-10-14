"""Material engine: what a Mill Test Certificate says about the steel, checked against the declaration.

Pure Python, no I/O, no LLM. The model only READS the certificate (heats, chemistry, strengths, as printed); everything
below is deterministic arithmetic on those printed values and on the curated tables in ``app/reference``. As in the rest
of the engine, a result that rests on an assumption is a WARN; PASS / MATERIAL are reserved for results computed from
what the documents state. Every check names the rule set it used (``rule_set`` / ``regulation_ref``).

  M-001  Alloy status. HS Chapter 72 Note 1(f) says a steel is ALLOY steel when any listed element reaches its threshold
         (Cr 0.30 %, Mn 1.65 %, B 0.0008 % ...), stainless above 10.5 % Cr. The certificate's chemistry is read this way
         ("as certified": any heat decides) and compared with what the declared HS code says (reference ``hs_rules``).
         Heading 7304 splits non-alloy from alloy tubes (7304.31/.39 vs 7304.51/.59) but not line pipe (7304.19).
  M-002  Carbon equivalent (IIW), or Pcm for low-carbon heats, against the limit of the certificate's own specification.
  M-003  Composition and strength limits of that specification, heat by heat.
  M-004  Traceability: every heat on the packing list is on a certificate.

A certificate can satisfy its own standard and still contradict a non-alloy declaration (ASTM A106 allows 0.40 % Cr;
Note 1(f) makes a steel alloy at 0.30 %): M-001 and M-003 are independent on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.domain.evidence import evidence_entry
from app.domain.hs import hs_digits, hs_text
from app.domain.measures import (
    CHEMISTRY_ELEMENTS,
    Measure,
    canonical_parameter,
    normalize_heat,
    parse_measure,
    to_mpa,
)
from app.domain.schemas import CheckResult, ExtractedDocument, LabResult
from app.domain.units import parse_number
from app.reference.loader import Reference, SpecEntry, get_reference

CHEMISTRY = set(CHEMISTRY_ELEMENTS)
NEAR_THRESHOLD_FRACTION = 0.8  # trade_remedies.py: "within 20 % below an alloy threshold"
_ALLOY_RANK = {"non_alloy": 0, "indeterminate": 1, "alloy": 2, "stainless": 3}


# ---------------------------------------------------------------------------
# reading a certificate
# ---------------------------------------------------------------------------


@dataclass
class Reading:
    """One printed value of one heat, parsed."""

    param: str
    measure: Measure
    row: int
    ref: LabResult
    doc: ExtractedDocument

    @property
    def value(self) -> float | None:
        return self.measure.value

    @property
    def exact(self) -> bool:
        return self.measure.value is not None and self.measure.bound == "exact"

    def printed(self) -> str:
        unit = (self.ref.unit or "").strip()
        sep = "" if unit in ("", "%") else " "
        return f"{self.ref.value}{sep}{unit}".strip()

    def evidence(self, heat: str) -> dict[str, Any]:
        label = f"{heat or 'heat not stated'}: {self.param} {self.printed()}"
        return evidence_entry(self.doc.document_id, "test_results", self.ref, row=self.row, raw_value=label)


@dataclass
class Heat:
    key: str
    label: str
    doc: ExtractedDocument
    readings: dict[str, Reading] = field(default_factory=dict)

    def value(self, element: str) -> float | None:
        reading = self.readings.get(element)
        return reading.value if reading is not None and reading.exact else None


def _read_row(doc: ExtractedDocument, index: int, row: LabResult) -> Reading | None:
    param = canonical_parameter(row.parameter)
    if param is None:
        return None
    if param in CHEMISTRY or param == "EL":
        return Reading(param, parse_measure(row.value, row.unit), index, row, doc)
    # YS / UTS: a strength; a trailing unit inside the value counts as stated
    parsed = parse_number(row.value)
    if parsed is None:
        return Reading(param, Measure(None, error=f"unreadable value '{row.value}'"), index, row, doc)
    measure = to_mpa(parsed.value, row.unit)
    return Reading(param, Measure(measure.value, measure.bound, assumptions=[*parsed.assumptions, *measure.assumptions], error=measure.error), index, row, doc)


def certificates(docs: list[ExtractedDocument]) -> list[ExtractedDocument]:
    return [d for d in docs if d.doc_type == "MILL_TEST_CERTIFICATE"]


def collect_heats(doc: ExtractedDocument) -> list[Heat]:
    """The heats of one certificate, in the order they are printed, each with its parsed readings."""
    heats: dict[str, Heat] = {}
    for index, row in enumerate(doc.test_results):
        reading = _read_row(doc, index, row)
        if reading is None:
            continue
        key = normalize_heat(row.heat_number)
        heat = heats.setdefault(key, Heat(key=key, label=(row.heat_number or "").strip(), doc=doc))
        heat.readings.setdefault(reading.param, reading)  # a repeated column keeps its first value
    return list(heats.values())


def heat_numbers_of(doc: ExtractedDocument) -> dict[str, tuple[str, int | None, Any]]:
    """{normalized heat: (as printed, row index in heat_numbers or None, ref)} for a document: its heat-number cells, and,
    for a certificate, the heats named by its test results."""
    found: dict[str, tuple[str, int | None, Any]] = {}
    for index, cell in enumerate(doc.heat_numbers):
        printed = hs_text(cell.value)
        for part in _split_heats(printed):
            found.setdefault(normalize_heat(part), (part, index, cell))
    for row in doc.test_results:
        if row.heat_number and normalize_heat(row.heat_number) not in found:
            found[normalize_heat(row.heat_number)] = (row.heat_number.strip(), None, None)
    return {key: value for key, value in found.items() if key}


def _split_heats(text: str) -> list[str]:
    """"H1, H2 / H3; H4" -> ["H1", "H2", "H3", "H4"]: a cell may list several heats. Whitespace is NOT a separator
    ("H 24 0881" is one heat); a space-separated list is recognised at comparison time (``_covered``)."""
    import re

    return [part.strip() for part in re.split(r"[,;/\n]+", text) if part.strip()]


def _covered(printed: str, certified: dict[str, Any]) -> bool:
    """Is a heat as printed on the packing list a certified heat? Either as a whole, or as a space-separated list of them."""
    if normalize_heat(printed) in certified:
        return True
    parts = [normalize_heat(part) for part in printed.split()]
    return len(parts) > 1 and all(part in certified for part in parts)


# ---------------------------------------------------------------------------
# Note 1(f): alloy status of a heat
# ---------------------------------------------------------------------------


@dataclass
class HeatClass:
    heat: Heat
    alloy_class: str                                   # non_alloy | alloy | stainless | indeterminate
    triggers: list[tuple[str, Reading, float]] = field(default_factory=list)       # (element, reading, threshold) at/above
    near: list[tuple[str, Reading, float]] = field(default_factory=list)           # within 20 % below an alloy threshold
    unclear: list[tuple[str, Reading, float]] = field(default_factory=list)        # "<x" with x at/above the threshold


def classify_heat(heat: Heat, reference: Reference) -> HeatClass:
    rules = reference.hs_rules
    chromium, carbon = heat.value("Cr"), heat.value("C")
    if chromium is not None and chromium >= rules.stainless.cr_min_pct and (carbon is None or carbon <= rules.stainless.c_max_pct):
        return HeatClass(heat, "stainless", triggers=[("Cr", heat.readings["Cr"], rules.stainless.cr_min_pct)])

    triggers: list[tuple[str, Reading, float]] = []
    near: list[tuple[str, Reading, float]] = []
    unclear: list[tuple[str, Reading, float]] = []
    for element, threshold in rules.note_1f_alloy_thresholds_pct.items():
        reading = heat.readings.get(element)
        if reading is None or reading.value is None:
            continue
        if reading.measure.bound == "upper":
            if reading.value >= threshold:
                unclear.append((element, reading, threshold))
        elif reading.value >= threshold:
            triggers.append((element, reading, threshold))
        elif reading.value >= NEAR_THRESHOLD_FRACTION * threshold and reading.value > 0:
            near.append((element, reading, threshold))
    if triggers:
        return HeatClass(heat, "alloy", triggers, near, unclear)
    return HeatClass(heat, "indeterminate" if unclear else "non_alloy", [], near, unclear)


@dataclass
class AlloyAssessment:
    """What the certificates' chemistry says, over every heat of every certificate."""

    alloy_class: str                                   # the worst heat decides
    heats: list[HeatClass]
    reported: set[str]
    thresholds: dict[str, float]

    @property
    def not_reported(self) -> list[str]:
        return [element for element in self.thresholds if element not in self.reported]

    def deciding(self) -> HeatClass:
        """The heat that sets the class: the first one of the worst class."""
        return max(self.heats, key=lambda h: _ALLOY_RANK[h.alloy_class])


def assess_alloy_status(docs: list[ExtractedDocument], reference: Reference | None = None) -> AlloyAssessment | None:
    """None when no certificate states any chemistry."""
    reference = reference or get_reference()
    classes: list[HeatClass] = []
    reported: set[str] = set()
    for certificate in certificates(docs):
        for heat in collect_heats(certificate):
            if not any(p in CHEMISTRY and r.value is not None for p, r in heat.readings.items()):
                continue
            classes.append(classify_heat(heat, reference))
            reported |= {p for p, r in heat.readings.items() if p in CHEMISTRY and r.value is not None}
    if not classes:
        return None
    worst = max(classes, key=lambda h: _ALLOY_RANK[h.alloy_class]).alloy_class
    return AlloyAssessment(worst, classes, reported, reference.hs_rules.note_1f_alloy_thresholds_pct)


@dataclass
class DeclaredCode:
    digits: str
    doc: ExtractedDocument
    field_name: str
    line_item: int | None
    ref: Any


def declared_codes(docs: list[ExtractedDocument]) -> list[DeclaredCode]:
    """The HS codes the goods are declared under: the commercial invoice's (else the packing list's), one entry per distinct
    code, with the field to cite."""
    for wanted in ("COMMERCIAL_INVOICE", "PACKING_LIST"):
        doc = next((d for d in docs if d.doc_type == wanted), None)
        if doc is None:
            continue
        found: dict[str, DeclaredCode] = {}
        for index, item in enumerate(doc.line_items):
            digits = hs_digits(item.hs_code_declared.value) if item.hs_code_declared else ""
            if len(digits) >= 6:
                found.setdefault(digits, DeclaredCode(digits, doc, "hs_code_declared", index, item.hs_code_declared))
        if doc.hs_code_header and len(hs_digits(doc.hs_code_header.value)) >= 6:
            digits = hs_digits(doc.hs_code_header.value)
            found.setdefault(digits, DeclaredCode(digits, doc, "hs_code_header", None, doc.hs_code_header))
        if found:
            return list(found.values())
    return []


def _fmt_code(digits: str) -> str:
    return f"{digits[:4]}.{digits[4:6]}" + (f".{digits[6:8]}" if len(digits) >= 8 else "")


_CLASS_WORDS = {"non_alloy": "non-alloy", "alloy": "alloy", "stainless": "stainless", "indeterminate": "undetermined"}


def check_alloy_status(docs: list[ExtractedDocument], reference: Reference | None = None) -> CheckResult | None:
    reference = reference or get_reference()
    if not certificates(docs):
        return None
    codes = [c for c in declared_codes(docs) if reference.hs_rules.alloy_class_of(c.digits) is not None]
    if not codes:
        return None
    rules = reference.hs_rules
    assessment = assess_alloy_status(docs, reference)
    # the finding is about the certificate whose chemistry decides, not about the invoice that carries the HS code
    base: dict[str, Any] = {
        "rule_set": rules.rule_set, "regulation_ref": rules.regulation_ref, "focus_document": certificates(docs)[0].document_id,
    }

    code_evidence = [evidence_entry(c.doc.document_id, c.field_name, c.ref, line_item=c.line_item) for c in codes]
    if assessment is None:
        needed = [c for c in codes if rules.alloy_class_of(c.digits).alloy_class != "any"]  # type: ignore[union-attr]
        if not needed:
            return None
        return CheckResult(
            check_id="M-001", severity="WARN", evidence=code_evidence, **base,
            message=(f"The certificate states no chemistry, so the alloy status behind the declared HS code "
                     f"{_fmt_code(needed[0].digits)} cannot be checked (HS Note 1(f) is decided by the chemical composition)."),
        )

    material: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    evidence = list(code_evidence)
    assumptions: list[str] = []
    for code in codes:
        declared = rules.alloy_class_of(code.digits).alloy_class  # type: ignore[union-attr]
        chem = assessment.alloy_class
        label = _fmt_code(code.digits)
        if declared == "any":
            notes.append(f"{label} covers non-alloy and alloy steel alike, so the alloy status does not decide it")
            continue
        if chem == "indeterminate":
            first = next(u for h in assessment.heats for u in h.unclear)
            warnings.append(
                f"{label} is declared {_CLASS_WORDS[declared]}, but heat {first[1].ref.heat_number or 'n/a'} reports {first[0]} only as "
                f"'{first[1].printed()}', which does not rule out the {first[2]}% alloy threshold"
            )
            assumptions.append("an element reported only as an upper bound ('<x') was not taken to be below its alloy threshold")
            evidence.append(first[1].evidence(first[1].ref.heat_number or ""))
            continue
        if chem == declared:
            continue
        # the declaration and the chemistry disagree
        decider = assessment.deciding()
        prefix6 = code.digits[:6]
        twin = rules.alloy_twin_subheading.get(prefix6, {}).get(chem)
        twin_text = f"; the matching subheading would be {_fmt_code(twin)} (the 8-digit code is to be confirmed)" if twin else ""
        if chem in ("alloy", "stainless"):
            element, reading, threshold = decider.triggers[0]
            why = (f"heat {decider.heat.label or 'n/a'} reports {element} {reading.printed()}, at or above the {threshold:g} % "
                   f"{'stainless-steel' if chem == 'stainless' else 'alloy-steel'} threshold of HS Note {'1(e)' if chem == 'stainless' else '1(f)'}")
            evidence.append(reading.evidence(decider.heat.label))
        else:
            why = "no heat reports any element at or above a Note 1(f) alloy threshold, so the steel reads as non-alloy"
        material.append(f"HS {label} is declared {_CLASS_WORDS[declared]}, but {why}{twin_text}")

    if material:
        return CheckResult(check_id="M-001", severity="MATERIAL", evidence=evidence, **base,
                           message="Certificate chemistry contradicts the declared HS code: " + "; ".join(material) + ".")
    if warnings:
        return CheckResult(check_id="M-001", severity="WARN", evidence=evidence, assumptions=list(dict.fromkeys(assumptions)), **base,
                           message="Alloy status could not be confirmed: " + "; ".join(warnings) + ".")
    missing = assessment.not_reported
    summary = (f"Certified chemistry reads as {_CLASS_WORDS[assessment.alloy_class]} under HS Note 1(f) "
               f"({len(assessment.heats)} heat(s) checked)")
    tail = f" Elements the certificate does not report (taken as certified, not tested): {', '.join(missing)}." if missing else ""
    if notes:
        return CheckResult(check_id="M-001", severity="PASS", evidence=evidence, **base,
                           message=f"{summary}; {'; '.join(notes)}.{tail}")
    return CheckResult(check_id="M-001", severity="PASS", evidence=evidence, **base,
                       message=f"{summary}, consistent with the declared HS code(s) "
                               f"{', '.join(_fmt_code(c.digits) for c in codes)}.{tail}")


# ---------------------------------------------------------------------------
# specification limits
# ---------------------------------------------------------------------------


def _round2(value: float) -> float:
    return float(Decimal(str(round(value, 6))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def carbon_equivalent_iiw(v: dict[str, float]) -> float:
    return v["C"] + v["Mn"] / 6 + (v["Cr"] + v["Mo"] + v["V"]) / 5 + (v["Ni"] + v["Cu"]) / 15


def carbon_equivalent_pcm(v: dict[str, float]) -> float:
    return v["C"] + v["Si"] / 30 + (v["Mn"] + v["Cu"] + v["Cr"]) / 20 + v["Ni"] / 60 + v["Mo"] / 15 + v["V"] / 10 + 5 * v["B"]


def _spec_of(doc: ExtractedDocument, reference: Reference) -> tuple[SpecEntry | None, str]:
    printed = hs_text(doc.specification.value) if doc.specification else ""
    return reference.specs.match(printed), printed


def check_carbon_equivalent(docs: list[ExtractedDocument], reference: Reference | None = None) -> CheckResult | None:
    reference = reference or get_reference()
    specs = reference.specs
    lines: list[str] = []
    evidence: list[dict[str, Any]] = []
    assumptions: list[str] = []
    exceeded: list[str] = []
    spec_titles: set[str] = set()
    spec_assumes: set[str] = set()
    checked = 0
    for certificate in certificates(docs):
        spec, _printed = _spec_of(certificate, reference)
        if spec is None or (spec.ce_iiw_max is None and spec.pcm_max is None):
            continue
        for heat in collect_heats(certificate):
            carbon = heat.value("C")
            if carbon is None or heat.value("Mn") is None:
                continue
            use_pcm = spec.pcm_max is not None and spec.pcm_applies_when_c_at_most is not None and carbon <= spec.pcm_applies_when_c_at_most
            names = ["C", "Si", "Mn", "Cu", "Cr", "Ni", "Mo", "V", "B"] if use_pcm else ["C", "Mn", "Cr", "Mo", "V", "Ni", "Cu"]
            values: dict[str, float] = {}
            for name in names:
                found = heat.value(name)
                if found is None:
                    values[name] = 0.0
                    assumptions.append(f"{name} is not reported for heat {heat.label or 'n/a'}; taken as 0 in the carbon equivalent")
                else:
                    values[name] = found
                    evidence.append(heat.readings[name].evidence(heat.label))
            raw = carbon_equivalent_pcm(values) if use_pcm else carbon_equivalent_iiw(values)
            limit = spec.pcm_max if use_pcm else spec.ce_iiw_max
            assert limit is not None
            result = _round2(raw)
            kind = "Pcm" if use_pcm else "CE(IIW)"
            lines.append(f"heat {heat.label or 'n/a'} {kind} {result:.2f}")
            spec_titles.add(f"{spec.title} (limit {limit:.2f})")
            spec_assumes.update(spec.assumes)
            checked += 1
            if result > limit:
                exceeded.append(f"heat {heat.label or 'n/a'} {kind} {result:.2f} exceeds {limit:.2f}")
    if not checked:
        return None
    base: dict[str, Any] = {"rule_set": specs.rule_set, "regulation_ref": specs.regulation_ref}
    title = "; ".join(sorted(spec_titles))
    if exceeded:
        note = list(spec_assumes) or []
        return CheckResult(
            check_id="M-002", severity="WARN", evidence=evidence, assumptions=list(dict.fromkeys(assumptions + note)), **base,
            message=(f"Carbon equivalent above the limit of {title}: {'; '.join(exceeded)}. The limit depends on conditions the "
                     f"documents do not state ({'; '.join(note) or 'none'}), so this is a warning, not a contradiction."),
        )
    if assumptions:
        return CheckResult(check_id="M-002", severity="WARN", evidence=evidence, assumptions=list(dict.fromkeys(assumptions)), **base,
                           message=f"Carbon equivalent within the limit ({'; '.join(lines)}; {title}), but it rests on assumptions.")
    return CheckResult(check_id="M-002", severity="PASS", evidence=evidence, **base,
                       message=f"Carbon equivalent within the limit: {'; '.join(lines)} (limit of {title}).")


def check_specification_limits(docs: list[ExtractedDocument], reference: Reference | None = None) -> CheckResult | None:
    reference = reference or get_reference()
    base: dict[str, Any] = {"rule_set": reference.specs.rule_set, "regulation_ref": reference.specs.regulation_ref}
    violations: list[str] = []
    unverified: list[str] = []
    evidence: list[dict[str, Any]] = []
    assumptions: list[str] = []
    checked = 0
    titles: set[str] = set()

    for certificate in certificates(docs):
        heats = collect_heats(certificate)
        if not heats:
            unverified.append(f"{certificate.document_id} states no test results")
            continue
        spec, printed = _spec_of(certificate, reference)
        if spec is None:
            unverified.append(
                f"the specification '{printed}' is not in the rule set" if printed else f"{certificate.document_id} states no specification"
            )
            continue
        titles.add(spec.title)
        for heat in heats:
            who = heat.label or "n/a"
            for element in sorted(set(spec.element_max_pct) | set(spec.element_min_pct)):
                reading = heat.readings.get(element)
                if reading is None or reading.value is None:
                    unverified.append(f"heat {who}: {element} is not reported")
                    continue
                for note in reading.measure.assumptions:
                    assumptions.append(f"heat {who} {element}: {note}")
                checked += 1
                evidence.append(reading.evidence(heat.label))
                high, low = spec.element_max_pct.get(element), spec.element_min_pct.get(element)
                if high is not None and reading.measure.bound != "lower" and reading.value > high and reading.measure.bound == "exact":
                    violations.append(f"heat {who}: {element} {reading.printed()} exceeds the maximum {high:g} %")
                elif high is not None and reading.measure.bound == "upper" and reading.value > high:
                    unverified.append(f"heat {who}: {element} is reported as '{reading.printed()}', which does not show it is within {high:g} %")
                if low is not None and reading.exact and reading.value < low:
                    violations.append(f"heat {who}: {element} {reading.printed()} is below the minimum {low:g} %")
            for param, limit in spec.mechanical.items():
                reading = heat.readings.get(param)
                if reading is None or reading.value is None:
                    continue
                for note in reading.measure.assumptions:
                    assumptions.append(f"heat {who} {param}: {note}")
                checked += 1
                evidence.append(reading.evidence(heat.label))
                if limit.min is not None and reading.value < limit.min:
                    violations.append(f"heat {who}: {param} {reading.value:.1f} MPa is below the minimum {limit.min:g} MPa")
                if limit.max is not None and reading.value > limit.max:
                    violations.append(f"heat {who}: {param} {reading.value:.1f} MPa exceeds the maximum {limit.max:g} MPa")

    if not checked and not unverified:
        return None
    title = "; ".join(sorted(titles)) or "the certificate's specification"
    if violations:
        return CheckResult(check_id="M-003", severity="MATERIAL", evidence=evidence, **base,
                           message=f"The certificate does not meet its own specification ({title}): " + "; ".join(violations[:6])
                           + (f"; and {len(violations) - 6} more" if len(violations) > 6 else "") + ".")
    if unverified or assumptions:
        reasons = list(dict.fromkeys(unverified)) or list(dict.fromkeys(assumptions))
        return CheckResult(check_id="M-003", severity="WARN", evidence=evidence, assumptions=list(dict.fromkeys(assumptions)), **base,
                           message=f"Specification limits could not be fully verified ({title}): " + "; ".join(reasons[:6]) + ".")
    return CheckResult(check_id="M-003", severity="PASS", evidence=evidence, **base,
                       message=f"All {checked} reported chemistry and strength values are within the limits of {title}.")


# ---------------------------------------------------------------------------
# heat traceability
# ---------------------------------------------------------------------------


def check_heat_traceability(docs: list[ExtractedDocument], reference: Reference | None = None) -> CheckResult | None:  # noqa: ARG001 - same signature as the other checks
    certs = certificates(docs)
    if not certs:
        return None
    packing = next((d for d in docs if d.doc_type == "PACKING_LIST"), None)

    certified: dict[str, tuple[str, ExtractedDocument, int | None, Any]] = {}
    for certificate in certs:
        for key, (printed, index, ref) in heat_numbers_of(certificate).items():
            certified.setdefault(key, (printed, certificate, index, ref))
    shipped = heat_numbers_of(packing) if packing is not None else {}
    base: dict[str, Any] = {}  # no reference table is involved: nothing to cite

    if not certified:
        return CheckResult(check_id="M-004", severity="WARN", **base,
                           message="The certificate states no heat number, so the shipment cannot be traced to its test results.")
    if packing is None or not shipped:
        return CheckResult(
            check_id="M-004", severity="WARN", **base,
            message=("The packing list states no heat number, so the goods cannot be traced to the certificate "
                     f"(the certificate covers heat(s) {', '.join(v[0] for v in certified.values())})."),
        )
    uncovered = [printed for _key, (printed, _i, _r) in shipped.items() if not _covered(printed, certified)]
    evidence = [evidence_entry(packing.document_id, "heat_numbers", ref, row=i) for _k, (_p, i, ref) in shipped.items() if i is not None]
    evidence += [evidence_entry(doc.document_id, "heat_numbers", ref, row=i) for _k, (_p, doc, i, ref) in certified.items() if i is not None]
    if uncovered:
        return CheckResult(check_id="M-004", severity="MATERIAL", evidence=evidence, **base,
                           message=f"The packing list ships heat(s) {', '.join(uncovered)} that no certificate covers (certified: {', '.join(v[0] for v in certified.values())}).")
    shipped_keys = {normalize_heat(part) for printed, _i, _r in shipped.values() for part in [printed, *printed.split()]}
    extra = [printed for key, (printed, *_rest) in certified.items() if key not in shipped_keys]
    tail = f" The certificate also lists heat(s) {', '.join(extra)} that this packing list does not ship." if extra else ""
    return CheckResult(check_id="M-004", severity="PASS", evidence=evidence, **base,
                       message=f"Every heat on the packing list ({', '.join(v[0] for v in shipped.values())}) is covered by a certificate.{tail}")


def run(docs: list[ExtractedDocument], reference: Reference | None = None) -> list[CheckResult]:
    reference = reference or get_reference()
    checks = (check_alloy_status, check_carbon_equivalent, check_specification_limits, check_heat_traceability)
    return [result for check in checks if (result := check(docs, reference)) is not None]
