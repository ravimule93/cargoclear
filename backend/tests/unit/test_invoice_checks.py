"""I-001 line arithmetic, I-002 invoice total, I-003 currency (services/invoice_checks.py)."""

from __future__ import annotations

import pytest

from app.services import invoice_checks
from tests.unit.material_fakes import invoice, line, result, severity


def run(*lines, **kwargs):
    return invoice_checks.run([invoice(*lines, **kwargs)])


# ---------------------------------------------------------------------------
# I-001
# ---------------------------------------------------------------------------


def test_a_line_that_adds_up_passes_and_cites_its_three_numbers() -> None:
    results = run(line())

    check = result(results, "I-001")
    assert check.severity == "PASS" and check.assumptions == []
    assert [(e["field"], e["line_item"]) for e in check.evidence] == [("quantity", 0), ("unit_price", 0), ("total_value", 0)]
    assert check.evidence[0]["raw_value"] == "120 LENGTHS" and check.evidence[0]["bbox"]


def test_rounded_unit_prices_are_tolerated() -> None:
    # 33.333 x 3 = 99.999: a total of 100.00 is within the one-currency-unit tolerance
    assert severity(run(line(qty="3 PCS", price=33.333, total=100.0), value=100.0), "I-001") == "PASS"


def test_a_line_that_does_not_add_up_under_any_basis_is_material() -> None:
    results = run(line(price=700.0, total=84500.0), value=84500.0)

    check = result(results, "I-001")
    assert check.severity == "MATERIAL"
    assert "700 x 120 = 84,000.00" in check.message and "84,500.00" in check.message and "no basis reconciles" in check.message


def test_a_printed_basis_makes_a_mismatch_material_and_a_match_a_pass() -> None:
    per_mt = line(qty="25 MT", price=2460.0, total=61500.0, basis="PER MT", net=25000.0)
    assert severity(run(per_mt, value=61500.0), "I-001") == "PASS"

    wrong = line(qty="25 MT", price=2460.0, total=70000.0, basis="PER MT", net=25000.0)
    assert severity(run(wrong, value=70000.0), "I-001") == "MATERIAL"


def test_a_price_per_weight_is_applied_to_the_net_weight_when_the_quantity_is_in_pieces() -> None:
    # 120 lengths, 14,000 kg net, USD 6,000 per MT: 14 MT x 6,000 = 84,000
    check = result(run(line(qty="120 LENGTHS", price=6000.0, total=84000.0, basis="PER MT", net=14000.0)), "I-001")

    assert check.severity == "PASS"


def test_without_a_printed_basis_another_basis_that_reconciles_is_only_a_warning() -> None:
    """120 lengths x 6,000 = 720,000 does not match 84,000, but 14 MT x 6,000 does: the invoice does not say per what."""
    check = result(run(line(qty="120 LENGTHS", price=6000.0, total=84000.0, net=14000.0)), "I-001")

    assert check.severity == "WARN"
    assert "per MT of net weight" in check.message and "does not say what the price is per" in check.message
    assert check.assumptions == ["unit price read as per MT of net weight"]


def test_a_price_basis_that_does_not_fit_the_quantity_unit_is_a_warning() -> None:
    check = result(run(line(qty="120 LENGTHS", price=700.0, total=84000.0, basis="PER BUNDLE")), "I-001")

    assert check.severity == "WARN" and "not comparable" in check.message


def test_a_thousands_separator_guess_is_never_a_pass() -> None:
    """'14,280' could be 14.28 or 14280: parse_number records the assumption, so the check cannot be a PASS."""
    check = result(run(line(qty="14,280 KGS", price=5.88, total=83966.4, net=14280.0)), "I-001")

    assert check.severity == "WARN" and check.assumptions


def test_lines_that_state_no_price_are_not_checked() -> None:
    assert result(run(line(price=None, total=None), value=84000.0), "I-001") is None
    assert result(run(line(price=None)), "I-001") is None


def test_an_unreadable_number_is_skipped_not_guessed() -> None:
    assert result(run(line(qty="a lot", price=700.0, total=84000.0)), "I-001") is None


def test_one_bad_line_makes_the_check_material_and_names_the_line() -> None:
    results = run(line(), line(qty="10 PCS", price=5.0, total=999.0), value=84999.0)

    check = result(results, "I-001")
    assert check.severity == "MATERIAL" and "line 2" in check.message and "line 1" not in check.message


# ---------------------------------------------------------------------------
# I-002
# ---------------------------------------------------------------------------


def test_the_invoice_total_equals_the_sum_of_the_lines() -> None:
    results = run(line(total=60000.0, qty="100 PCS", price=600.0), line(total=24000.0, qty="40 PCS", price=600.0), value=84000.0)

    assert severity(results, "I-002") == "PASS"
    assert len(result(results, "I-002").evidence) == 3


def test_a_total_that_differs_from_its_lines_is_a_warning_with_the_direction_and_the_explanation_as_an_assumption() -> None:
    above = result(run(line(), value=86000.0), "I-002")
    below = result(run(line(), value=80000.0), "I-002")

    assert above.severity == below.severity == "WARN"
    assert "exceeds" in above.message and "2,000.00" in above.message
    assert "is below" in below.message
    assert above.assumptions and "charges or discounts" in above.assumptions[0]


def test_a_line_without_a_total_makes_the_comparison_a_warning() -> None:
    check = result(run(line(), line(total=None, price=None), value=84000.0), "I-002")

    assert check.severity == "WARN" and "1 line(s) state no total" in check.message


def test_no_total_or_no_line_totals_means_no_check() -> None:
    assert result(run(line(), value=None), "I-002") is None
    assert result(run(line(total=None, price=None), value=84000.0), "I-002") is None


# ---------------------------------------------------------------------------
# I-003
# ---------------------------------------------------------------------------


def test_one_currency_everywhere_passes() -> None:
    check = result(run(line(), currency="USD"), "I-003")

    assert check.severity == "PASS" and "USD" in check.message and len(check.evidence) == 2


def test_two_currencies_are_a_contradiction() -> None:
    check = result(run(line(currency="EUR"), currency="USD"), "I-003")

    assert check.severity == "MATERIAL" and "EUR, USD" in check.message


def test_a_currency_that_is_not_a_code_is_not_interpreted() -> None:
    check = result(run(line(currency="US$"), currency="US$"), "I-003")

    assert check.severity == "WARN" and "US$" in check.message


def test_a_value_without_any_currency_is_a_warning() -> None:
    check = result(run(line(currency=None), currency=None), "I-003")

    assert check.severity == "WARN" and "no currency" in check.message


def test_the_checks_use_the_first_invoice_and_need_one() -> None:
    from tests.unit.material_fakes import packing

    assert invoice_checks.run([packing()]) == []
    assert [r.check_id for r in invoice_checks.run([invoice(), invoice(document_id="inv-2", value=1.0)])] == ["I-001", "I-002", "I-003"]


@pytest.mark.parametrize(("total", "tol"), [(100.0, 1.0), (84000.0, 84.0), (0.0, 1.0), (-2000.0, 2.0)])
def test_money_tolerance_is_one_unit_or_a_tenth_of_a_percent(total, tol) -> None:
    assert invoice_checks.money_tolerance(total) == tol
