"""Tariff grounding policy (agents/grounding.py): which row governs a line, and what each match level allows.

The same declared code must be read the same way here and in H-002: "7304.19.00" == "73041900".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.agents import extraction, grounding
from app.agents.grounding import run_grounding_agent
from app.agents.tools import bq_tariff
from app.agents.tools.bq_tariff import AMBIGUITY_THRESHOLD
from app.domain.schemas import BBox, ExtractedDocument, FieldRef, GroundingFinding, LineItem
from app.services import calculation, confidence
from app.services.orchestrator import resolve_final_status

REPO = Path(__file__).resolve().parents[3]
DESCRIPTION = "Seamless carbon steel pipes API 5L Grade B"

RULE_SET = "demo-curated"
REG_REF = "Demo rule set (prototype); not an official AHTN requirement"
CORE_REASON = (
    "Baseline trade document (prototype rule: commercial invoice, bill of lading and packing list "
    "are always expected)"
)
CORE_REF = "Prototype baseline rule"


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def ref(value, conf=0.98) -> FieldRef:
    return FieldRef(value=value, confidence=conf, bbox=BBox(page=1, ymin=10, xmin=20, ymax=30, xmax=40))


def line(hs, desc: str | None = DESCRIPTION) -> LineItem:
    return LineItem(
        description=ref(desc), quantity=ref("1"), net_weight_kg=ref(1.0), gross_weight_kg=ref(1.0),
        hs_code_declared=ref(hs),
    )


def doc(doc_type: str, *lines: LineItem, doc_id: str | None = None) -> ExtractedDocument:
    ids = {"COMMERCIAL_INVOICE": "inv-001", "PACKING_LIST": "pl-001", "BILL_OF_LADING": "bol-001",
           "MILL_TEST_CERTIFICATE": "mtc-001"}
    return ExtractedDocument(document_id=doc_id or ids[doc_type], doc_type=doc_type, doc_type_confidence=0.99,
                             line_items=list(lines))


def bundle(hs, desc: str | None = DESCRIPTION, *, with_mtc=False) -> list[ExtractedDocument]:
    docs = [doc("COMMERCIAL_INVOICE", line(hs, desc)), doc("PACKING_LIST", line(hs, desc)), doc("BILL_OF_LADING")]
    if with_mtc:
        docs.append(doc("MILL_TEST_CERTIFICATE"))
    return docs


def cand(hs, distance=0.08, docs=("MILL_TEST_CERTIFICATE",), description=None, **extra) -> dict[str, Any]:
    return {
        "hs_code": hs,
        "description": description or f"Tariff row {hs}: line pipe of a kind used for oil or gas pipelines, seamless",
        "required_documents": list(docs),
        "distance": distance,
        "rule_set": RULE_SET,
        "regulation_ref": REG_REF,
        **extra,
    }


class FakeLookup:
    """Replaces lookup_tariff_with_source and records the query text it was asked to embed."""

    def __init__(self, hits: list[dict[str, Any]], source: str = "seed") -> None:
        self.hits, self.source, self.queries = hits, source, []

    def __call__(self, description: str, destination_country: str = "SG"):
        self.queries.append(description)
        return list(self.hits), self.source


async def ground(docs, monkeypatch=None, hits=None) -> dict[str, Any]:
    """Run the grounding stage; with `hits` the tariff lookup is faked, otherwise the real offline seed is used."""
    fake = None
    if hits is not None:
        assert monkeypatch is not None
        fake = FakeLookup(hits)
        monkeypatch.setattr(grounding, "lookup_tariff_with_source", fake)
    ctx = await calculation.run({"extracted": docs})
    ctx = await run_grounding_agent(ctx)
    ctx["_fake"] = fake
    return ctx


def finding_for(ctx, document_id: str) -> dict[str, Any]:
    return next(f for f in ctx["grounding"] if f["document_id"] == document_id)


def mtc_items(ctx) -> list[dict[str, Any]]:
    return [m for m in ctx["missing_evidence"] if m["id"] == "ME-MILL_TEST_CERTIFICATE"]


# ---------------------------------------------------------------------------
# D1: the same declared code reads the same way in grounding and in H-002
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", ["73041900", "7304.19.00", "7304 19 00", 73041900, 73041900.0])
async def test_every_spelling_of_the_declared_code_is_exact8_and_agrees_with_h002(declared) -> None:
    ctx = await ground(bundle(declared))

    for document_id in ("inv-001", "pl-001"):
        f = finding_for(ctx, document_id)
        assert f["hs_mismatch"] is False, f"declared {declared!r}: wrongly flagged as a mismatch"
        assert f["ambiguous"] is False
        assert f["hs_match_level"] == "exact8"
        assert f["governing_hs"] == "73041900"

    h002 = calculation.check_hs_consistency(bundle(declared)[0], bundle("73041900")[1])
    assert h002.severity == "PASS"
    assert ctx["grounding_ambiguous"] is False


@pytest.mark.asyncio
async def test_six_digit_declaration_is_subheading6_ambiguous_and_h002_warns() -> None:
    ctx = await ground(bundle("730419"))
    f = finding_for(ctx, "inv-001")

    assert f["hs_mismatch"] is False
    assert f["ambiguous"] is True
    assert f["hs_match_level"] == "subheading6"
    assert f["required_documents"] == []
    assert calculation.check_hs_consistency(bundle("730419")[0], bundle("73041900")[1]).severity == "WARN"


@pytest.mark.asyncio
async def test_a_code_in_the_same_heading_but_another_subheading_is_a_mismatch_and_h002_is_material() -> None:
    ctx = await ground(bundle("73041100"))
    f = finding_for(ctx, "inv-001")

    assert f["hs_match_level"] in ("heading4", "none")
    assert f["hs_mismatch"] is True
    assert f["ambiguous"] is True
    assert f["required_documents"] == []
    assert calculation.check_hs_consistency(bundle("73041100")[0], bundle("73041900")[1]).severity == "MATERIAL"


# ---------------------------------------------------------------------------
# C1: the query is the description only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", ["73041900", "7304.19.00", 73041900])
async def test_the_declared_code_is_never_part_of_the_query(monkeypatch, declared) -> None:
    ctx = await ground(bundle(declared), monkeypatch, hits=[cand("73041900")])
    fake: FakeLookup = ctx["_fake"]

    assert fake.queries, "no lookup was made"
    for query in fake.queries:
        assert query == DESCRIPTION
        assert "73041900" not in query
        assert "7304" not in query


def test_the_seed_search_ignores_digits_in_the_query() -> None:
    """The old shortcut let a claimed code pull its own row to the top (distance 0.08)."""
    plain, _ = bq_tariff.lookup_tariff_with_source("Coffee beans", "SG")
    with_code, _ = bq_tariff.lookup_tariff_with_source("Coffee beans 73041900", "SG")
    assert {h["hs_code"]: h["distance"] for h in plain} == {h["hs_code"]: h["distance"] for h in with_code}
    pipes = next(h for h in with_code if h["hs_code"] == "73041900")
    assert pipes["distance"] > grounding.AMBIGUITY_THRESHOLD


def test_case_c_description_still_retrieves_73041900_within_the_threshold() -> None:
    hits, source = bq_tariff.lookup_tariff_with_source(DESCRIPTION, "SG")
    assert source == "seed"
    top = next(h for h in hits if h["hs_code"] == "73041900")
    assert top["distance"] <= grounding.AMBIGUITY_THRESHOLD
    assert hits[0]["distance"] == top["distance"]


@pytest.mark.asyncio
async def test_a_line_without_a_description_makes_no_lookup(monkeypatch) -> None:
    docs = [doc("COMMERCIAL_INVOICE", line("73041900", desc=None)), doc("PACKING_LIST"), doc("BILL_OF_LADING")]
    ctx = await ground(docs, monkeypatch, hits=[cand("73041900")])

    assert ctx["_fake"].queries == []
    f = finding_for(ctx, "inv-001")
    assert f["hs_match_level"] == "not_declared"
    assert f["ambiguous"] is True
    assert f["hs_mismatch"] is False
    assert f["required_documents"] == []
    assert mtc_items(ctx) == []
    assert ctx["grounding_source"] is None  # nothing was looked up


@pytest.mark.asyncio
async def test_blank_description_counts_as_missing(monkeypatch) -> None:
    ctx = await ground([doc("COMMERCIAL_INVOICE", line("73041900", desc="   ")), doc("PACKING_LIST"),
                        doc("BILL_OF_LADING")], monkeypatch, hits=[cand("73041900")])
    assert ctx["_fake"].queries == []
    assert finding_for(ctx, "inv-001")["hs_match_level"] == "not_declared"


# ---------------------------------------------------------------------------
# C2 / D2: the governing row is the best match, not rank 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_required_documents_come_from_the_row_of_the_declared_code_even_at_rank_2(monkeypatch) -> None:
    rank1 = cand("73043100", 0.05, docs=("PHYTOSANITARY",), regulation_ref="REF-RANK-1", rule_set="rs-1")
    rank2 = cand("73041900", 0.12, docs=("MILL_TEST_CERTIFICATE",), regulation_ref="REF-RANK-2", rule_set="rs-2")
    ctx = await ground(bundle("73041900"), monkeypatch, hits=[rank1, rank2])

    f = finding_for(ctx, "inv-001")
    assert f["required_documents"] == ["MILL_TEST_CERTIFICATE"]  # not rank 1's PHYTOSANITARY
    assert not [m for m in ctx["missing_evidence"] if m["id"] == "ME-PHYTOSANITARY"]
    assert ctx["required_documents"] == ["MILL_TEST_CERTIFICATE"]
    [item] = mtc_items(ctx)
    assert item["regulation_ref"] == "REF-RANK-2"
    assert item["rule_set"] == "rs-2"
    assert item["hs_code"] == "73041900"

    assert f["regulation_ref"] == "REF-RANK-2"
    assert f["rule_set"] == "rs-2"
    assert f["hs_match_level"] == "exact8"
    assert f["governing_hs"] == "73041900"
    assert f["top_candidate_hs"] == "73041900"  # the row the line was judged against
    assert f["distance"] == 0.12


@pytest.mark.asyncio
async def test_ambiguity_uses_the_governing_rows_distance_not_rank_1s(monkeypatch) -> None:
    """The declared row is far from the description AND a different row is close: the claim is contradicted."""
    rank1 = cand("73043100", 0.05)
    rank2 = cand("73041900", 0.60)
    ctx = await ground(bundle("73041900"), monkeypatch, hits=[rank1, rank2])
    f = finding_for(ctx, "inv-001")

    assert f["hs_match_level"] == "exact8"  # the code does exist in the tariff
    assert f["ambiguous"] is True  # the governing row is too far from the description
    assert f["hs_mismatch"] is True  # ... and the description fits another row (rank 1) much better
    assert f["required_documents"] == []  # so nothing is derived from the declared row
    assert f["better_match_hs"] == "73043100"


@pytest.mark.asyncio
async def test_a_weak_governing_row_with_no_better_row_still_governs(monkeypatch) -> None:
    """Weak (0.60) but every other row is weak too: nothing contradicts the claim, so it keeps its requirements."""
    rank1 = cand("73043100", 0.40)
    rank2 = cand("73041900", 0.60)
    ctx = await ground(bundle("73041900"), monkeypatch, hits=[rank1, rank2])
    f = finding_for(ctx, "inv-001")

    assert f["hs_match_level"] == "exact8"
    assert f["ambiguous"] is True
    assert f["hs_mismatch"] is False
    assert f["required_documents"] == ["MILL_TEST_CERTIFICATE"]
    assert f["better_match_hs"] is None


@pytest.mark.asyncio
async def test_best_level_beats_a_closer_distance(monkeypatch) -> None:
    heading_only = cand("73041100", 0.01, docs=("PHYTOSANITARY",))
    subheading = cand("73041900", 0.30, docs=("MILL_TEST_CERTIFICATE",))
    ctx = await ground(bundle("730419"), monkeypatch, hits=[heading_only, subheading])
    f = finding_for(ctx, "inv-001")

    assert f["hs_match_level"] == "subheading6"
    assert f["governing_hs"] == "73041900"


@pytest.mark.asyncio
async def test_equal_levels_are_broken_by_the_lowest_distance(monkeypatch) -> None:
    far = cand("73041900", 0.30, docs=("PHYTOSANITARY",), regulation_ref="FAR")
    near = cand("7304190000", 0.10, docs=("MILL_TEST_CERTIFICATE",), regulation_ref="NEAR")
    ctx = await ground(bundle("73041900"), monkeypatch, hits=[far, near])
    f = finding_for(ctx, "inv-001")

    assert f["hs_match_level"] == "exact8"
    assert f["regulation_ref"] == "NEAR"
    assert f["required_documents"] == ["MILL_TEST_CERTIFICATE"]


# ---------------------------------------------------------------------------
# C3: policy table, one test per row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("declared", "level", "mismatch", "ambiguous"),
    [
        ("73041900", "exact8", False, False),
        ("7304.19.00", "exact8", False, False),
        ("730419", "subheading6", False, True),
        ("7304190", "subheading6", False, True),
        ("73041100", "heading4", True, True),
        ("10019910", "none", True, True),
        ("N/A", "not_declared", False, True),
        ("7304", "not_declared", False, True),
        (None, "not_declared", False, True),
    ],
)
async def test_policy_table(monkeypatch, declared, level, mismatch, ambiguous) -> None:
    ctx = await ground(bundle(declared), monkeypatch, hits=[cand("73041900", 0.08)])
    f = finding_for(ctx, "inv-001")

    if level == "exact8":
        assert f["required_documents"] == ["MILL_TEST_CERTIFICATE"]
        assert len(mtc_items(ctx)) == 1
    else:
        assert f["required_documents"] == [], "requirements must never be derived from an unconfirmed code"
        assert mtc_items(ctx) == []
        assert ctx["required_documents"] == []
    assert (f["hs_mismatch"], f["ambiguous"]) == (mismatch, ambiguous)
    assert ctx["grounding_ambiguous"] is ambiguous
    assert f["hs_match_level"] == level


@pytest.mark.asyncio
async def test_mismatch_and_subheading_cases_derive_no_missing_evidence_items_at_all(monkeypatch) -> None:
    for declared in ("73041100", "730419", "10019910"):
        ctx = await ground(bundle(declared, with_mtc=False), monkeypatch, hits=[cand("73041900")])
        assert [m["id"] for m in ctx["missing_evidence"]] == [], declared


@pytest.mark.asyncio
async def test_no_candidates_at_all_is_unverifiable_not_a_mismatch(monkeypatch) -> None:
    ctx = await ground(bundle("73041900"), monkeypatch, hits=[])
    f = finding_for(ctx, "inv-001")
    assert f["ambiguous"] is True
    assert f["hs_mismatch"] is False
    assert f["hs_match_level"] == "none"
    assert f["governing_hs"] is None
    assert f["required_documents"] == []


# ---------------------------------------------------------------------------
# C4: provenance wording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_c_missing_certificate_carries_the_prototype_wording() -> None:
    ctx = await ground(bundle("73041900"))

    [item] = mtc_items(ctx)
    assert item["rule_set"] == RULE_SET
    assert item["regulation_ref"] == REG_REF
    assert item["hs_code"] == "73041900"
    assert item["document_label"] == "Mill Test Certificate"
    assert item["reason"] == (
        "Required by the demo-curated rule set for HS 73041900 "
        "(Line pipe of a kind used for oil or gas pipelines, seamless,); no Mill Test Certificate is in the bundle."
    )
    assert [m["id"] for m in ctx["missing_evidence"]] == ["ME-MILL_TEST_CERTIFICATE"]

    f = finding_for(ctx, "inv-001")
    assert f["rule_set"] == RULE_SET
    assert f["regulation_ref"] == REG_REF


@pytest.mark.asyncio
async def test_reason_uses_the_governing_rows_description_cut_at_60_characters(monkeypatch) -> None:
    long_row = cand("73041900", 0.08, description="D" * 100)
    ctx = await ground(bundle("73041900"), monkeypatch, hits=[long_row])
    [item] = mtc_items(ctx)
    assert item["reason"] == (
        f"Required by the demo-curated rule set for HS 73041900 ({'D' * 60}); no Mill Test Certificate is in the bundle."
    )


@pytest.mark.asyncio
async def test_rule_set_and_reference_come_from_the_row_not_a_constant(monkeypatch) -> None:
    row = cand("73041900", 0.08, rule_set="custom-set", regulation_ref="Custom ref")
    ctx = await ground(bundle("73041900"), monkeypatch, hits=[row])
    [item] = mtc_items(ctx)
    assert (item["rule_set"], item["regulation_ref"]) == ("custom-set", "Custom ref")
    assert "Required by the custom-set rule set" in item["reason"]


@pytest.mark.asyncio
async def test_missing_core_documents_use_the_prototype_wording() -> None:
    ctx = await ground([doc("COMMERCIAL_INVOICE", line("73041900"))])

    core = {m["id"]: m for m in ctx["missing_evidence"] if m["id"].startswith("ME-CORE-")}
    assert set(core) == {"ME-CORE-BILL_OF_LADING", "ME-CORE-PACKING_LIST"}
    for item in core.values():
        assert item["reason"] == CORE_REASON
        assert item["regulation_ref"] == CORE_REF
        assert item["rule_set"] == RULE_SET
        assert item["hs_code"] == "GENERAL"


def test_seed_candidates_carry_rule_set_and_regulation_ref() -> None:
    hits, _ = bq_tariff.lookup_tariff_with_source(DESCRIPTION, "SG")
    assert hits
    for hit in hits:
        assert hit["rule_set"] == RULE_SET
        assert hit["regulation_ref"] == REG_REF


def test_bigquery_rows_without_the_columns_get_the_prototype_wording(monkeypatch) -> None:
    from types import SimpleNamespace

    rows = [
        {"hs_code": "73041900", "description": "d", "required_documents": [], "distance": 0.05,
         "rule_set": None, "regulation_ref": None},
        {"hs_code": "73043100", "description": "d", "required_documents": [], "distance": 0.06,
         "rule_set": "own-set", "regulation_ref": "Own ref"},
        {"hs_code": "10019910", "description": "d", "required_documents": [], "distance": 0.07},  # older table
    ]
    job = SimpleNamespace(result=lambda timeout=None: rows)
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: SimpleNamespace(query=lambda *_a, **_k: job))

    hits, source = bq_tariff.lookup_tariff_with_source("pipes", "SG")

    assert source == "bigquery"
    assert [(h["rule_set"], h["regulation_ref"]) for h in hits] == [
        (RULE_SET, REG_REF), ("own-set", "Own ref"), (RULE_SET, REG_REF),
    ]


# ---------------------------------------------------------------------------
# C5: provenance data in infra
# ---------------------------------------------------------------------------


def test_vector_sql_selects_the_provenance_columns_and_keeps_its_filter() -> None:
    sql = bq_tariff.VECTOR_SQL
    assert "base.rule_set" in sql
    assert "base.regulation_ref" in sql
    # a PRE-filter: inside the base-table subquery, so top_k is taken from the destination's rows only
    assert "(SELECT * FROM `{tariff_table}` WHERE destination_country = @dest)" in sql
    assert "base.destination_country" not in sql


def test_seed_rows_all_carry_the_prototype_provenance() -> None:
    rows = json.loads((REPO / "infra" / "bigquery" / "seed" / "sample_tariff.json").read_text(encoding="utf-8"))
    assert len(rows) == 7  # four for Singapore (Case C and others) and three for India (Case D)
    for row in rows:
        assert row["rule_set"] == RULE_SET
        assert row["regulation_ref"] == REG_REF


def test_table_schema_has_two_nullable_string_provenance_columns() -> None:
    schema = json.loads((REPO / "infra" / "bigquery" / "schema.json").read_text(encoding="utf-8"))
    by_name = {column["name"]: column for column in schema}
    for name in ("rule_set", "regulation_ref"):
        assert by_name[name]["type"] == "STRING"
        assert by_name[name]["mode"] == "NULLABLE"
    assert {"hs_code", "description", "destination_country", "required_documents", "description_embedding"} <= set(by_name)


# ---------------------------------------------------------------------------
# D4: no claim of an official source
# ---------------------------------------------------------------------------

FORBIDDEN = ("official tariff regulation", "AHTN 2022", "Customs Core Trade Policy")


def test_no_forbidden_provenance_wording_in_app_or_seed_data() -> None:
    files = [*(REPO / "backend" / "app").rglob("*.py"), *(REPO / "infra" / "bigquery" / "seed").rglob("*")]
    offenders = [
        f"{path.relative_to(REPO)}: {phrase!r}"
        for path in files
        if path.is_file()
        for phrase in FORBIDDEN
        if phrase in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# ---------------------------------------------------------------------------
# G-001: grounding outcomes are visible as a check
# ---------------------------------------------------------------------------


def g001(ctx) -> dict[str, Any]:
    found = [c for c in ctx["checks"] if c["check_id"] == "G-001"]
    assert len(found) == 1, f"expected exactly one G-001, got {len(found)}"
    return found[0]


@pytest.mark.asyncio
async def test_g001_passes_for_case_c_with_bbox_evidence_on_the_hs_fields() -> None:
    ctx = await ground(bundle("73041900"))
    check = g001(ctx)

    assert check["severity"] == "PASS"
    assert check["assumptions"] == []
    assert "73041900" in check["message"]
    assert "0.08" in check["message"]
    docs_with_boxes = {e["doc"] for e in check["evidence"] if e.get("bbox") and e.get("page")}
    assert docs_with_boxes == {"inv-001", "pl-001"}
    for entry in check["evidence"]:
        assert entry["field"] == "hs_code_declared"
        assert entry["line_item"] == 0
        assert entry["raw_value"] == "73041900"


@pytest.mark.asyncio
async def test_case_c_check_ids_are_unique_and_include_every_rule() -> None:
    docs = [
        doc("COMMERCIAL_INVOICE", line("73041900")),
        ExtractedDocument(
            document_id="pl-001", doc_type="PACKING_LIST", doc_type_confidence=0.9, line_items=[line("73041900")],
            total_net_weight_kg=ref(14000.0), tare_weight_kg=ref(280.0), total_gross_weight_kg=ref(14280.0),
        ),
        ExtractedDocument(document_id="bol-001", doc_type="BILL_OF_LADING", doc_type_confidence=0.9,
                          total_gross_weight_kg=ref(14280.0)),
    ]
    for d in docs:
        for name in ("total_net_weight_kg", "total_gross_weight_kg", "tare_weight_kg"):
            weight = getattr(d, name, None)
            if weight is not None:
                weight.unit = "KGS"
    ctx = await ground(docs)

    ids = [c["check_id"] for c in ctx["checks"]]
    assert len(ids) == len(set(ids)), ids
    assert {c["check_id"]: c["severity"] for c in ctx["checks"]} == {
        "W-001": "PASS", "W-002": "PASS", "H-002": "PASS", "G-001": "PASS",
    }


@pytest.mark.asyncio
async def test_running_grounding_twice_still_yields_one_g001() -> None:
    ctx = await ground(bundle("73041900"))
    ctx = await run_grounding_agent(ctx)
    g001(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("declared", "hits", "fragments"),
    [
        ("730419", [cand("73041900", 0.08)], ["730419", "6 digits", "73041900"]),
        ("73041100", [cand("73041900", 0.08)], ["73041100", "heading", "73041900"]),
        ("10019910", [cand("73041900", 0.08)], ["10019910", "no retrieved tariff candidate", "73041900"]),
        ("N/A", [cand("73041900", 0.08)], ["N/A", "no usable", "73041900"]),
        ("73041900", [cand("73041900", 0.60)], ["73041900", "weak", "0.60"]),
        ("73041900", [], ["73041900", "no tariff candidate"]),
    ],
)
async def test_g001_warns_with_a_readable_message_for_every_unconfirmed_level(monkeypatch, declared, hits, fragments) -> None:
    ctx = await ground(bundle(declared), monkeypatch, hits=hits)
    check = g001(ctx)

    assert check["severity"] == "WARN"
    for fragment in fragments:
        assert fragment in check["message"], f"{fragment!r} missing from: {check['message']}"
    assert "Other problem lines: 1" in check["message"]  # the packing list line has the same problem


@pytest.mark.asyncio
async def test_g001_names_the_closest_candidate_with_description_and_distance(monkeypatch) -> None:
    ctx = await ground(bundle("73041100"), monkeypatch,
                       hits=[cand("73041900", 0.21, description="Line pipe of a kind used for oil or gas pipelines, seamless, of iron or steel")])
    message = g001(ctx)["message"]

    assert "73041900" in message
    assert "Line pipe of a kind used for oil or gas pipelines, seamless," in message  # description[:60]
    assert "of iron or steel" not in message
    assert "0.21" in message


@pytest.mark.asyncio
async def test_g001_warns_for_a_line_without_a_description_and_says_so(monkeypatch) -> None:
    docs = [doc("COMMERCIAL_INVOICE", line("73041900", desc=None)), doc("PACKING_LIST", line("73041900")),
            doc("BILL_OF_LADING")]
    check = g001(await ground(docs, monkeypatch, hits=[cand("73041900")]))

    assert check["severity"] == "WARN"
    assert "no description" in check["message"]
    assert "73041900" in check["message"]


@pytest.mark.asyncio
async def test_g001_counts_other_problem_lines(monkeypatch) -> None:
    docs = [doc("COMMERCIAL_INVOICE", line("730419"), line("73041100"), line("73041900")), doc("PACKING_LIST"),
            doc("BILL_OF_LADING")]
    check = g001(await ground(docs, monkeypatch, hits=[cand("73041900")]))

    assert check["severity"] == "WARN"
    assert "Other problem lines: 1" in check["message"]
    assert "730419" in check["message"]  # the FIRST problem line is the one described


@pytest.mark.asyncio
async def test_g001_is_never_material(monkeypatch) -> None:
    for declared in ("73041100", "10019910", "730419", None):
        ctx = await ground(bundle(declared), monkeypatch, hits=[cand("73041900")])
        assert g001(ctx)["severity"] == "WARN"


@pytest.mark.asyncio
async def test_g001_does_not_change_how_status_is_resolved(monkeypatch) -> None:
    monkeypatch.setattr(grounding, "lookup_tariff_with_source", FakeLookup([cand("73041900", 0.08)]))
    ctx = await calculation.run({"extracted": bundle("730419")})
    math_status = ctx["math_status"]

    ctx = await run_grounding_agent(ctx)

    assert ctx["math_status"] == math_status  # computed before grounding, untouched by G-001
    assert "force_status" not in ctx
    assert ctx["grounding_ambiguous"] is True  # this, not G-001, routes to specialist review


@pytest.mark.asyncio
async def test_g001_with_no_line_items_warns_that_nothing_was_classified() -> None:
    ctx = await ground([doc("BILL_OF_LADING")])
    check = g001(ctx)
    assert check["severity"] == "WARN"
    assert "no line item" in check["message"]
    assert check["evidence"] == []


@pytest.mark.asyncio
async def test_g001_is_added_even_when_the_stage_runs_without_prior_checks() -> None:
    ctx = await run_grounding_agent({"extracted": bundle("73041900")})
    assert [c["check_id"] for c in ctx["checks"]] == ["G-001"]


# ---------------------------------------------------------------------------
# certificates describe a test, not the goods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("cert_type", ["MILL_TEST_CERTIFICATE", "CERTIFICATE_OF_ORIGIN", "PHYTOSANITARY"])
async def test_certificate_lines_are_not_grounded(monkeypatch, cert_type) -> None:
    cert = ExtractedDocument(
        document_id="cert-001", doc_type=cert_type, doc_type_confidence=0.99,
        line_items=[line("73041900", desc="Chemical & mechanical test report API 5L PSL2")],
    )
    ctx = await ground(bundle("73041900") + [cert], monkeypatch, hits=[cand("73041900", 0.08)])

    assert [f["document_id"] for f in ctx["grounding"]] == ["inv-001", "pl-001"]
    # ONE lookup: the invoice and packing-list lines share a description (looked up once), and the certificate's own
    # description (a test report, not goods) is never looked up
    assert ctx["_fake"].queries == [DESCRIPTION]
    assert ctx["grounding_ambiguous"] is False
    assert g001(ctx)["severity"] == "PASS"


@pytest.mark.asyncio
async def test_a_satisfied_requirement_stays_satisfied_when_the_certificate_arrives() -> None:
    """Case C iteration 2: the MTC's test-report description must not flip the bundle back to review."""
    mtc = ExtractedDocument(
        document_id="mtc-001", doc_type="MILL_TEST_CERTIFICATE", doc_type_confidence=0.99,
        line_items=[line("73041900", desc="Chemical & mechanical test report API 5L PSL2")],
    )
    ctx = await ground(bundle("73041900") + [mtc])

    assert ctx["missing_evidence"] == []
    assert ctx["grounding_ambiguous"] is False


@pytest.mark.asyncio
async def test_a_line_with_neither_description_nor_code_is_skipped(monkeypatch) -> None:
    empty = line(None, desc=None)
    docs = [doc("COMMERCIAL_INVOICE", empty, line("73041900")), doc("PACKING_LIST"), doc("BILL_OF_LADING")]
    ctx = await ground(docs, monkeypatch, hits=[cand("73041900")])

    assert len(ctx["grounding"]) == 1  # only the real line is grounded and reported
    check = g001(ctx)
    assert check["severity"] == "PASS"
    assert [e["line_item"] for e in check["evidence"]] == [1]


# ---------------------------------------------------------------------------
# A: an exact-8 match that the description contradicts
# ---------------------------------------------------------------------------

COFFEE = "Roasted coffee beans"
CASE_C_FILES = {
    "inv-001": "commercial_invoice.pdf",
    "bol-001": "bill_of_lading.pdf",
    "pl-001": "packing_list.pdf",
    "mtc-001": "mtc_pipe_test_cert.pdf",
}
CONTRADICTION = re.compile(
    r"declared code '73041900' exists in the tariff, but the description matches HS 09012110 "
    r"\('[^']+', distance 0\.08\) much better \(declared row distance 0\.48\)"
)


def case_c_docs(*, description: str | None = None, with_mtc: bool = False) -> list[ExtractedDocument]:
    """The real Case C fixture documents; ``description`` replaces the commodity description on invoice + packing list."""
    wanted = ["inv-001", "bol-001", "pl-001"] + (["mtc-001"] if with_mtc else [])
    docs = [extraction._generate_fixture_for_file(doc_id, CASE_C_FILES[doc_id]) for doc_id in wanted]
    if description is not None:
        for d in docs:
            if d.doc_type in ("COMMERCIAL_INVOICE", "PACKING_LIST"):
                item = d.line_items[0]
                item.description = item.description.model_copy(update={"value": description})
    return docs


async def run_pipeline(docs: list[ExtractedDocument]) -> dict[str, Any]:
    """discrepancy -> ground -> confidence -> final status, in the orchestrator's order."""
    ctx = await calculation.run({"extracted": docs})
    ctx = await run_grounding_agent(ctx)
    ctx = await confidence.route(ctx)
    ctx["final_status"] = resolve_final_status(ctx)
    return ctx


def non_core_missing(ctx) -> list[str]:
    return [m["id"] for m in ctx["missing_evidence"] if not m["id"].startswith("ME-CORE-")]


@pytest.mark.asyncio
async def test_coffee_described_but_pipe_coded_is_contradicted_with_the_real_seed() -> None:
    ctx = await ground(case_c_docs(description=COFFEE))

    for document_id in ("inv-001", "pl-001"):
        f = finding_for(ctx, document_id)
        assert f["hs_mismatch"] is True, "the description matches the coffee row, not the declared pipe row"
        assert f["ambiguous"] is True
        assert f["required_documents"] == []
        assert f["better_match_hs"] == "09012110"
        assert f["hs_match_level"] == "exact8"  # the declared code does exist in the tariff
        assert f["governing_hs"] == "73041900"
        assert f["distance"] == 0.48  # the declared row's own distance
    assert ctx["grounding_ambiguous"] is True
    assert ctx["required_documents"] == []


@pytest.mark.asyncio
async def test_coffee_described_but_pipe_coded_derives_no_certificate_requirement() -> None:
    ctx = await ground(case_c_docs(description=COFFEE))

    assert non_core_missing(ctx) == [], "no Mill Test Certificate may be required on the strength of a contradicted code"
    assert ctx["missing_evidence"] == []  # the bundle has all three core documents


@pytest.mark.asyncio
async def test_coffee_described_but_pipe_coded_g001_warns_with_the_contradiction_message() -> None:
    check = g001(await ground(case_c_docs(description=COFFEE)))

    assert check["severity"] == "WARN"
    assert CONTRADICTION.search(check["message"]), check["message"]
    assert "Other problem lines: 1" in check["message"]  # the packing list carries the same claim


@pytest.mark.asyncio
async def test_coffee_described_but_pipe_coded_is_specialist_review_not_a_missing_certificate() -> None:
    ctx = await run_pipeline(case_c_docs(description=COFFEE))

    assert ctx["math_status"] == "COMPLIANT_FOR_SUBMISSION"  # the weights and H-002 are fine: only grounding objects
    assert ctx["final_status"] == "SPECIALIST_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_a_weak_exact8_match_that_nothing_contradicts_keeps_its_requirements_with_the_real_seed() -> None:
    """A2: every seed row is 0.48 for a description that overlaps nothing, so no row is a better fit."""
    ctx = await ground(case_c_docs(description="Industrial fasteners"))
    f = finding_for(ctx, "inv-001")

    assert f["distance"] == 0.48
    assert f["ambiguous"] is True
    assert f["hs_mismatch"] is False
    assert f["better_match_hs"] is None
    assert f["required_documents"] == ["MILL_TEST_CERTIFICATE"]
    assert non_core_missing(ctx) == ["ME-MILL_TEST_CERTIFICATE"]
    check = g001(ctx)
    assert check["severity"] == "WARN"
    assert "weak" in check["message"]
    assert "exists in the tariff" not in check["message"]


@pytest.mark.asyncio
async def test_case_c_is_not_affected_by_the_contradiction_rule() -> None:
    ctx = await run_pipeline(case_c_docs())
    f = finding_for(ctx, "inv-001")

    assert (f["hs_mismatch"], f["ambiguous"], f["better_match_hs"]) == (False, False, None)
    assert f["distance"] == 0.08
    assert f["required_documents"] == ["MILL_TEST_CERTIFICATE"]
    assert g001(ctx)["severity"] == "PASS"
    assert ctx["final_status"] == "MISSING_EVIDENCE"  # the certificate really is missing in iteration 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("alternative_distance", "contradicted"),
    [
        (AMBIGUITY_THRESHOLD - 0.01, True),
        (AMBIGUITY_THRESHOLD, True),            # exactly at the threshold counts as "within"
        (AMBIGUITY_THRESHOLD + 0.01, False),
    ],
)
async def test_the_alternative_must_be_within_the_threshold_inclusive(monkeypatch, alternative_distance, contradicted) -> None:
    hits = [cand("73041900", 0.60), cand("09012110", alternative_distance, docs=("PHYTOSANITARY",))]
    f = finding_for(await ground(bundle("73041900"), monkeypatch, hits=hits), "inv-001")

    assert f["hs_mismatch"] is contradicted
    assert f["better_match_hs"] == ("09012110" if contradicted else None)
    assert f["required_documents"] == ([] if contradicted else ["MILL_TEST_CERTIFICATE"])
    assert f["ambiguous"] is True


@pytest.mark.asyncio
async def test_a_governing_row_exactly_at_the_threshold_is_not_weak_so_nothing_contradicts_it(monkeypatch) -> None:
    hits = [cand("73041900", AMBIGUITY_THRESHOLD), cand("09012110", 0.05)]
    f = finding_for(await ground(bundle("73041900"), monkeypatch, hits=hits), "inv-001")

    assert (f["hs_mismatch"], f["ambiguous"], f["better_match_hs"]) == (False, False, None)
    assert f["required_documents"] == ["MILL_TEST_CERTIFICATE"]


@pytest.mark.asyncio
async def test_the_best_alternative_is_the_closest_and_ties_go_to_the_first_retrieved(monkeypatch) -> None:
    hits = [cand("73041900", 0.60), cand("73043100", 0.30), cand("09012110", 0.10), cand("10019910", 0.10)]
    f = finding_for(await ground(bundle("73041900"), monkeypatch, hits=hits), "inv-001")
    assert f["better_match_hs"] == "09012110"

    tie = [cand("73041900", 0.60), cand("73043100", 0.20), cand("09012110", 0.20)]
    f = finding_for(await ground(bundle("73041900"), monkeypatch, hits=tie), "inv-001")
    assert f["better_match_hs"] == "73043100"  # a sibling subheading is a different 8-digit code too


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", ["730419", "73041100", "10019910", "N/A", None])
async def test_only_an_exact8_claim_can_be_contradicted(monkeypatch, declared) -> None:
    hits = [cand("73041900", 0.60), cand("09012110", 0.05)]
    f = finding_for(await ground(bundle(declared), monkeypatch, hits=hits), "inv-001")

    assert f["hs_match_level"] != "exact8"
    assert f["better_match_hs"] is None


@pytest.mark.asyncio
async def test_a_contradicted_line_does_not_cancel_the_requirements_of_a_sound_line(monkeypatch) -> None:
    sound = line("73041900", desc="Seamless carbon steel pipes API 5L Grade B")
    contradicted = line("73041900", desc="Roasted coffee beans")

    def lookup(description: str, destination_country: str = "SG"):
        pipes = [cand("73041900", 0.08), cand("09012110", 0.48, docs=("PHYTOSANITARY",))]
        coffee = [cand("73041900", 0.60), cand("09012110", 0.08, docs=("PHYTOSANITARY",))]
        return (coffee if "coffee" in description else pipes), "seed"

    monkeypatch.setattr(grounding, "lookup_tariff_with_source", lookup)
    ctx = await run_grounding_agent({"extracted": [doc("COMMERCIAL_INVOICE", sound, contradicted),
                                                   doc("PACKING_LIST"), doc("BILL_OF_LADING")]})

    assert [f["hs_mismatch"] for f in ctx["grounding"]] == [False, True]
    assert ctx["required_documents"] == ["MILL_TEST_CERTIFICATE"]  # from the sound line only
    assert [m["id"] for m in ctx["missing_evidence"]] == ["ME-MILL_TEST_CERTIFICATE"]


def test_grounding_finding_carries_better_match_hs_and_old_findings_still_load() -> None:
    old = {"document_id": "d", "declared_hs": "73041900", "top_candidate_hs": "73041900",
           "top_candidate_description": "x", "distance": 0.1, "ambiguous": False}
    finding = GroundingFinding(**old)
    assert finding.better_match_hs is None
    assert finding.model_dump()["better_match_hs"] is None
    assert GroundingFinding(**old, better_match_hs="09012110").better_match_hs == "09012110"


def test_the_bigquery_seed_and_the_offline_seed_hold_the_same_rows() -> None:
    """Two copies of the demo tariff exist (demo mode reads the JSON, BigQuery is loaded from the SQL): keep them in step."""
    import re

    rows = json.loads((REPO / "infra" / "bigquery" / "seed" / "sample_tariff.json").read_text(encoding="utf-8"))
    sql = (REPO / "infra" / "bigquery" / "seed" / "seed_master_tariff.sql").read_text(encoding="utf-8")

    in_json = {f"{r['destination_country']}:{r['hs_code']}" for r in rows}
    in_sql = set(re.findall(r"SELECT '([A-Z]{2}:\d+)'", sql))  # the embedding sub-select lists the same keys
    assert in_json == in_sql and len(in_json) == len(rows), "a (destination, hs_code) pair must be unique"
    for row in rows:  # the descriptions are what gets embedded: they must match too
        assert row["description"] in sql, row["hs_code"]
        assert row["destination_country"] in {"SG", "IN"}


def test_the_seed_join_cannot_multiply_rows_when_a_code_has_two_destinations() -> None:
    sql = (REPO / "infra" / "bigquery" / "seed" / "seed_master_tariff.sql").read_text(encoding="utf-8")

    assert ") e ON t.k = e.k;" in sql and "ON t.hs_code = e.hs_code" not in sql
