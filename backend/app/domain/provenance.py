"""Where an assessment's data actually came from.

``data_source`` is derived from what ran, never from APP_MODE:

  ctx["extraction_source"]  "fixture" | "live"      set by the extraction agent
  ctx["grounding_source"]   "seed" | "bigquery" | None   set by the grounding agent (None: no tariff lookup ran)

An iteration is "fixture" if extraction used fixtures OR the tariff came from the local seed, else "live".
"""

from __future__ import annotations

from typing import Any, Literal

DataSource = Literal["live", "fixture"]


def derive_data_source(ctx: dict[str, Any]) -> DataSource | None:
    """Return the iteration's data_source, or None when no stage reported what it used."""
    extraction_source = ctx.get("extraction_source")
    if extraction_source is None:
        return None
    if extraction_source == "fixture" or ctx.get("grounding_source") == "seed":
        return "fixture"
    return "live"


# ---------------------------------------------------------------------------
# Prototype wording for the curated demo rule set. These strings are the ONLY place the app describes where a
# requirement comes from: it is a curated demo rule set, not an official AHTN requirement, and must never be
# presented as one.
# ---------------------------------------------------------------------------

RULE_SET_DEMO = "demo-curated"
REGULATION_REF_DEMO = "Demo rule set (prototype); not an official AHTN requirement"
CORE_DOC_REASON = (
    "Baseline trade document (prototype rule: commercial invoice, bill of lading and packing list "
    "are always expected)"
)
CORE_DOC_REF = "Prototype baseline rule"
