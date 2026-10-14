"""Country names as printed on trade documents -> ISO 3166-1 alpha-2, for comparing and for looking up trade remedies.

Pure, no I/O. Deliberately small: the countries the prototype's rule sets name, plus common spellings. A name that is
not recognised returns None: the engines then say "origin not recognised" instead of guessing.
"""

from __future__ import annotations

import re

_COUNTRIES: dict[str, tuple[str, ...]] = {
    "CN": ("CHINA", "PRC", "PEOPLES REPUBLIC OF CHINA", "P R CHINA", "PR CHINA", "CHINA MAINLAND", "MADE IN CHINA", "CN", "CHN"),
    "IN": ("INDIA", "REPUBLIC OF INDIA", "MADE IN INDIA", "IN", "IND"),
    "SG": ("SINGAPORE", "REPUBLIC OF SINGAPORE", "SG", "SGP"),
    "VN": ("VIETNAM", "VIET NAM", "SOCIALIST REPUBLIC OF VIETNAM", "VN", "VNM"),
    "KR": ("SOUTH KOREA", "KOREA", "REPUBLIC OF KOREA", "KOREA REPUBLIC OF", "KR", "KOR"),
    "JP": ("JAPAN", "JP", "JPN"),
    "ID": ("INDONESIA", "ID", "IDN"),
    "TH": ("THAILAND", "TH", "THA"),
    "MY": ("MALAYSIA", "MY", "MYS"),
    "TW": ("TAIWAN", "TW", "TWN"),
    "AE": ("UNITED ARAB EMIRATES", "UAE", "AE", "ARE"),
}

_BY_NAME = {name: code for code, names in _COUNTRIES.items() for name in names}


def country_code(raw: object) -> str | None:
    """ISO alpha-2 for a printed country name ("People's Republic of China" -> "CN"), or None if not recognised."""
    if raw is None:
        return None
    key = re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", "", str(raw).upper().replace("'", ""))).strip()
    return _BY_NAME.get(key)
