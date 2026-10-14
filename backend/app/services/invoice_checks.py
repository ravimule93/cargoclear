"""Commercial invoice arithmetic: do the invoice's own numbers add up? (spec US 3.2: "invoice totals")

Pure Python, no I/O, no LLM. Like the rest of the deterministic engine: a result that rests on an assumption is a WARN;
PASS / MATERIAL are reserved for results computed from values the document states.

  I-001  line arithmetic: quantity x unit price = line total, for every line that states all three. The unit price is read
         as "per unit of the quantity" (the convention of a Quantity / Unit Price column pair) unless the line prints what
         it is per (``unit_price_basis``). A line that only reconciles under ANOTHER basis (per MT while the quantity is in
         pieces) is a WARN that names it; one that reconciles under none is MATERIAL.
  I-002  invoice total: the stated invoice value against the sum of the line totals. Charges or discounts that are not
         extracted as lines would explain a difference, which is an assumption: a difference is a WARN.
  I-003  currency: the invoice and every line state the same currency (MATERIAL when they disagree); a code that is not a
         three-letter ISO-style code is a WARN.

Money tolerance: abs(delta) <= max(1.00 currency unit, 0.1 % of the stated total): unit prices are rounded, totals are
often whole numbers.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.evidence import evidence_entry
from app.domain.schemas import CheckResult, ExtractedDocument, FieldRef, LineItem
from app.domain.units import normalize_unit, parse_number, to_kg, trailing_unit

MONEY_ABS_TOL = 1.0
MONEY_REL_TOL = 0.001
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def money_tolerance(total: float) -> float:
    return max(MONEY_ABS_TOL, MONEY_REL_TOL * abs(total))


def _number(ref: FieldRef | None) -> tuple[float | None, list[str]]:
    """(value, assumptions) of a printed amount; (None, []) when absent or unreadable."""
    if ref is None or ref.value is None:
        return None, []
    parsed = parse_number(ref.value)
    if parsed is None:
        return None, []
    return parsed.value, list(parsed.assumptions)


def _unit_word(text: str | None) -> str:
    """"PER MT" / "/MT" / "LENGTHS" -> "MT" / "MT" / "LENGTH": the unit a price or a quantity is stated in."""
    cleaned = re.sub(r"^(PER|/)\s*", "", str(text or "").strip().upper()).strip()
    cleaned = re.sub(r"[^A-Z ]", "", cleaned).strip()
    return cleaned[:-1] if cleaned.endswith("S") and len(cleaned) > 3 else cleaned


def _weight_in(unit: str, net: FieldRef | None) -> float | None:
    """The line's net weight expressed in ``unit`` (a weight unit), or None."""
    canonical = normalize_unit(unit)
    if canonical is None or net is None or net.value is None:
        return None
    parsed = parse_number(net.value)
    if parsed is None:
        return None
    kg = to_kg(parsed.value, getattr(net, "unit", None) or trailing_unit(net.value))
    if kg.error:
        return None
    return {"KG": kg.kg, "MT": kg.kg / 1000.0, "LB": kg.kg / 0.45359237, "G": kg.kg * 1000.0}[canonical]


def _reading_candidates(item: LineItem, qty: float, qty_unit: str) -> list[tuple[str, float]]:
    """(description, multiplier) pairs under which ``unit price x multiplier`` could be the line total."""
    out = [(f"per {qty_unit or 'unit of the quantity'}", qty)]
    for unit in ("MT", "KG"):
        weight = _weight_in(unit, item.net_weight_kg)
        if weight is not None:
            out.append((f"per {unit} of net weight", weight))
    return out


def check_line_arithmetic(invoice: ExtractedDocument) -> CheckResult | None:
    problems: list[str] = []
    warnings: list[str] = []
    evidence: list[dict[str, Any]] = []
    assumptions: list[str] = []
    verified = 0
    worst_delta = 0.0

    for index, item in enumerate(invoice.line_items):
        qty, qty_assumptions = _number(item.quantity)
        price, price_assumptions = _number(item.unit_price)
        total, total_assumptions = _number(item.total_value)
        if qty is None or price is None or total is None:
            continue  # a line that does not state all three cannot be checked
        for ref, name in ((item.quantity, "quantity"), (item.unit_price, "unit_price"), (item.total_value, "total_value")):
            evidence.append(evidence_entry(invoice.document_id, name, ref, line_item=index))
        line_assumptions = [*qty_assumptions, *price_assumptions, *total_assumptions]
        assumptions += line_assumptions

        qty_unit = _unit_word(trailing_unit(item.quantity.value if item.quantity else None))
        tol = money_tolerance(total)
        label = f"line {index + 1}"

        basis_text = item.unit_price_basis.value if item.unit_price_basis and item.unit_price_basis.value else None
        if basis_text:
            basis = _unit_word(basis_text)
            if normalize_unit(basis) is not None:  # priced per weight
                weight = _weight_in(basis, item.net_weight_kg) if basis != qty_unit else qty
                if weight is None:
                    warnings.append(f"{label}: priced {basis_text} but no net weight is stated to apply it to")
                    continue
                expected, reading = price * weight, f"{basis_text}: {price:g} x {weight:g}"
            elif basis == qty_unit or not qty_unit:
                expected, reading = price * qty, f"{basis_text}: {price:g} x {qty:g}"
            else:
                warnings.append(f"{label}: priced {basis_text} but the quantity is in {qty_unit}: not comparable")
                continue
            delta = abs(expected - total)
            worst_delta = max(worst_delta, delta)
            if delta <= tol or line_assumptions:
                if delta > tol:
                    warnings.append(f"{label}: {reading} = {expected:,.2f}, total {total:,.2f} (delta {delta:,.2f}), but a value was read with an assumption")
                else:
                    verified += 1
            else:
                problems.append(f"{label}: {reading} = {expected:,.2f} but the line total is {total:,.2f} (delta {delta:,.2f})")
            continue

        # no basis printed: the price is read as per unit of the quantity; another basis that reconciles is only a WARN
        candidates = _reading_candidates(item, qty, qty_unit)
        expected = price * qty
        delta = abs(expected - total)
        worst_delta = max(worst_delta, delta)
        if delta <= tol:
            verified += 1
            continue
        other = next((desc for desc, factor in candidates[1:] if abs(price * factor - total) <= tol), None)
        if other is not None:
            warnings.append(
                f"{label}: {price:g} x {qty:g} = {expected:,.2f} does not match the line total {total:,.2f}, but the total "
                f"is reached if the unit price is {other}; the invoice does not say what the price is per"
            )
            assumptions.append(f"unit price read as {other}")
        else:
            problems.append(f"{label}: {price:g} x {qty:g} = {expected:,.2f} but the line total is {total:,.2f} (delta {delta:,.2f}); no basis reconciles it")

    if not evidence:
        return None
    if problems:
        return CheckResult(check_id="I-001", severity="MATERIAL", message="Invoice line arithmetic does not hold: " + "; ".join(problems) + ".",
                           delta=worst_delta, evidence=evidence)
    if warnings or assumptions:
        return CheckResult(check_id="I-001", severity="WARN", message="Invoice line arithmetic could not be confirmed: " + "; ".join(warnings or assumptions) + ".",
                           delta=worst_delta or None, evidence=evidence, assumptions=list(dict.fromkeys(assumptions)))
    return CheckResult(check_id="I-001", severity="PASS",
                       message=f"Quantity x unit price equals the line total on {verified} line(s) (within {MONEY_ABS_TOL:g} or {MONEY_REL_TOL:.1%}).",
                       delta=worst_delta, evidence=evidence)


def check_invoice_total(invoice: ExtractedDocument) -> CheckResult | None:
    stated, stated_assumptions = _number(invoice.invoice_value)
    if stated is None:
        return None
    totals: list[float] = []
    evidence = [evidence_entry(invoice.document_id, "invoice_value", invoice.invoice_value)]
    assumptions = list(stated_assumptions)
    missing = 0
    for index, item in enumerate(invoice.line_items):
        value, line_assumptions = _number(item.total_value)
        if value is None:
            missing += 1
            continue
        totals.append(value)
        assumptions += line_assumptions
        evidence.append(evidence_entry(invoice.document_id, "total_value", item.total_value, line_item=index))
    if not totals:
        return None

    summed = sum(totals)
    delta = abs(stated - summed)
    tol = money_tolerance(stated)
    if missing:
        return CheckResult(
            check_id="I-002", severity="WARN", delta=delta, tolerance=tol, evidence=evidence,
            message=f"Invoice total cannot be compared with its lines: {missing} line(s) state no total (the {len(totals)} that do sum to {summed:,.2f}; the invoice states {stated:,.2f}).",
        )
    if delta <= tol and not assumptions:
        return CheckResult(check_id="I-002", severity="PASS", delta=delta, tolerance=tol, evidence=evidence,
                           message=f"Invoice total {stated:,.2f} equals the sum of its {len(totals)} line total(s) (delta {delta:,.2f}, tolerance {tol:,.2f}).")
    if delta <= tol:
        return CheckResult(check_id="I-002", severity="WARN", delta=delta, tolerance=tol, evidence=evidence,
                           message=f"Invoice total {stated:,.2f} matches the sum of its lines {summed:,.2f}, but a value was read with an assumption.",
                           assumptions=list(dict.fromkeys(assumptions)))
    direction = "exceeds" if stated > summed else "is below"
    return CheckResult(
        check_id="I-002", severity="WARN", delta=delta, tolerance=tol, evidence=evidence,
        message=(
            f"Invoice total {stated:,.2f} {direction} the sum of its line totals {summed:,.2f} by {delta:,.2f}. Charges or discounts "
            "that are not listed as lines would explain it; that is an assumption, so it is a warning, not a contradiction."
        ),
        assumptions=["a difference between the invoice total and its lines is attributed to charges or discounts not extracted as lines"],
    )


def check_currency(invoice: ExtractedDocument) -> CheckResult | None:
    stated: list[tuple[str, dict[str, Any]]] = []
    if invoice.invoice_currency and invoice.invoice_currency.value:
        stated.append((str(invoice.invoice_currency.value).strip().upper(), evidence_entry(invoice.document_id, "invoice_currency", invoice.invoice_currency)))
    for index, item in enumerate(invoice.line_items):
        if item.currency and item.currency.value:
            stated.append((str(item.currency.value).strip().upper(), evidence_entry(invoice.document_id, "currency", item.currency, line_item=index)))
    evidence = [entry for _, entry in stated]

    if not stated:
        if invoice.invoice_value is not None and invoice.invoice_value.value is not None:
            return CheckResult(check_id="I-003", severity="WARN", evidence=[evidence_entry(invoice.document_id, "invoice_value", invoice.invoice_value)],
                               message="The invoice states a value but no currency.")
        return None
    codes = sorted({code for code, _ in stated})
    if len(codes) > 1:
        return CheckResult(check_id="I-003", severity="MATERIAL", evidence=evidence,
                           message=f"The invoice states more than one currency: {', '.join(codes)}.")
    bad = [code for code in codes if not _CURRENCY.match(code)]
    if bad:
        return CheckResult(check_id="I-003", severity="WARN", evidence=evidence,
                           message=f"The currency '{bad[0]}' is not a three-letter currency code; it was not interpreted.")
    return CheckResult(check_id="I-003", severity="PASS", evidence=evidence,
                       message=f"Every stated currency is {codes[0]} ({len(stated)} value(s) checked).")


def run(docs: list[ExtractedDocument]) -> list[CheckResult]:
    """The invoice checks for the first commercial invoice of the bundle (a duplicate is already a D-DUP warning)."""
    invoice = next((d for d in docs if d.doc_type == "COMMERCIAL_INVOICE"), None)
    if invoice is None:
        return []
    results = [check_line_arithmetic(invoice), check_invoice_total(invoice), check_currency(invoice)]
    return [r for r in results if r is not None]
