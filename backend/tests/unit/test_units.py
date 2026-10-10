"""Unit layer (app/domain/units.py): number parsing, unit aliases, conversion to kg.

A parsed value carries the ASSUMPTIONS that were needed to read it; the calculation engine turns any
assumption into a WARN. These tests pin both the values and the exact assumptions.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.domain import units
from app.domain.units import UnknownUnit, normalize_unit, parse_number, to_kg

# The autouse hermetic_test_env fixture is function-scoped; these properties are pure, so sharing it is fine.
PURE = settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=200, deadline=None)


# ---------------------------------------------------------------------------
# B1  parse_number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   ", " ", "   "])
def test_empty_inputs_are_none(raw) -> None:
    assert parse_number(raw) is None


@pytest.mark.parametrize(("raw", "expected"), [(14280, 14280.0), (14280.5, 14280.5), (0, 0.0), (0.0, 0.0)])
def test_numbers_pass_through(raw, expected) -> None:
    parsed = parse_number(raw)
    assert parsed is not None
    assert parsed.value == expected
    assert parsed.assumptions == []


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf"), True, False])
def test_non_finite_and_bool_are_none(raw) -> None:
    assert parse_number(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14280", 14280.0),
        ("14280.50", 14280.5),
        ("14,280.50", 14280.5),
        ("14 280.5", 14280.5),
        ("14 280.5", 14280.5),  # no-break space as the grouping separator
        ("1 234 567", 1234567.0),
        ("14.280,50", 14280.5),  # both marks present: the LAST one is the decimal mark
        ("1,234,567.89", 1234567.89),
        ("1.234.567,89", 1234567.89),
        ("  14280  ", 14280.0),
        ("0.5", 0.5),
        ("007", 7.0),
    ],
)
def test_unambiguous_formats_carry_no_assumption(raw, expected) -> None:
    parsed = parse_number(raw)
    assert parsed is not None, raw
    assert parsed.value == pytest.approx(expected)
    assert parsed.assumptions == [], raw


def test_lone_comma_before_three_digits_is_a_thousands_separator_but_an_assumption() -> None:
    parsed = parse_number("14,280")
    assert parsed is not None
    assert parsed.value == 14280.0
    assert parsed.assumptions == ["thousands separator assumed for '14,280'"]


@pytest.mark.parametrize(("raw", "expected"), [("14280,5", 14280.5), ("14280,50", 14280.5), ("0,5", 0.5)])
def test_lone_comma_before_one_or_two_digits_is_a_decimal_comma_assumption(raw, expected) -> None:
    parsed = parse_number(raw)
    assert parsed is not None
    assert parsed.value == pytest.approx(expected)
    assert parsed.assumptions == [f"decimal comma assumed for '{raw}'"]


def test_lone_dot_before_three_digits_is_a_decimal_point_but_an_assumption() -> None:
    """'14.280' is 14.28 in English notation but 14 280 in German notation: say so instead of guessing silently."""
    parsed = parse_number("14.280")
    assert parsed is not None
    assert parsed.value == pytest.approx(14.28)
    assert parsed.assumptions == ["decimal point assumed for '14.280'"]


@pytest.mark.parametrize(("raw", "expected"), [("1 234,5", 1234.5), ("14 280,50", 14280.5)])
def test_space_grouped_number_with_a_comma_is_a_decimal_comma_assumption(raw, expected) -> None:
    """Space already groups the thousands, so a following comma can only be the decimal mark."""
    parsed = parse_number(raw)
    assert parsed is not None
    assert parsed.value == pytest.approx(expected)
    assert parsed.assumptions == [f"decimal comma assumed for '{raw}'"]


@pytest.mark.parametrize("raw", [b"14280", [14280], {"v": 1}, object()])
def test_other_types_are_none(raw) -> None:
    assert parse_number(raw) is None


def test_multiple_commas_in_valid_groups_are_unambiguous_thousands() -> None:
    parsed = parse_number("1,234,567")
    assert parsed is not None
    assert parsed.value == 1234567.0
    assert parsed.assumptions == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14,280.50 KGS", 14280.5),
        ("14280KG", 14280.0),
        ("14280 kg.", 14280.0),
        ("5 M/T", 5.0),
        ("14 METRIC TONS", 14.0),
        ("14 280.5 lbs", 14280.5),
    ],
)
def test_trailing_unit_word_is_stripped(raw, expected) -> None:
    parsed = parse_number(raw)
    assert parsed is not None, raw
    assert parsed.value == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "abc", "KGS", "N/A", "14O80", "1.2.3", "1.234.567", "1,2,3", "14,28.50", "14,2800", "1,2345",
        "14280,", ",", ".", ",5.", "-5", "+5", "1e5", "12 34", "14 28 0", "14280..5", "14,,280", "٣٤",
    ],
)
def test_garbage_is_none(raw) -> None:
    assert parse_number(raw) is None, raw


@PURE
@given(st.floats(min_value=0, max_value=1e7, allow_nan=False, allow_infinity=False))
def test_property_grouped_two_decimal_formatting_round_trips(x: float) -> None:
    parsed = parse_number(f"{x:,.2f}")
    assert parsed is not None
    assert parsed.value == pytest.approx(x, abs=0.005)
    assert parsed.assumptions == []


@PURE
@given(st.floats(min_value=0, max_value=1e7, allow_nan=False, allow_infinity=False))
def test_property_plain_formatting_round_trips(x: float) -> None:
    parsed = parse_number(f"{x:.2f}")
    assert parsed is not None
    assert parsed.value == pytest.approx(x, abs=0.005)
    assert parsed.assumptions == []


@PURE
@given(st.integers(min_value=0, max_value=10**9))
def test_property_integers_in_both_notations_agree(n: int) -> None:
    plain = parse_number(str(n))
    spaced = parse_number(f"{n:,}".replace(",", " "))
    assert plain is not None and spaced is not None
    assert plain.value == spaced.value == float(n)


@PURE
@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz!@#$%^&*_=~", min_size=1, max_size=12))
def test_property_text_without_digits_is_none(text: str) -> None:
    assert parse_number(text) is None


# ---------------------------------------------------------------------------
# B2  normalize_unit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        *[(r, "KG") for r in ("KG", "kg", "Kgs", "KGS", "KG.", "kilo", "KILOS", "kilogram", "Kilograms", " KGS ")],
        *[(r, "MT") for r in ("MT", "mt", "M/T", "m/t", "TONNE", "tonnes", "Tonne(s)", "TONS(metric)", "tons (metric)",
                              "METRIC TON", "Metric Tons", "METRIC TON(S)")],
        *[(r, "LB") for r in ("LB", "lb", "LBS", "lbs.", "pound", "POUNDS")],
        *[(r, "G") for r in ("G", "g", "GM", "gm", "gram", "GRAMS")],
    ],
)
def test_unit_aliases(raw, canonical) -> None:
    assert normalize_unit(raw) == canonical


@pytest.mark.parametrize("raw", [None, "", "  ", "XYZ", "TON", "TONS", "T", "KT", "OZ", "PCS", "123"])
def test_unknown_units_normalise_to_none(raw) -> None:
    """Plain TON/TONS is deliberately unknown: it is 907 kg (US) or 1016 kg (UK), not the metric tonne."""
    assert normalize_unit(raw) is None


def test_require_known_unit_raises_for_unknown_non_empty_units() -> None:
    assert units.require_known_unit("kgs") == "KG"
    assert units.require_known_unit(None) is None
    assert units.require_known_unit("") is None
    with pytest.raises(UnknownUnit) as excinfo:
        units.require_known_unit("furlongs")
    assert excinfo.value.raw == "furlongs"
    assert "furlongs" in str(excinfo.value)


# ---------------------------------------------------------------------------
# B3  to_kg
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", [None, "", "   "])
def test_missing_unit_is_assumed_kg(unit) -> None:
    q = to_kg(14000.0, unit)
    assert q.kg == 14000.0
    assert q.assumptions == ["no unit stated; assumed kg"]
    assert q.error is None


@pytest.mark.parametrize(
    ("unit", "value", "kg"),
    [("KGS", 14000.0, 14000.0), ("kg", 1.5, 1.5), ("MT", 14.28, 14280.0), ("M/T", 2.0, 2000.0),
     ("LBS", 100.0, 45.359237), ("lb", 1.0, 0.45359237), ("G", 500.0, 0.5), ("grams", 2500.0, 2.5)],
)
def test_recognised_units_convert_with_no_assumption(unit, value, kg) -> None:
    q = to_kg(value, unit)
    assert q.kg == pytest.approx(kg)
    assert q.assumptions == []
    assert q.error is None


def test_unrecognised_unit_is_an_error_not_a_guess() -> None:
    q = to_kg(14000.0, "furlongs")
    assert q.error == "unrecognised unit 'furlongs'"
    assert q.kg == 14000.0  # value passed through; callers must not compute with it
    assert q.assumptions == []


@PURE
@given(st.floats(min_value=0, max_value=1e7, allow_nan=False, allow_infinity=False))
def test_property_metric_tonnes_are_exactly_a_thousand_kg(x: float) -> None:
    assert to_kg(x, "MT").kg == x * 1000
    assert to_kg(x, "kgs").kg == x
    assert to_kg(x, "G").kg == x / 1000
    assert math.isclose(to_kg(x, "LBS").kg, x * 0.45359237, rel_tol=1e-12, abs_tol=1e-12)


@PURE
@given(
    st.floats(min_value=0, max_value=1e7, allow_nan=False, allow_infinity=False),
    st.sampled_from(["KG", "KGS", "KILOS", "MT", "M/T", "TONNES", "LB", "LBS", "G", "GM"]),
)
def test_property_conversion_is_monotonic_and_assumption_free(x: float, unit: str) -> None:
    q = to_kg(x, unit)
    assert q.error is None
    assert q.assumptions == []
    assert q.kg >= 0


# ---------------------------------------------------------------------------
# trailing_unit: the unit that is printed inside a value string ("14,280 KGS")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "unit"),
    [("14,280 KGS", "KGS"), ("14280KG", "KG"), ("5 M/T", "M/T"), ("14 METRIC TONS", "METRIC TONS"),
     ("14280", None), (14280.0, None), (None, None), ("", None), ("abc", None)],
)
def test_trailing_unit_extracts_the_printed_unit_text(raw, unit) -> None:
    assert units.trailing_unit(raw) == unit
