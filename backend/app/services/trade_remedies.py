"""Origin, anti-dumping and circumvention: the risks that sit between a document set and a duty.

Pure Python, no I/O, no LLM: deterministic rules over the curated tables in ``app/reference``, as the rest of the engine.

  E-origin  The country of origin stated on the documents agrees (MATERIAL when they disagree: origin laundering is a
            classic trade-fraud pattern; WARN when a stated name is not recognised).
  SEC-001   A heat sits within 20 % below an HS Note 1(f) alloy threshold while the goods are declared NON-alloy: a steel
            kept just under a threshold is a known way of staying in another code. A heuristic, so a WARN.
  SEC-002   An anti-dumping entry of the reference data matches destination + origin + HS code (the declared code, and the
            code the chemistry points to if it differs). ALWAYS a WARN: real duties are producer- and notification-specific,
            and the entries are unverified until a reviewer replaces them. The matching entry also feeds the duty estimate.

Detection is deterministic on purpose: the model reads documents; it never decides a classification or a duty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.countries import country_code
from app.domain.evidence import evidence_entry
from app.domain.hs import hs_text
from app.domain.schemas import CheckResult, ExtractedDocument
from app.reference.loader import AntiDumpingEntry, Reference, get_reference
from app.services import metallurgy

_DOC_LABELS = {
    "COMMERCIAL_INVOICE": "Commercial invoice", "PACKING_LIST": "Packing list", "BILL_OF_LADING": "Bill of lading",
    "CERTIFICATE_OF_ORIGIN": "Certificate of origin", "MILL_TEST_CERTIFICATE": "Mill test certificate",
}


@dataclass
class StatedOrigin:
    doc: ExtractedDocument
    printed: str
    code: str | None


def stated_origins(docs: list[ExtractedDocument]) -> list[StatedOrigin]:
    out: list[StatedOrigin] = []
    for doc in docs:
        ref = doc.country_of_origin
        if ref is not None and ref.value is not None and hs_text(ref.value):
            out.append(StatedOrigin(doc, hs_text(ref.value), country_code(ref.value)))
    return out


def _origin_evidence(origins: list[StatedOrigin]) -> list[dict[str, Any]]:
    return [evidence_entry(o.doc.document_id, "country_of_origin", o.doc.country_of_origin) for o in origins]


def check_origin_consistency(docs: list[ExtractedDocument], reference: Reference | None = None) -> CheckResult | None:  # noqa: ARG001
    origins = stated_origins(docs)
    if len(origins) < 2:
        return None  # one document states it: nothing to compare with
    evidence = _origin_evidence(origins)
    unknown = [o for o in origins if o.code is None]
    codes = sorted({o.code for o in origins if o.code})
    if len(codes) > 1:
        detail = "; ".join(f"{_DOC_LABELS.get(o.doc.doc_type, o.doc.doc_type)}: {o.printed}" for o in origins)
        return CheckResult(check_id="E-origin", severity="MATERIAL", evidence=evidence,
                           message=f"The country of origin differs between documents ({detail}).")
    if unknown:
        return CheckResult(check_id="E-origin", severity="WARN", evidence=evidence,
                           message=f"The country of origin '{unknown[0].printed}' is not a name the rule set recognises, so it could not be compared.")
    return CheckResult(check_id="E-origin", severity="PASS", evidence=evidence,
                       message=f"The country of origin is {codes[0]} on all {len(origins)} documents that state it.")


# ---------------------------------------------------------------------------
# SEC-001
# ---------------------------------------------------------------------------


def check_near_threshold(docs: list[ExtractedDocument], reference: Reference | None = None) -> CheckResult | None:
    reference = reference or get_reference()
    rules = reference.hs_rules
    declared = [c for c in metallurgy.declared_codes(docs) if (r := rules.alloy_class_of(c.digits)) is not None and r.alloy_class == "non_alloy"]
    assessment = metallurgy.assess_alloy_status(docs, reference)
    if not declared or assessment is None or assessment.alloy_class != "non_alloy":
        return None
    near = [(h, n) for h in assessment.heats for n in h.near]
    if not near:
        return None
    heat, (element, reading, threshold) = near[0]
    more = f" ({len(near) - 1} more value(s) are also close)" if len(near) > 1 else ""
    return CheckResult(
        check_id="SEC-001", severity="WARN", rule_set=rules.rule_set, regulation_ref=rules.regulation_ref,
        evidence=[reading.evidence(heat.heat.label)],
        message=(f"Heat {heat.heat.label or 'n/a'} reports {element} {reading.printed()}, within 20 % below the {threshold:g} % at which HS Note 1(f) "
                 f"makes steel alloy, while the goods are declared non-alloy{more}. A steel kept just under a threshold is a known way "
                 "of staying in another tariff code: have the certificate verified."),
        assumptions=["the 20 % proximity band is a heuristic, not a legal test"],
    )


# ---------------------------------------------------------------------------
# SEC-002
# ---------------------------------------------------------------------------


@dataclass
class AntiDumpingMatch:
    entry: AntiDumpingEntry
    hs_digits: str          # the code that matched (declared, or implied by the chemistry)
    implied: bool           # True when the code is the one the chemistry points to, not the declared one
    origin: StatedOrigin


def _codes_to_screen(docs: list[ExtractedDocument], reference: Reference) -> list[tuple[str, bool]]:
    """(digits, implied) for every declared code, plus the twin subheading the chemistry points to when it disagrees."""
    rules = reference.hs_rules
    codes = [(c.digits, False) for c in metallurgy.declared_codes(docs)]
    assessment = metallurgy.assess_alloy_status(docs, reference)
    if assessment is not None and assessment.alloy_class in ("alloy", "stainless"):
        for digits, _ in list(codes):
            rule = rules.alloy_class_of(digits)
            twin = rules.alloy_twin_subheading.get(digits[:6], {}).get(assessment.alloy_class)
            if rule is not None and rule.alloy_class not in (assessment.alloy_class, "any") and twin:
                codes.append((twin, True))
    return codes


def anti_dumping_matches(docs: list[ExtractedDocument], destination: str, reference: Reference | None = None) -> list[AntiDumpingMatch]:
    reference = reference or get_reference()
    found: list[AntiDumpingMatch] = []
    seen: set[tuple[str, str]] = set()
    for digits, implied in _codes_to_screen(docs, reference):
        for origin in stated_origins(docs):
            if origin.code is None:
                continue
            for entry in reference.anti_dumping.matches(destination, origin.code, digits):
                if (entry.id, digits) not in seen:
                    seen.add((entry.id, digits))
                    found.append(AntiDumpingMatch(entry, digits, implied, origin))
    return found


def check_anti_dumping(docs: list[ExtractedDocument], destination: str, reference: Reference | None = None) -> CheckResult | None:
    reference = reference or get_reference()
    table = reference.anti_dumping
    base: dict[str, Any] = {"rule_set": table.rule_set, "regulation_ref": table.regulation_ref}
    destination = (destination or "").upper()
    screened = _codes_to_screen(docs, reference)
    relevant = [e for e in table.entries if e.destination == destination
                and any(d.startswith(p) for d, _ in screened for p in e.hs_prefixes)]
    if not relevant:
        return None

    code_evidence = [evidence_entry(c.doc.document_id, c.field_name, c.ref, line_item=c.line_item) for c in metallurgy.declared_codes(docs)]
    matches = anti_dumping_matches(docs, destination, reference)
    origins = stated_origins(docs)
    if matches:
        grouped: dict[str, list[AntiDumpingMatch]] = {}
        for match in matches:
            grouped.setdefault(match.entry.id, []).append(match)
        parts = []
        for group in grouped.values():
            entry, origin = group[0].entry, group[0].origin
            codes = " and ".join(
                f"{metallurgy._fmt_code(m.hs_digits)}" + (" (the code the certificate's chemistry points to)" if m.implied else " (declared)")
                for m in group
            )
            parts.append(f"HS {codes} from {origin.printed}: {entry.scope}, {entry.rate_pct_of_assessable_value:g} % of the assessable value "
                         f"(entry {entry.id}; notification {entry.notification_ref or 'not supplied'})")
        producer = " The rate is producer-specific: a specialist must confirm the producer and the notification." if any(m.entry.producer_specific for m in matches) else ""
        return CheckResult(
            check_id="SEC-002", severity="WARN", evidence=_origin_evidence(origins) + code_evidence, **base,
            message="Anti-dumping duty may apply: " + "; ".join(parts) + "." + producer + " It is included in the indicative duty estimate.",
            assumptions=["anti-dumping applicability and rate are taken from reference entries that have not been verified against a notification"],
        )
    if not origins:
        return CheckResult(check_id="SEC-002", severity="WARN", evidence=code_evidence, **base,
                           message=(f"No country of origin is stated, so anti-dumping duty into {destination} cannot be ruled out "
                                    f"(the rule set has an entry for origin(s) {', '.join(sorted({o for e in relevant for o in e.origins}))}) for this HS code."))
    if any(o.code is None for o in origins):
        unknown = next(o for o in origins if o.code is None)
        return CheckResult(check_id="SEC-002", severity="WARN", evidence=_origin_evidence(origins) + code_evidence, **base,
                           message=f"The country of origin '{unknown.printed}' is not recognised, so anti-dumping duty cannot be ruled out for this HS code.")
    return None  # origins are known and none is covered: nothing to report


def run(docs: list[ExtractedDocument], destination: str, reference: Reference | None = None) -> list[CheckResult]:
    reference = reference or get_reference()
    results = [
        check_origin_consistency(docs, reference),
        check_near_threshold(docs, reference),
        check_anti_dumping(docs, destination, reference),
    ]
    return [r for r in results if r is not None]
