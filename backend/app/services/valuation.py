"""Indicative assessable value and duty exposure.

Pure Python, no I/O, no LLM. DECISION SUPPORT for the authorised Custom House Agent: an estimate with every guess
listed, never a customs determination and never an amount payable. It does not change the assessment status (that
stays "are the documents consistent and complete"); it answers "what would the duty exposure roughly be, and what did you
have to assume to say so".

Steps (every one that rests on a guess adds a line to ``assumptions``):

  1. The transaction value: the invoice's stated value (else the sum of its lines), in the invoice currency.
  2. Incoterm -> CIF basis. FOB/FCA/FAS/EXW: add freight and insurance. CFR/CPT: add insurance. CIF/CIP: nothing.
     DAP/DPU/DDP: the value already includes costs beyond CIF; they are NOT deducted (the estimate may overstate).
     No Incoterm stated: the value is read as FOB.
  3. Freight and insurance: as stated on the invoice / bill of lading; else the statutory default of the destination
     (reference ``valuation_defaults``), else nothing is added and the result is PARTIAL.
  4. Exchange rate to the destination currency (reference ``exchange_rates``): without one there is no assessable value.
  5. Duties by the destination's model (reference ``duty_rates``): India: BCD, SWS on the BCD, anti-dumping duty if an
     entry matches, IGST on value + BCD + SWS + ADD. Singapore: customs duty (none here) and GST on CIF + duty.
  6. If the certificate's chemistry points to another subheading (services/metallurgy.py), the same estimate is also
     given under that subheading.

The rates in the reference data are demo-curated and unverified until a reviewer says otherwise: that is itself listed as
an assumption.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.domain.hs import hs_text
from app.domain.schemas import DutyLine, ExtractedDocument, ValuationEstimate
from app.domain.units import parse_number
from app.reference.loader import Reference, get_reference
from app.services import metallurgy, trade_remedies

_INCOTERM = re.compile(r"\b(EXW|FCA|FAS|FOB|CFR|CNF|CPT|CIF|CIP|DAP|DPU|DAT|DDP)\b")
_ADDS_BOTH = {"EXW", "FCA", "FAS", "FOB"}
_ADDS_INSURANCE = {"CFR", "CNF", "CPT"}
_ALREADY_CIF = {"CIF", "CIP"}
_BEYOND_CIF = {"DAP", "DPU", "DAT", "DDP"}


def _amount(ref: Any) -> float | None:
    if ref is None or ref.value is None:
        return None
    parsed = parse_number(ref.value)
    return parsed.value if parsed is not None else None


def _currency(ref: Any) -> str | None:
    text = hs_text(ref.value).upper() if ref is not None and ref.value is not None else ""
    return text or None


def _first(docs: list[ExtractedDocument], doc_type: str) -> ExtractedDocument | None:
    return next((d for d in docs if d.doc_type == doc_type), None)


def _round(value: float) -> float:
    return round(value + 1e-9, 2)


def _unverified(reference: Reference, *names: str) -> list[str]:
    out = []
    for name in names:
        table = getattr(reference, name)
        if table.verification.status != "verified":
            out.append(f"{name.replace('_', ' ')}: {table.rule_set} data, not verified")
    return out


def _duties(model: str, entry: Any, assessable: float, add_rate_pct: float | None) -> list[DutyLine]:
    lines: list[DutyLine] = []
    if model == "IN_BCD_SWS_IGST":
        bcd = assessable * (entry.bcd_pct or 0.0) / 100
        sws = bcd * (entry.sws_pct_of_bcd or 0.0) / 100
        add = assessable * add_rate_pct / 100 if add_rate_pct is not None else 0.0
        igst_base = assessable + bcd + sws + add
        lines.append(DutyLine(name="BCD", rate_pct=entry.bcd_pct, base=_round(assessable), amount=_round(bcd), note="basic customs duty"))
        lines.append(DutyLine(name="SWS", rate_pct=entry.sws_pct_of_bcd, base=_round(bcd), amount=_round(sws), note="social welfare surcharge, on the BCD"))
        if add_rate_pct is not None:
            lines.append(DutyLine(name="ADD", rate_pct=add_rate_pct, base=_round(assessable), amount=_round(add),
                                  note="anti-dumping duty: ILLUSTRATIVE entry, producer-specific in practice"))
        lines.append(DutyLine(name="IGST", rate_pct=entry.igst_pct, base=_round(igst_base), amount=_round(igst_base * (entry.igst_pct or 0.0) / 100),
                              note="on value + BCD + SWS" + (" + anti-dumping duty" if add_rate_pct is not None else "")))
    else:  # SG_GST
        customs = assessable * (entry.customs_duty_pct or 0.0) / 100
        lines.append(DutyLine(name="Customs duty", rate_pct=entry.customs_duty_pct, base=_round(assessable), amount=_round(customs)))
        gst_base = assessable + customs
        lines.append(DutyLine(name="GST", rate_pct=entry.gst_pct, base=_round(gst_base), amount=_round(gst_base * (entry.gst_pct or 0.0) / 100),
                              note="on the CIF value + duty"))
    return lines


def estimate(docs: list[ExtractedDocument], destination: str, reference: Reference | None = None) -> ValuationEstimate:
    reference = reference or get_reference()
    dest = (destination or "").upper()
    duty_table = reference.duty_rates.destinations.get(dest)

    def unavailable(reason: str, **extra: Any) -> ValuationEstimate:
        return ValuationEstimate(destination_country=dest, status="NOT_AVAILABLE", reason=reason, **extra)

    if duty_table is None:
        return unavailable(f"The reference data has no duty rules for destination '{dest}'.")
    invoice = _first(docs, "COMMERCIAL_INVOICE")
    if invoice is None:
        return unavailable("There is no commercial invoice in the bundle, so there is no transaction value.")

    assumptions: list[str] = []
    value = _amount(invoice.invoice_value)
    if value is None:
        totals = [v for item in invoice.line_items if (v := _amount(item.total_value)) is not None]
        value = sum(totals) if totals else None
        if value is not None:
            assumptions.append("the invoice states no total: the sum of its line totals is used as the transaction value")
    if value is None:
        return unavailable("The invoice states no value.")
    currencies = {c for c in [_currency(invoice.invoice_currency), *(_currency(i.currency) for i in invoice.line_items)] if c}
    if not currencies:
        return unavailable("The invoice states no currency.")
    if len(currencies) > 1:
        return unavailable(f"The invoice states more than one currency ({', '.join(sorted(currencies))}): see check I-003.")
    inv_cur = next(iter(currencies))

    # --- Incoterm -> what to add
    incoterm_text = hs_text(invoice.incoterm.value).upper() if invoice.incoterm and invoice.incoterm.value else ""
    match = _INCOTERM.search(incoterm_text)
    term = match.group(1) if match else None
    if term is None:
        assumptions.append("no Incoterm is stated: the invoice value is read as FOB (freight and insurance are added)")
        term = "FOB"
    elif term in _BEYOND_CIF:
        assumptions.append(f"{term} includes costs beyond CIF (delivery to destination); they are not deducted, so the value may be overstated")
    if term in ("EXW", "FCA"):
        assumptions.append(f"{term}: inland transport to the port of export is not added")
    add_freight = term in _ADDS_BOTH
    add_insurance = term in _ADDS_BOTH or term in _ADDS_INSURANCE

    # --- exchange rates (to the destination currency)
    dest_cur = duty_table.currency
    fx_note: str | None = None

    def rate(source: str) -> float | None:
        found = reference.exchange_rates.rate(source, dest_cur)
        return found.rate if found else None

    inv_rate = rate(inv_cur)
    defaults = reference.valuation_defaults.destinations.get(dest)

    def stated(doc: ExtractedDocument | None, amount_field: str, currency_field: str) -> tuple[float, str] | None:
        if doc is None:
            return None
        amount = _amount(getattr(doc, amount_field))
        if amount is None:
            return None
        return amount, _currency(getattr(doc, currency_field)) or inv_cur

    bol = _first(docs, "BILL_OF_LADING")
    freight_src = stated(invoice, "freight_amount", "freight_currency") or stated(bol, "freight_amount", "freight_currency")
    insurance_src = stated(invoice, "insurance_amount", "insurance_currency") or stated(bol, "insurance_amount", "insurance_currency")

    partial: list[str] = []
    freight_inv = insurance_inv = 0.0  # in the invoice currency
    if add_freight:
        if freight_src is not None:
            amount, cur = freight_src
            factor = 1.0 if cur == inv_cur else ((rate(cur) or 0.0) / inv_rate if inv_rate else 0.0)
            if factor == 0.0:
                partial.append(f"no exchange rate {cur} to {inv_cur}/{dest_cur} for the stated freight")
            freight_inv = amount * factor
        elif defaults and defaults.freight_pct_of_fob is not None:
            freight_inv = value * defaults.freight_pct_of_fob / 100
            assumptions.append(f"freight is not stated: the default {defaults.freight_pct_of_fob:g} % of the FOB value is applied")
        else:
            partial.append("freight is not stated and the reference data has no default for this destination")
    if add_insurance:
        if insurance_src is not None:
            amount, cur = insurance_src
            factor = 1.0 if cur == inv_cur else ((rate(cur) or 0.0) / inv_rate if inv_rate else 0.0)
            if factor == 0.0:
                partial.append(f"no exchange rate {cur} to {inv_cur}/{dest_cur} for the stated insurance")
            insurance_inv = amount * factor
        elif defaults and defaults.insurance_pct_of_fob is not None:
            insurance_inv = value * defaults.insurance_pct_of_fob / 100
            assumptions.append(f"insurance is not stated: the default {defaults.insurance_pct_of_fob:g} % of the FOB value is applied")
        else:
            partial.append("insurance is not stated and the reference data has no default for this destination")

    codes = metallurgy.declared_codes(docs)
    declared = codes[0] if codes else None
    if len(codes) > 1:
        assumptions.append(f"{len(codes)} different HS codes are declared: the first ({metallurgy._fmt_code(codes[0].digits)}) is used")

    result: dict[str, Any] = dict(
        destination_country=dest, incoterm=term if incoterm_text else None, invoice_currency=inv_cur, destination_currency=dest_cur,
        transaction_value=_round(value), freight=_round(freight_inv) if add_freight else None,
        insurance=_round(insurance_inv) if add_insurance else None,
        hs_code=declared.digits if declared else None,
        rule_set=reference.duty_rates.rule_set, regulation_ref=reference.duty_rates.regulation_ref,
    )

    if inv_rate is None:
        return ValuationEstimate(status="PARTIAL", reason=f"The reference data has no exchange rate {inv_cur} to {dest_cur}, so no assessable value in {dest_cur} can be given.",
                                 assumptions=assumptions + _unverified(reference, "duty_rates"), **result)
    fx = reference.exchange_rates.rate(inv_cur, dest_cur)
    assert fx is not None
    fx_note = ("ILLUSTRATIVE rate, not a customs notification" if fx.illustrative else f"rate notified {fx.effective_from or 'date not stated'}")
    if dest == "IN":
        fx_note += "; for India the applicable rate is the one in force when the Bill of Entry is presented (no date is applied here)"
    assumptions.append(f"exchange rate {inv_cur} to {dest_cur} = {fx.rate:g} ({fx_note})")

    assessable = (value + freight_inv + insurance_inv) * inv_rate
    result.update(exchange_rate=inv_rate, exchange_rate_note=fx_note, assessable_value=_round(assessable))

    if declared is None:
        return ValuationEstimate(status="PARTIAL", reason="No HS code is declared, so no duty rates can be looked up.",
                                 assumptions=assumptions + _unverified(reference, "duty_rates"), **result)

    add_matches = trade_remedies.anti_dumping_matches(docs, dest, reference)

    def duties_for(digits: str, implied: bool) -> list[DutyLine] | None:
        entry = duty_table.entry_for(digits)
        if entry is None:
            return None
        add = next((m.entry.rate_pct_of_assessable_value for m in add_matches if m.implied == implied and m.hs_digits == digits), None)
        return _duties(duty_table.model, entry, assessable, add)

    lines = duties_for(declared.digits, False)
    if lines is None:
        return ValuationEstimate(status="PARTIAL", reason=f"The reference data has no {dest} duty rates for HS {metallurgy._fmt_code(declared.digits)}.",
                                 assumptions=assumptions + _unverified(reference, "duty_rates"), **result)
    total = _round(sum(line.amount for line in lines))

    implied_code = implied_total = None
    assessment = metallurgy.assess_alloy_status(docs, reference)
    if assessment is not None and assessment.alloy_class in ("alloy", "stainless"):
        rule = reference.hs_rules.alloy_class_of(declared.digits)
        twin = reference.hs_rules.alloy_twin_subheading.get(declared.digits[:6], {}).get(assessment.alloy_class)
        if rule is not None and rule.alloy_class not in (assessment.alloy_class, "any") and twin:
            implied_lines = duties_for(twin, True)
            if implied_lines is not None:
                implied_code, implied_total = twin, _round(sum(line.amount for line in implied_lines))

    if any(line.name == "ADD" for line in lines):
        assumptions.append("the anti-dumping rate is an illustrative reference entry (no notification, producer-specific in practice)")
    used = ["duty_rates", "exchange_rates"] + (["valuation_defaults"] if any("default" in a for a in assumptions) else []) + (
        ["anti_dumping"] if add_matches else [])
    assumptions += _unverified(reference, *used)

    status: Literal["ESTIMATED", "PARTIAL"] = "PARTIAL" if partial else "ESTIMATED"
    return ValuationEstimate(
        status=status, reason="; ".join(partial) or None, duties=lines, total_duty=total,
        implied_hs_code=implied_code, implied_total_duty=implied_total, assumptions=list(dict.fromkeys(assumptions)), **result,
    )
