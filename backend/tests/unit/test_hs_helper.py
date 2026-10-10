"""app/domain/hs.py: the single source of truth for reading and comparing HS codes."""

from __future__ import annotations

import pytest

from app.domain import hs
from app.domain.hs import HS_FULL_DIGITS, HS_MIN_DIGITS, hs_digits, hs_match_level, hs_text


def test_constants() -> None:
    assert (HS_FULL_DIGITS, HS_MIN_DIGITS) == (8, 6)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("73041900", "73041900"),
        (" 7304.19.00 ", "7304.19.00"),
        (73041900, "73041900"),
        (73041900.0, "73041900"),  # a whole float loses its '.0'
        (14.5, "14.5"),
        (None, ""),
        ("", ""),
    ],
)
def test_hs_text(value, text) -> None:
    assert hs_text(value) == text


@pytest.mark.parametrize(
    ("value", "digits"),
    [
        ("73041900", "73041900"),
        ("7304.19.00", "73041900"),
        ("7304 19 00", "73041900"),
        ("7304-19-00", "73041900"),
        (73041900, "73041900"),
        (73041900.0, "73041900"),
        ("7304190000", "7304190000"),
        ("N/A", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_hs_digits(value, digits) -> None:
    assert hs_digits(value) == digits


@pytest.mark.parametrize(
    ("declared", "candidate", "level"),
    [
        # exact at 8 digits, whatever the formatting or type of the declaration
        ("73041900", "73041900", "exact8"),
        ("7304.19.00", "73041900", "exact8"),
        ("7304 19 00", "73041900", "exact8"),
        (73041900, "73041900", "exact8"),
        (73041900.0, "73041900", "exact8"),
        # 10-digit national lines compare on their first 8 digits, on either side
        ("7304190000", "73041900", "exact8"),
        ("7304.19.00.11", "73041900", "exact8"),
        ("73041900", "7304190099", "exact8"),
        # only 6 (or 7) digits declared: the 8-digit code is unconfirmed
        ("730419", "73041900", "subheading6"),
        ("7304.19", "73041900", "subheading6"),
        ("7304190", "73041900", "subheading6"),
        ("730419", "730419", "subheading6"),
        ("73041900", "730419", "subheading6"),  # the row itself only goes to 6 digits
        # same heading, different subheading
        ("73041100", "73041900", "heading4"),
        ("7304.31.00", "73041900", "heading4"),
        # unrelated
        ("73061900", "73041900", "none"),
        ("10019910", "73041900", "none"),
        # nothing usable declared
        (None, "73041900", "not_declared"),
        ("", "73041900", "not_declared"),
        ("N/A", "73041900", "not_declared"),
        ("garbage", "73041900", "not_declared"),
        ("7304", "73041900", "not_declared"),
        ("73041", "73041900", "not_declared"),
    ],
)
def test_hs_match_level(declared, candidate, level) -> None:
    assert hs_match_level(declared, candidate) == level


def test_candidate_formatting_does_not_matter_either() -> None:
    assert hs_match_level("73041900", "7304.19.00") == "exact8"


def test_helper_module_is_pure() -> None:
    """No settings or services: it is only string logic."""
    assert not hasattr(hs, "settings")
