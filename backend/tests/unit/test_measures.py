"""Printed lab values, parameter names, heat ids and country names: read as printed, assumptions reported."""

from __future__ import annotations

import pytest

from app.domain.countries import country_code
from app.domain.measures import canonical_parameter, normalize_heat, parse_measure, to_mpa


@pytest.mark.parametrize(
    ("raw", "unit", "value"),
    [("0.18", "%", 0.18), (0.18, "%", 0.18), (".18", "%", 0.18), ("0,18", "%", 0.18), ("1.200", "%", 1.2),
     ("5", "ppm", 0.0005), ("8", "mg/kg", 0.0008), (" 0.25 ", "wt%", 0.25), ("0.0008", "%", 0.0008)],
)
def test_a_chemistry_value_is_read_as_weight_percent(raw, unit, value) -> None:
    measure = parse_measure(raw, unit)

    assert measure.value == pytest.approx(value)
    assert measure.bound == "exact" and measure.assumptions == [] and measure.error is None


def test_a_missing_unit_is_read_as_percent_and_the_assumption_is_recorded() -> None:
    measure = parse_measure("0.18", None)

    assert measure.value == 0.18 and measure.assumptions == ["no unit printed; read as weight %"]
    assert parse_measure("0.18", "  ").assumptions == ["no unit printed; read as weight %"]


@pytest.mark.parametrize("raw", ["<0.005", "≤0.005", "< 0.005"])
def test_a_less_than_sign_is_an_upper_bound(raw) -> None:
    measure = parse_measure(raw, "%")

    assert measure.value == 0.005 and measure.bound == "upper"


def test_a_greater_than_sign_is_a_lower_bound() -> None:
    assert parse_measure(">0.5", "%").bound == "lower"


@pytest.mark.parametrize("raw", ["ND", "nd", "N.D.", "nil", "-", "trace"])
def test_not_detected_has_no_value_and_is_not_an_error(raw) -> None:
    measure = parse_measure(raw, "%")

    assert measure.value is None and measure.not_detected is True and measure.error is None


@pytest.mark.parametrize(("raw", "unit"), [("abc", "%"), ("1.2.3", "%"), ("0.1", "grams"), (None, "%"), ("", "%"), (True, "%")])
def test_what_cannot_be_read_is_an_error_not_a_guess(raw, unit) -> None:
    measure = parse_measure(raw, unit)

    assert measure.value is None and measure.error


def test_strengths_are_converted_to_mpa() -> None:
    assert to_mpa(310, "MPa").value == 310
    assert to_mpa(310, "N/mm2").value == 310
    assert to_mpa(42, "ksi").value == pytest.approx(289.58, abs=0.01)
    assert to_mpa(45000, "psi").value == pytest.approx(310.26, abs=0.01)
    assert to_mpa(310, None).assumptions == ["no unit printed; read as MPa"]
    assert to_mpa(310, "kgf").error


@pytest.mark.parametrize(
    ("printed", "canonical"),
    [("C", "C"), ("Carbon", "C"), ("MN", "Mn"), ("Manganese", "Mn"), ("Sulphur", "S"), ("Sulfur", "S"), ("Cr", "Cr"),
     ("Columbium", "Nb"), ("Cb", "Nb"), ("Aluminum", "Al"), ("B", "B"), ("YS", "YS"), ("Yield Strength", "YS"),
     ("Rp0.2", "YS"), ("UTS", "UTS"), ("Tensile", "UTS"), ("Elongation", "EL")],
)
def test_column_headings_map_to_canonical_parameters(printed, canonical) -> None:
    assert canonical_parameter(printed) == canonical


def test_an_unknown_heading_is_not_guessed() -> None:
    assert canonical_parameter("Hardness HRB") is None and canonical_parameter(None) is None


def test_heat_numbers_compare_without_punctuation_or_case() -> None:
    assert normalize_heat("H-24-0881") == normalize_heat("h 24 0881") == normalize_heat("H240881") == "H240881"
    assert normalize_heat(None) == "" and normalize_heat("  ") == ""


@pytest.mark.parametrize(
    ("printed", "code"),
    [("China", "CN"), ("CHINA", "CN"), ("People's Republic of China", "CN"), ("P.R. CHINA", "CN"), ("PRC", "CN"),
     ("Made in India", "IN"), ("Viet Nam", "VN"), ("Singapore", "SG"), ("IN", "IN"), ("Atlantis", None), (None, None), ("", None)],
)
def test_country_names_become_iso_codes(printed, code) -> None:
    assert country_code(printed) == code
