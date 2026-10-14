"""The frontend's copy of the correction address tables (frontend/lib/corrections.ts) must equal the backend's.

The backend is the authority and refuses anything outside its tables, so a drifted frontend would offer an Edit button the
API then rejects (or hide one it accepts). Nothing generates the TypeScript, so this test is what keeps the two together.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.domain import corrections as c

TS = (Path(__file__).resolve().parents[3] / "frontend" / "lib" / "corrections.ts").read_text(encoding="utf-8")


def ts_list(name: str) -> list[str]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", TS, re.DOTALL)
    assert match, f"{name} not found in frontend/lib/corrections.ts"
    return re.findall(r'"([a-z_]+)"', match.group(1))


def test_the_field_tables_are_the_same_in_both_languages() -> None:
    assert ts_list("HEADER_FIELDS") == list(c.HEADER_FIELDS)
    assert ts_list("LINE_FIELDS") == list(c.LINE_FIELDS)
    assert ts_list("ROW_LISTS") == list(c.ROW_LISTS)


def test_the_weight_fields_the_frontend_gives_a_unit_box_are_the_ones_the_backend_treats_as_weights() -> None:
    match = re.search(r"const WEIGHT_FIELDS = new Set\(\[(.*?)\]\)", TS, re.DOTALL)
    assert match
    frontend = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    backend = {f for f, kind in {**c.HEADER_FIELDS, **c.LINE_FIELDS}.items() if kind == "weight"}
    assert frontend == backend


def test_the_frontend_types_name_the_fields_the_backend_models_have() -> None:
    types = (Path(__file__).resolve().parents[3] / "frontend" / "lib" / "types.ts").read_text(encoding="utf-8")
    from app.domain.schemas import AppliedCorrection, CorrectionRecord, CorrectionRequest, CorrectionsResponse

    for model, interface in (
        (AppliedCorrection, "AppliedCorrection"),
        (CorrectionRecord, "CorrectionRecord"),
        (CorrectionRequest, "CorrectionRequest"),
        (CorrectionsResponse, "CorrectionsResponse"),
    ):
        block = re.search(rf"export interface {interface} \{{(.*?)\n\}}", types, re.DOTALL)
        assert block, f"{interface} missing from frontend/lib/types.ts"
        declared = set(re.findall(r"^\s{2}([a-z_]+)\??:", block.group(1), re.MULTILINE))
        assert declared == set(model.model_fields), f"{interface}: {declared ^ set(model.model_fields)}"
