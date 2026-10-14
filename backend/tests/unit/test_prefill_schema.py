"""The committed JSON Schema of the pre-fill pack (docs/schemas/declaration-prefill.schema.json) must equal the models'.

Consumers of the pack read that file, so a model change that is not reflected there (and in SCHEMA_VERSION) is caught here.
Regenerate after a deliberate change:  UPDATE_PREFILL_SCHEMA=1 pytest tests/unit/test_prefill_schema.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.domain.prefill import SCHEMA_ID, SCHEMA_VERSION, PrefillPack

SCHEMA_FILE = Path(__file__).resolve().parents[3] / "docs" / "schemas" / "declaration-prefill.schema.json"


def current() -> dict:
    schema = PrefillPack.model_json_schema()
    schema["$id"] = f"{SCHEMA_ID}/{SCHEMA_VERSION}"
    schema["description"] = (
        "CargoClear declaration pre-fill pack. Not a government format; see docs/PREFILL_PACK.md. "
        f"Schema version {SCHEMA_VERSION}."
    )
    return schema


def test_the_committed_schema_is_the_models_schema() -> None:
    if os.environ.get("UPDATE_PREFILL_SCHEMA") == "1":
        SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_FILE.write_text(json.dumps(current(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert SCHEMA_FILE.exists(), "docs/schemas/declaration-prefill.schema.json is missing (UPDATE_PREFILL_SCHEMA=1 creates it)"
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == json.loads(json.dumps(current())), (
        "the pre-fill models changed: regenerate the schema (UPDATE_PREFILL_SCHEMA=1) and bump SCHEMA_VERSION if a consumer could notice"
    )


def test_every_field_is_documented() -> None:
    """A consumer reads descriptions, not code: every property of the pack's own models says what it is."""
    schema = current()
    undocumented = [
        f"{name}.{prop}"
        for name, definition in {"PrefillPack": schema, **schema.get("$defs", {})}.items()
        if name.startswith("Prefill")
        for prop, body in definition.get("properties", {}).items()
        if prop not in {"schema_id", "schema_version"} and not (body.get("description") or "$ref" in body or any("$ref" in b for b in body.get("anyOf", [])) or "items" in body)
    ]
    assert undocumented == [], f"fields with no description: {undocumented}"
