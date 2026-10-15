"""Deterministic math engine — weight parity + entity alignment + HS consistency.

This service is PURE Python with NO I/O and NO LLM calls.
It receives the structured extraction output and applies deterministic rules.

Rule of the engine: a check whose result depends on an ASSUMPTION never returns PASS or MATERIAL. It returns
WARN, lists every assumption in ``CheckResult.assumptions`` and states the computed delta in the message.
PASS / MATERIAL are reserved for results computed purely from values and units the documents actually state.

Weight rules (v4.0 §3.1, corrected):
  W-001  packing list vs Bill of Lading gross, tolerance abs(delta) <= max(0.5% x gross, 5 kg). The packing-list
         side is, in priority order: (1) net + DECLARED tare, (2) the packing list's DECLARED total gross (tare not
         declared), (3) last resort net + 2% default tare, which is an assumption and therefore always a WARN.
  W-002  packing list internal consistency: net + tare vs its own declared gross (only when all three are declared).
  Every weight is converted to kg with app.domain.units; a missing unit ("assumed kg") is an assumption, an
  unrecognised unit makes the check not evaluable.

HS rules (H-002, H-003): declared codes (line items and header) are compared as digits only, at 8 digits when
  every code states 8 (longer national codes are truncated to 8), otherwise at 6 digits with a WARN. Malformed
  codes are never compared. One helper (_compare_hs_codes) serves both:
  H-002          commercial invoice vs packing list.
  H-003-<TYPE>   each certificate type (mill test certificate, certificate of origin, phytosanitary) that states an
                 HS code vs the invoice's codes (the packing list's if the invoice states none; no check if neither
                 does). A certificate may state a proper SUBSET of those codes (it covers some lines): that agrees;
                 a code the reference lacks is MATERIAL. A certificate that states no HS code is not checked.

Invoice arithmetic (services/invoice_checks.py), the certificate's chemistry against the declaration
(services/metallurgy.py) and origin / anti-dumping / circumvention (services/trade_remedies.py) are separate modules
called from ``run``; the indicative duty estimate (services/valuation.py) is computed there too and does not affect status.

Entity rules (v4.0 §3.2 & hardening update):
  consignee, consignor, vessel_or_flight must be consistent across documents (E-consignee / E-consignor /
  E-vessel: MATERIAL on disagreement, PASS with evidence when two or more documents agree).
  Name normalization (casefold, strip punctuation, collapse whitespace) applies.
  Note: document_number is explicitly excluded because invoices, packing lists, and BoLs
  have unique document identifiers.

This module has a ≥95% unit test coverage requirement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from app.domain.hs import (
    CERTIFICATE_DOC_TYPES,
    HS_FULL_DIGITS,
    HS_MIN_DIGITS,
    hs_digits,
    hs_evidence_entry,
    hs_text,
)
from app.domain.schemas import CheckResult, ExtractedDocument, FieldRef
from app.domain.units import parse_number, to_kg, trailing_unit
from app.reference.loader import fingerprint
from app.services import invoice_checks, metallurgy, trade_remedies, valuation

# ---------------------------------------------------------------------------
# Constants (from v4.0 §3.1)
# ---------------------------------------------------------------------------

REL_TOL: float = 0.005      # 0.5% of gross weight
ABS_TOL: float = 5.0        # 5 kg minimum tolerance
DEFAULT_TARE_RATIO: float = 0.02   # 2% of net: ONLY the last-resort W-001 branch, and then always a WARN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tolerance(gross_kg: float) -> float:
    """Return the allowed weight delta for a given gross weight."""
    return max(REL_TOL * gross_kg, ABS_TOL)


def normalize_entity_name(name: str) -> str:
    """Normalize entity names for comparison.

    Converts to uppercase, strips punctuation, and collapses whitespace.
    e.g., "SINGAPORE TRADING PTE. LTD." -> "SINGAPORE TRADING PTE LTD"
    """
    cleaned = re.sub(r"[^\w\s]", "", name.upper())
    return " ".join(cleaned.split())


def _build_field_evidence(doc: ExtractedDocument, field_name: str) -> dict[str, Any]:
    """Extract field evidence with page and bbox provenance."""
    field_ref: FieldRef | None = getattr(doc, field_name, None)
    entry: dict[str, Any] = {"doc": doc.document_id, "field": field_name}
    if field_ref and field_ref.bbox:
        entry["page"] = field_ref.bbox.page
        entry["bbox"] = field_ref.bbox.model_dump()
    else:
        entry["page"] = 1
        entry["bbox"] = None
    printed = getattr(field_ref, "value", None)
    if printed is not None and str(printed).strip() != "":
        entry["raw_value"] = printed if not isinstance(printed, float) else (int(printed) if printed.is_integer() else printed)
    unit = getattr(field_ref, "unit", None)
    if unit is not None and str(unit).strip() != "":
        entry["unit"] = str(unit).strip()
    return entry


# ---------------------------------------------------------------------------
# Weight reading (units + assumptions)
# ---------------------------------------------------------------------------


@dataclass
class _Weight:
    """One stated weight, converted to kg, with whatever was assumed to read it."""

    doc: ExtractedDocument
    field_name: str
    kg: float | None = None
    assumptions: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def label(self) -> str:
        return f"{self.doc.document_id}.{self.field_name}"


def _read_weight(doc: ExtractedDocument, field_name: str) -> _Weight | None:
    """The weight a document states in ``field_name`` in kg; None when the document does not state it."""
    ref = getattr(doc, field_name, None)
    if ref is None or ref.value is None or (isinstance(ref.value, str) and not ref.value.strip()):
        return None

    weight = _Weight(doc=doc, field_name=field_name)
    parsed = parse_number(ref.value)
    if parsed is None:
        weight.error = f"unreadable value '{ref.value}' in {weight.label}"
        return weight

    unit = getattr(ref, "unit", None)
    if unit is None or not str(unit).strip():
        unit = trailing_unit(ref.value)  # "14,280 KGS" printed inside the value counts as a stated unit
    quantity = to_kg(parsed.value, unit)
    if quantity.error:
        weight.error = f"{quantity.error} in {weight.label}"
        return weight

    weight.kg = quantity.kg
    weight.assumptions = [*parsed.assumptions, *quantity.assumptions]
    return weight


def _evidence(weights: list[_Weight]) -> list[dict[str, Any]]:
    return [_build_field_evidence(w.doc, w.field_name) for w in weights]


def _dedupe(assumptions: list[str]) -> list[str]:
    return list(dict.fromkeys(assumptions))


def _first_error(weights: list[_Weight]) -> str | None:
    return next((w.error for w in weights if w.error), None)


def _within(delta: float, tol: float) -> str:
    return "within" if delta <= tol else "exceeds"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_weight_parity(
    packing: ExtractedDocument,
    bol: ExtractedDocument,
) -> CheckResult:
    """W-001: the packing list's weight vs the Bill of Lading gross.

    Packing-list side, in priority order: (1) net + DECLARED tare; (2) the packing list's DECLARED total gross
    when tare is not declared; (3) net + DEFAULT_TARE_RATIO x net as a last resort, which rests on an
    assumption and so is always a WARN. Returns PASS / MATERIAL only for results computed from stated values
    and units; anything assumed or unreadable is a WARN.
    """
    net = _read_weight(packing, "total_net_weight_kg")
    tare = _read_weight(packing, "tare_weight_kg")
    pl_gross = _read_weight(packing, "total_gross_weight_kg")
    bol_gross = _read_weight(bol, "total_gross_weight_kg")

    declared = [w for w in (net, tare, pl_gross, bol_gross) if w is not None]

    def not_evaluable(reason: str) -> CheckResult:
        return CheckResult(
            check_id="W-001",
            severity="WARN",
            message=f"Weight parity not evaluable: {reason}",
            evidence=_evidence(declared),
        )

    if bol_gross is None:
        return not_evaluable("the Bill of Lading states no gross weight.")

    if net is not None and tare is not None:
        branch, used = 1, [net, tare, bol_gross]
    elif pl_gross is not None:
        branch, used = 2, [pl_gross, bol_gross]
    elif net is not None:
        branch, used = 3, [net, bol_gross]
    else:
        return not_evaluable("the packing list states no usable net weight or gross weight.")

    error = _first_error(used)
    if error:
        return not_evaluable(f"{error}.")

    if any(w.kg is None for w in used):  # unreachable once errors are handled; keeps the types honest
        return not_evaluable("a weight could not be converted to kilograms.")
    kgs = [cast(float, w.kg) for w in used]
    gross = kgs[-1]  # the Bill of Lading gross is always the last element of `used`
    tol = _tolerance(gross)
    assumptions = [a for w in used for a in w.assumptions]

    if branch == 1:
        expected = kgs[0] + kgs[1]  # net + declared tare
        what = "Net+tare"
    elif branch == 2:
        expected = kgs[0]  # the packing list's declared gross
        what = "Packing list gross"
    else:
        expected = kgs[0] + DEFAULT_TARE_RATIO * kgs[0]  # net + assumed tare
        what = f"Net + {DEFAULT_TARE_RATIO:.0%} default tare"
        assumptions.append(f"tare not declared; assumed {DEFAULT_TARE_RATIO:.0%} of net (spec default)")

    delta = abs(expected - gross)
    assumptions = _dedupe(assumptions)
    evidence = _evidence(used)

    if assumptions:
        return CheckResult(
            check_id="W-001",
            severity="WARN",
            message=(
                f"Weight parity depends on assumptions ({'; '.join(assumptions)}): {what} is {expected:.1f} kg "
                f"vs BoL gross {gross:.1f} kg, delta {delta:.1f} kg ({_within(delta, tol)} ±{tol:.1f} kg tolerance)."
            ),
            delta=delta,
            tolerance=tol,
            evidence=evidence,
            assumptions=assumptions,
        )

    if delta <= tol:
        if branch == 1:
            message = (
                f"Net+tare ({expected:.1f} kg) matches BoL gross ({gross:.1f} kg) "
                f"within tolerance (±{tol:.1f} kg)."
            )
        else:
            message = (
                f"Packing list gross ({expected:.1f} kg) matches BoL gross ({gross:.1f} kg), delta {delta:.1f} kg, "
                f"within tolerance (±{tol:.1f} kg); tare is not declared."
            )
        severity = "PASS"
    else:
        if branch == 1:
            message = (
                f"Weight mismatch of {delta:.1f} kg exceeds ±{tol:.1f} kg tolerance. "
                f"Expected ≈{expected:.1f} kg, BoL declares {gross:.1f} kg."
            )
        else:
            message = (
                f"Weight mismatch of {delta:.1f} kg exceeds ±{tol:.1f} kg tolerance. "
                f"Packing list declares gross {expected:.1f} kg, BoL declares {gross:.1f} kg."
            )
        severity = "MATERIAL"

    return CheckResult(
        check_id="W-001",
        severity=severity,
        message=message,
        delta=delta,
        tolerance=tol,
        evidence=evidence,
    )


def check_packing_consistency(packing: ExtractedDocument) -> CheckResult | None:
    """W-002: the packing list must add up: net + tare vs its own declared total gross.

    Evaluated only when the packing list declares net, tare AND total gross; otherwise skipped (None).
    """
    net = _read_weight(packing, "total_net_weight_kg")
    tare = _read_weight(packing, "tare_weight_kg")
    gross = _read_weight(packing, "total_gross_weight_kg")
    if net is None or tare is None or gross is None:
        return None

    used = [net, tare, gross]
    error = _first_error(used)
    if error:
        return CheckResult(
            check_id="W-002",
            severity="WARN",
            message=f"Packing list consistency not evaluable: {error}.",
            evidence=_evidence(used),
        )

    if net.kg is None or tare.kg is None or gross.kg is None:  # unreachable once errors are handled
        return CheckResult(
            check_id="W-002",
            severity="WARN",
            message="Packing list consistency not evaluable: a weight could not be converted to kilograms.",
            evidence=_evidence(used),
        )
    expected = net.kg + tare.kg
    tol = _tolerance(gross.kg)
    delta = abs(expected - gross.kg)
    assumptions = _dedupe([a for w in used for a in w.assumptions])

    if assumptions:
        return CheckResult(
            check_id="W-002",
            severity="WARN",
            message=(
                f"Packing list consistency depends on assumptions ({'; '.join(assumptions)}): net+tare is "
                f"{expected:.1f} kg vs declared gross {gross.kg:.1f} kg, delta {delta:.1f} kg "
                f"({_within(delta, tol)} ±{tol:.1f} kg tolerance)."
            ),
            delta=delta,
            tolerance=tol,
            evidence=_evidence(used),
            assumptions=assumptions,
        )

    if delta <= tol:
        severity = "PASS"
        message = (
            f"Packing list net+tare ({expected:.1f} kg) matches its declared gross ({gross.kg:.1f} kg) "
            f"within tolerance (±{tol:.1f} kg)."
        )
    else:
        severity = "MATERIAL"
        message = (
            f"Packing list does not add up: net+tare is {expected:.1f} kg but gross is declared as "
            f"{gross.kg:.1f} kg (delta {delta:.1f} kg exceeds ±{tol:.1f} kg tolerance)."
        )
    return CheckResult(
        check_id="W-002",
        severity=severity,
        message=message,
        delta=delta,
        tolerance=tol,
        evidence=_evidence(used),
    )


# ---------------------------------------------------------------------------
# HS codes
# ---------------------------------------------------------------------------


@dataclass
class _HsCode:
    raw: str
    digits: str
    doc_id: str
    field_name: str
    line_item: int | None
    ref: FieldRef

    @property
    def well_formed(self) -> bool:
        return len(self.digits) >= HS_MIN_DIGITS

    @property
    def evidence(self) -> dict[str, Any]:
        return hs_evidence_entry(self.doc_id, self.field_name, self.ref, line_item=self.line_item)


def _collect_hs_codes(doc: ExtractedDocument) -> list[_HsCode]:
    """Every declared code on a document: its line items and its header code."""
    refs: list[tuple[str, int | None, FieldRef]] = [
        ("hs_code_declared", index, item.hs_code_declared)
        for index, item in enumerate(doc.line_items)
        if item.hs_code_declared
    ]
    if doc.hs_code_header is not None:
        refs.append(("hs_code_header", None, doc.hs_code_header))

    codes: list[_HsCode] = []
    for field_name, line_item, ref in refs:
        if ref.value is None:
            continue
        raw = hs_text(ref.value)
        if not raw:
            continue
        codes.append(
            _HsCode(
                raw=raw, digits=hs_digits(raw), doc_id=doc.document_id,
                field_name=field_name, line_item=line_item, ref=ref,
            )
        )
    return codes


def _hs_evidence(doc: ExtractedDocument, codes: list[_HsCode]) -> list[dict[str, Any]]:
    """One entry per declared code (page/bbox/line item when known); a placeholder if the document has none."""
    if not codes:
        return [hs_evidence_entry(doc.document_id, "hs_code_declared")]
    return [code.evidence for code in codes]


@dataclass
class _HsComparison:
    """The outcome of comparing two sets of declared HS codes; shared by H-002 and H-003."""

    severity: Literal["PASS", "WARN", "MATERIAL"]
    message: str
    assumptions: list[str] = field(default_factory=list)
    level: int | None = None  # digits the codes were compared at; None when no comparison was possible


def _compare_hs_codes(
    reference_codes: list[_HsCode],
    other_codes: list[_HsCode],
    *,
    reference_label: str = "Invoice",
    other_label: str = "Packing List",
    other_may_be_subset: bool = False,
) -> _HsComparison:
    """Compare the codes of a reference document with those of another document.

    Codes are reduced to digits ("7304.19.00" == "73041900") and compared at 8 digits when every well-formed code
    states 8 (longer national codes are truncated to 8, which is stated in the message); if any code has only 6-7
    digits ALL codes are compared at 6 digits and an agreement is only a WARN (the 8-digit AHTN code is then an
    assumption). Codes with fewer than 6 digits are malformed: they are named and never compared. Differing code
    sets are MATERIAL. The labels only name the two sides in the messages.

    With ``other_may_be_subset`` (a certificate covers one product, not the whole invoice) the other side may state
    a PROPER SUBSET of the reference codes: that agrees (PASS at 8 digits, WARN + assumption at 6 digits). Any
    code the reference does not have is still MATERIAL and is named. H-002 compares two full documents, so it
    keeps the default (equal sets only).
    """
    if not reference_codes or not other_codes:
        return _HsComparison("WARN", "HS code absent on one or more documents — cannot verify consistency.")

    malformed = [c for c in (*reference_codes, *other_codes) if not c.well_formed]
    malformed_note = "; ".join(f"malformed HS code '{c.raw}' ({c.doc_id}) was not compared" for c in malformed)
    reference_valid = [c for c in reference_codes if c.well_formed]
    other_valid = [c for c in other_codes if c.well_formed]

    if not reference_valid or not other_valid:
        return _HsComparison("WARN", f"HS codes cannot be verified: {malformed_note}.")

    level = (
        HS_FULL_DIGITS
        if all(len(c.digits) >= HS_FULL_DIGITS for c in (*reference_valid, *other_valid))
        else HS_MIN_DIGITS
    )
    reference_set = sorted({c.digits[:level] for c in reference_valid})
    other_set = sorted({c.digits[:level] for c in other_valid})

    notes = []
    if level == HS_FULL_DIGITS:
        truncated = [c for c in (*reference_valid, *other_valid) if len(c.digits) > HS_FULL_DIGITS]
        if truncated:
            listed = ", ".join(f"'{c.raw}'" for c in truncated)
            notes.append(f"{listed} truncated to {HS_FULL_DIGITS} digits for comparison")
    for code in (*reference_valid, *other_valid):
        if len(code.digits) == HS_FULL_DIGITS - 1:
            notes.append(f"'{code.raw}' has 7 digits; a leading zero may have been dropped")
    if malformed_note:
        notes.append(malformed_note)
    suffix = f" ({'; '.join(notes)})" if notes else ""

    unmatched = sorted(set(other_set) - set(reference_set))
    is_subset = other_may_be_subset and not unmatched and other_set != reference_set
    if other_set != reference_set and not is_subset:
        named = (
            f" Not declared on the {reference_label}: {unmatched}."
            if other_may_be_subset
            else ""
        )
        return _HsComparison(
            "MATERIAL",
            f"HS code divergence detected at {level} digits. "
            f"{reference_label}: {reference_set}, {other_label}: {other_set}.{named}{suffix}",
            level=level,
        )

    # The codes agree: either they are equal, or the other side states some of the reference's codes.
    states = (
        f"{other_label} states {len(other_set)} of the {len(reference_set)} codes declared on the "
        f"{reference_label}: {other_set}."
        if is_subset
        else None
    )

    if level == HS_MIN_DIGITS:
        unverified = (
            f"The {HS_FULL_DIGITS}-digit AHTN code is not stated on every document, so the codes were compared "
            f"at {HS_MIN_DIGITS} digits and the full code is unverified.{suffix}"
        )
        return _HsComparison(
            "WARN",
            f"{states} {unverified}"
            if states
            else f"Declared HS codes agree at {HS_MIN_DIGITS} digits only: {reference_set}. {unverified}",
            assumptions=[f"compared at {HS_MIN_DIGITS} digits; {HS_FULL_DIGITS}-digit AHTN code not stated"],
            level=level,
        )

    if malformed:
        return _HsComparison(
            "WARN",
            f"{states} However, {malformed_note}."
            if states
            else f"Declared HS codes that could be read are consistent: {reference_set}, but {malformed_note}.",
            level=level,
        )

    return _HsComparison(
        "PASS",
        f"{states}{suffix}" if states else f"Declared HS codes are consistent: {reference_set}.{suffix}",
        level=level,
    )


def check_hs_consistency(
    invoice: ExtractedDocument,
    packing: ExtractedDocument,
) -> CheckResult:
    """H-002: declared HS codes must agree between the invoice and the packing list.

    Codes come from line items and the header; the comparison rules are those of :func:`_compare_hs_codes`.
    """
    inv_codes = _collect_hs_codes(invoice)
    pl_codes = _collect_hs_codes(packing)
    result = _compare_hs_codes(inv_codes, pl_codes)
    return CheckResult(
        check_id="H-002",
        severity=result.severity,
        message=result.message,
        evidence=_hs_evidence(invoice, inv_codes) + _hs_evidence(packing, pl_codes),
        assumptions=result.assumptions,
    )


def _hs_reference(
    invoice: ExtractedDocument | None,
    packing: ExtractedDocument | None,
) -> tuple[ExtractedDocument, list[_HsCode], str] | None:
    """The document certificates are compared with: the invoice if it states a code, else the packing list."""
    for candidate, label in ((invoice, "Invoice"), (packing, "Packing List")):
        if candidate is None:
            continue
        codes = _collect_hs_codes(candidate)
        if codes:
            return candidate, codes, label
    return None


def check_certificate_hs_consistency(
    certificate: ExtractedDocument,
    invoice: ExtractedDocument | None,
    packing: ExtractedDocument | None,
) -> CheckResult | None:
    """H-003-<DOC_TYPE>: the HS code a certificate states must agree with the invoice (else the packing list).

    Same comparison rules as H-002, except that the certificate may state a proper SUBSET of the reference's codes
    (it covers some of the lines, not necessarily all): that agrees. A code the reference does not have is
    MATERIAL. Returns None, so the check is skipped, when the certificate states no HS code or when neither the
    invoice nor the packing list states one.
    """
    certificate_codes = _collect_hs_codes(certificate)
    reference = _hs_reference(invoice, packing)
    if not certificate_codes or reference is None:
        return None

    reference_doc, reference_codes, reference_label = reference
    certificate_label = certificate.doc_type.replace("_", " ").title()
    result = _compare_hs_codes(
        reference_codes,
        certificate_codes,
        reference_label=reference_label,
        other_label=certificate_label,
        other_may_be_subset=True,  # a certificate covers a product / heat, not necessarily every invoice line
    )
    return CheckResult(
        check_id=f"H-003-{certificate.doc_type}",  # one per certificate type, so ids stay unique
        severity=result.severity,
        message=f"{certificate_label} vs {reference_label}: {result.message}",
        evidence=_hs_evidence(certificate, certificate_codes) + _hs_evidence(reference_doc, reference_codes),
        assumptions=result.assumptions,
    )


def check_entity_alignment(docs: list[ExtractedDocument]) -> list[CheckResult]:
    """Consignee, consignor, and vessel must be consistent across all docs.

    Note: document_number is explicitly excluded per T2.2 (invoice, PL, BoL numbers differ).
    Entity names are normalized (punctuation, case, whitespace) before comparison. One check per attribute:
    MATERIAL when the documents disagree, PASS (with evidence for every stating document) when at least two
    documents state it and all agree, nothing when fewer than two documents state it.
    """
    results: list[CheckResult] = []

    for attr, check_id in (
        ("consignee", "E-consignee"),
        ("consignor", "E-consignor"),
        ("vessel_or_flight", "E-vessel"),
    ):
        raw_vals: dict[str, list[dict[str, Any]]] = {}
        for doc in docs:
            field_ref: FieldRef | None = getattr(doc, attr, None)
            if field_ref and field_ref.value is not None:
                orig_val = str(field_ref.value).strip()
                norm_val = normalize_entity_name(orig_val)
                if norm_val:
                    ev = _build_field_evidence(doc, attr)
                    ev["raw_value"] = orig_val
                    raw_vals.setdefault(norm_val, []).append(ev)

        all_evidence = [ev for group in raw_vals.values() for ev in group]
        unique_raws = sorted({ev["raw_value"] for ev in all_evidence})
        stating_docs = {ev["doc"] for ev in all_evidence}

        if len(raw_vals) > 1:
            results.append(
                CheckResult(
                    check_id=check_id,
                    severity="MATERIAL",
                    message=f"Inconsistent {attr} across documents: {unique_raws}.",
                    evidence=all_evidence,
                )
            )
        elif len(stating_docs) >= 2:
            # Agreement is reported too: it puts the fields on record as used by a check (confidence routing
            # reads check evidence). A field stated by a single document has nothing to be compared with.
            results.append(
                CheckResult(
                    check_id=check_id,
                    severity="PASS",
                    message=f"{attr} is consistent across {len(stating_docs)} documents: {unique_raws}",
                    evidence=all_evidence,
                )
            )

    return results


# ---------------------------------------------------------------------------
# Roll-up to status
# ---------------------------------------------------------------------------


def _roll_up(results: list[CheckResult]) -> str:
    """Convert a list of check results to a single status string."""
    if any(r.severity == "MATERIAL" for r in results):
        return "MATERIAL_CONTRADICTION"
    if any(r.severity == "WARN" for r in results):
        return "SPECIALIST_REVIEW_REQUIRED"
    return "COMPLIANT_FOR_SUBMISSION"


# ---------------------------------------------------------------------------
# Pipeline stage entry point
# ---------------------------------------------------------------------------


async def run(ctx: dict) -> dict:
    """Deterministic check engine — pipeline stage entry point.

    Reads:  ctx["extracted"]  (list[ExtractedDocument])
    Writes: ctx["checks"]     (list[dict] — serialised CheckResults)
            ctx["math_status"] (str — one of the 4 status strings)
            ctx["valuation"]  (dict — ValuationEstimate; informational)
            ctx["reference_data"] (dict — fingerprint of the curated tables used)
    """
    docs: list[ExtractedDocument] = ctx.get("extracted", [])
    results: list[CheckResult] = []

    by_type: dict[str, list[ExtractedDocument]] = {}
    for d in docs:
        by_type.setdefault(d.doc_type, []).append(d)

    # Check for duplicate document types
    for doc_type, doc_list in by_type.items():
        if len(doc_list) > 1 and doc_type != "UNKNOWN":
            results.append(
                CheckResult(
                    check_id=f"D-DUP-{doc_type}",  # one per duplicated type, so ids stay unique
                    severity="WARN",
                    message=f"Multiple documents found for type '{doc_type}' ({len(doc_list)} docs). Using first document for pair checks.",
                )
            )

    # Helper to get first doc of a type
    def get_first(doc_type: str) -> ExtractedDocument | None:
        lst = by_type.get(doc_type, [])
        return lst[0] if lst else None

    packing = get_first("PACKING_LIST")
    bol = get_first("BILL_OF_LADING")
    invoice = get_first("COMMERCIAL_INVOICE")

    # Weight parity: Packing List vs Bill of Lading
    if packing and bol:
        results.append(check_weight_parity(packing, bol))

    # Packing list internal consistency (only when net, tare and gross are all declared)
    if packing:
        consistency = check_packing_consistency(packing)
        if consistency is not None:
            results.append(consistency)

    # HS code consistency: Commercial Invoice vs Packing List
    if invoice and packing:
        results.append(check_hs_consistency(invoice, packing))

    # HS code consistency: each certificate type vs the invoice (else the packing list)
    for certificate_type in CERTIFICATE_DOC_TYPES:
        certificate = get_first(certificate_type)
        if certificate is None:
            continue
        certificate_check = check_certificate_hs_consistency(certificate, invoice, packing)
        if certificate_check is not None:
            results.append(certificate_check)

    # Entity alignment across all documents
    results.extend(check_entity_alignment(docs))

    # Invoice arithmetic (I-001..I-003), the certificate against the declaration (M-001..M-005), origin and trade
    # remedies (E-origin, SEC-001, SEC-002). Each rests on its own module; the curated tables they use are named on
    # the checks (rule_set / regulation_ref) and fingerprinted below.
    destination = str(ctx.get("destination_country", "SG"))
    results.extend(invoice_checks.run(docs))
    results.extend(metallurgy.run(docs))
    results.extend(trade_remedies.run(docs, destination))

    ctx["checks"] = [r.model_dump() for r in results]
    ctx["math_status"] = _roll_up(results)
    # The indicative duty estimate is NOT a check: it never changes the status (see services/valuation.py).
    ctx["valuation"] = valuation.estimate(docs, destination).model_dump(mode="json")
    ctx["reference_data"] = fingerprint()
    return ctx
