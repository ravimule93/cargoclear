"""Indicative assessable value and duty exposure (services/valuation.py): the arithmetic and every assumption it states."""

from __future__ import annotations

import json
from typing import Callable

import pytest

from app.reference.loader import FILES, REFERENCE_DIR, Reference
from app.services import valuation
from tests.unit.material_fakes import GOOD_HEAT, bill_of_lading, certificate, invoice, line, packing, ref


def reference(*mutations: tuple[str, Callable[[dict], None]]) -> Reference:
    """The shipped tables, with some edited: the maths is proved with rates of the test's choosing."""
    raw = {name: json.loads((REFERENCE_DIR / filename).read_text(encoding="utf-8")) for name, (filename, _m) in FILES.items()}
    for name, mutate in mutations:
        mutate(raw[name])
    return Reference(**{name: model.model_validate(raw[name]) for name, (_f, model) in FILES.items()})


def estimate(*docs, destination="IN", ref=None):
    return valuation.estimate(list(docs), destination, ref)


def goods(**kw):
    return invoice(line("73043100", qty="25 MT", price=2460.0, total=61500.0, net=25000.0), value=61500.0, **kw)


# ---------------------------------------------------------------------------
# India: BCD + SWS + (ADD) + IGST
# ---------------------------------------------------------------------------


def test_fob_with_stated_freight_and_default_insurance_into_india() -> None:
    v = estimate(goods(incoterm="FOB TIANJIN", origin="INDIA"), bill_of_lading(freight=1850.0))

    # (61,500 + 1,850 + 1.125 % of 61,500) x 85
    assert v.status == "ESTIMATED" and v.incoterm == "FOB" and v.destination_currency == "INR" and v.invoice_currency == "USD"
    assert v.transaction_value == 61500.0 and v.freight == 1850.0 and v.insurance == pytest.approx(691.88, abs=0.01)
    assert v.assessable_value == pytest.approx(5443559.38, abs=0.01)
    by_name = {d.name: d for d in v.duties}
    assert list(by_name) == ["BCD", "SWS", "IGST"]                                       # origin India: no anti-dumping line
    assert by_name["BCD"].amount == pytest.approx(5443559.375 * 0.075, abs=0.01)
    assert by_name["SWS"].amount == pytest.approx(by_name["BCD"].amount * 0.10, abs=0.01)
    assert by_name["IGST"].base == pytest.approx(5443559.375 + by_name["BCD"].amount + by_name["SWS"].amount, abs=0.02)
    assert by_name["IGST"].amount == pytest.approx(by_name["IGST"].base * 0.18, abs=0.02)
    assert v.total_duty == pytest.approx(sum(d.amount for d in v.duties), abs=0.01)
    assert "insurance is not stated: the default 1.125 % of the FOB value is applied" in v.assumptions
    assert not any("freight is not stated" in a for a in v.assumptions)


def test_anti_dumping_duty_is_added_and_enters_the_igst_base() -> None:
    v = estimate(goods(incoterm="FOB", origin="CHINA"), bill_of_lading(freight=1850.0))

    by_name = {d.name: d for d in v.duties}
    assert list(by_name) == ["BCD", "SWS", "ADD", "IGST"] and by_name["ADD"].rate_pct == 12.0
    assert by_name["ADD"].amount == pytest.approx(v.assessable_value * 0.12, abs=0.01)
    assert by_name["IGST"].base == pytest.approx(v.assessable_value + by_name["BCD"].amount + by_name["SWS"].amount + by_name["ADD"].amount, abs=0.02)
    assert "ILLUSTRATIVE" in by_name["ADD"].note and any("illustrative reference entry" in a for a in v.assumptions)


def test_freight_and_insurance_default_to_the_statutory_percentages_when_not_stated() -> None:
    v = estimate(goods(incoterm="FOB"))

    assert v.freight == pytest.approx(12300.0) and v.insurance == pytest.approx(691.88, abs=0.01)
    assert "freight is not stated: the default 20 % of the FOB value is applied" in v.assumptions
    assert v.status == "ESTIMATED"


@pytest.mark.parametrize("what", ["freight", "insurance"])
def test_a_stated_cost_in_a_currency_without_a_rate_makes_the_estimate_partial_not_silently_smaller(what) -> None:
    inv = goods(incoterm="FOB", insurance=500.0 if what == "insurance" else None)
    if what == "insurance":
        inv.insurance_currency = ref("XYZ")
        v = estimate(inv, bill_of_lading(freight=1000.0))
    else:
        v = estimate(inv, bill_of_lading(freight=1000.0, currency="XYZ"))

    assert v.status == "PARTIAL", "the cost that could not be converted is named, not counted as zero without a word"
    assert f"no exchange rate XYZ to USD/INR for the stated {what}" in (v.reason or "")
    assert getattr(v, what) == 0.0


def test_the_incoterm_decides_what_is_added() -> None:
    cif = estimate(goods(incoterm="CIF MUMBAI"))
    cfr = estimate(goods(incoterm="CFR MUMBAI"))
    fob = estimate(goods(incoterm="FOB TIANJIN"), bill_of_lading(freight=1000.0))

    assert (cif.freight, cif.insurance) == (None, None) and cif.assessable_value == pytest.approx(61500 * 85)
    assert cfr.freight is None and cfr.insurance == pytest.approx(691.88, abs=0.01)
    assert fob.freight == 1000.0


def test_terms_beyond_cif_are_not_deducted_and_the_estimate_says_so() -> None:
    v = estimate(goods(incoterm="DDP MUMBAI"))

    assert (v.freight, v.insurance) == (None, None)
    assert any("DDP includes costs beyond CIF" in a and "may be overstated" in a for a in v.assumptions)


def test_exw_notes_that_inland_transport_is_not_added() -> None:
    assert any("inland transport" in a for a in estimate(goods(incoterm="EXW FACTORY")).assumptions)


def test_no_incoterm_is_read_as_fob() -> None:
    v = estimate(goods())

    assert v.incoterm is None and v.freight is not None
    assert any("no Incoterm is stated" in a and "read as FOB" in a for a in v.assumptions)


def test_the_exchange_rate_is_an_assumption_naming_its_origin() -> None:
    v = estimate(goods(incoterm="CIF"))

    assert v.exchange_rate == 85.0 and "ILLUSTRATIVE" in v.exchange_rate_note and "Bill of Entry is presented" in v.exchange_rate_note
    assert any(a.startswith("exchange rate USD to INR = 85") for a in v.assumptions)


def test_unverified_tables_are_listed_as_an_assumption_and_verified_ones_are_not() -> None:
    assert any("duty rates: demo-curated data, not verified" in a for a in estimate(goods(incoterm="CIF")).assumptions)

    def verify(table):
        table["verification"] = {"status": "verified", "reviewer": "R. Rao", "date": "2026-11-02"}

    ref = reference(("duty_rates", verify), ("exchange_rates", verify))
    v = estimate(goods(incoterm="CIF"), ref=ref)

    assert not any("not verified" in a for a in v.assumptions)


def test_a_notified_exchange_rate_is_not_called_illustrative() -> None:
    def notify(table):
        table["rates"][0].update(illustrative=False, effective_from="2026-10-15", reference="Notification X")

    v = estimate(goods(incoterm="CIF"), ref=reference(("exchange_rates", notify)))

    assert "ILLUSTRATIVE" not in v.exchange_rate_note and "2026-10-15" in v.exchange_rate_note


def test_freight_in_another_currency_is_converted_through_the_destination_currency() -> None:
    def add_eur(table):
        table["rates"].append({"from": "EUR", "to": "INR", "rate": 100.0, "effective_from": None, "reference": None, "illustrative": True})

    v = estimate(goods(incoterm="FOB"), bill_of_lading(freight=1000.0, currency="EUR"), ref=reference(("exchange_rates", add_eur)))

    assert v.freight == pytest.approx(1000 * 100 / 85, abs=0.01)         # EUR 1,000 expressed in USD at 100 / 85


# ---------------------------------------------------------------------------
# Singapore: customs duty + GST
# ---------------------------------------------------------------------------


def test_singapore_levies_gst_on_the_cif_value_and_no_customs_duty() -> None:
    v = estimate(invoice(line("73041900"), incoterm="CIF SINGAPORE"), destination="SG")

    assert v.assessable_value == pytest.approx(84000 * 1.30) and v.destination_currency == "SGD"
    assert [(d.name, d.rate_pct, d.amount) for d in v.duties] == [("Customs duty", 0.0, 0.0), ("GST", 9.0, 9828.0)]
    assert v.total_duty == 9828.0 and v.freight is None


# ---------------------------------------------------------------------------
# what the estimate says when it cannot give a figure
# ---------------------------------------------------------------------------


def test_a_destination_without_rules_gets_no_estimate() -> None:
    v = estimate(goods(), destination="XX")

    assert v.status == "NOT_AVAILABLE" and "no duty rules for destination 'XX'" in v.reason and v.duties == []


def test_no_invoice_no_value_no_currency_or_two_currencies_give_no_estimate() -> None:
    assert "no commercial invoice" in estimate(packing()).reason
    assert "states no value" in estimate(invoice(line(total=None, price=None), value=None)).reason
    assert "states no currency" in estimate(invoice(line(currency=None), currency=None)).reason
    mixed = estimate(invoice(line(currency="EUR"), currency="USD"))
    assert mixed.status == "NOT_AVAILABLE" and "EUR, USD" in mixed.reason and "I-003" in mixed.reason


def test_without_an_invoice_total_the_sum_of_the_lines_is_used_and_said() -> None:
    v = estimate(invoice(line(), value=None, incoterm="CIF"))

    assert v.transaction_value == 84000.0 and any("sum of its line totals" in a for a in v.assumptions)


def test_without_an_exchange_rate_there_is_no_assessable_value() -> None:
    v = estimate(invoice(line(currency="EUR"), currency="EUR", incoterm="CIF"))

    assert v.status == "PARTIAL" and v.assessable_value is None and v.duties == []
    assert "no exchange rate EUR to INR" in v.reason and v.transaction_value == 84000.0


def test_without_a_declared_hs_code_or_a_rate_for_it_the_value_is_given_and_the_duty_is_not() -> None:
    no_code = estimate(invoice(line(hs=""), incoterm="CIF"))
    no_rate = estimate(invoice(line("10019910"), incoterm="CIF"))

    assert no_code.status == no_rate.status == "PARTIAL"
    assert no_code.assessable_value and no_code.duties == [] and "No HS code is declared" in no_code.reason
    assert no_rate.assessable_value and "no IN duty rates for HS 1001.99.10" in no_rate.reason


def test_missing_freight_without_a_default_makes_the_estimate_partial() -> None:
    def no_defaults(table):
        table["destinations"]["IN"].update(freight_pct_of_fob=None, insurance_pct_of_fob=None)

    v = estimate(goods(incoterm="FOB"), ref=reference(("valuation_defaults", no_defaults)))

    assert v.status == "PARTIAL" and "freight is not stated and the reference data has no default" in v.reason
    assert v.assessable_value == pytest.approx(61500 * 85) and v.total_duty is not None


def test_several_declared_codes_use_the_first_and_say_so() -> None:
    two = invoice(line("73043100"), line("73043900"), incoterm="CIF", value=168000.0)

    assert any("2 different HS codes are declared" in a for a in estimate(two).assumptions)


# ---------------------------------------------------------------------------
# "what if it were the code the chemistry points to?"
# ---------------------------------------------------------------------------


def test_the_estimate_is_also_given_under_the_subheading_the_chemistry_points_to() -> None:
    def rates(table):
        table["destinations"]["IN"]["entries"].append({"prefix": "730451", "bcd_pct": 12.5, "sws_pct_of_bcd": 10.0, "igst_pct": 18.0})

    alloy = certificate({"H1": {**GOOD_HEAT, "Cr": "0.35"}})
    v = estimate(goods(incoterm="CIF"), alloy, ref=reference(("duty_rates", rates)))

    assert v.hs_code == "73043100" and v.implied_hs_code == "730451"
    assert v.implied_total_duty > v.total_duty                                   # 12.5 % BCD against 7.5 %
    plain = estimate(goods(incoterm="CIF"), certificate(), ref=reference(("duty_rates", rates)))
    assert plain.implied_hs_code is None and plain.implied_total_duty is None


def test_the_estimate_never_exceeds_what_it_claims_to_be() -> None:
    v = estimate(goods(incoterm="CIF"))

    assert "Not a customs determination" in v.disclaimer and v.rule_set == "demo-curated"
    assert v.model_dump(mode="json")["status"] == "ESTIMATED"
