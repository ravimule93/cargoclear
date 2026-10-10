"""Confidence routing is scoped to the fields the checks actually use, and it explains itself.

  min_overall_confidence   minimum over EVERY populated field (the old semantics)
  min_field_confidence     minimum over the fields cited by ctx["checks"][*].evidence (the key the UI shows)
  min_doc_type_confidence  minimum doc_type_confidence over ALL extracted documents
  tier                     min(min_field_confidence, min_doc_type_confidence) against 0.95 / 0.65
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents import extraction
from app.agents.grounding import run_grounding_agent
from app.domain.schemas import BBox, ConfidenceResult, ExtractedDocument, FieldRef, LineItem
from app.services import calculation, confidence
from app.services.orchestrator import PIPELINE_STAGES

COMPLIANT = "COMPLIANT_FOR_SUBMISSION"


def ref(value, conf: float = 0.99) -> FieldRef:
    return FieldRef(value=value, confidence=conf, bbox=BBox(page=1, ymin=1, xmin=2, ymax=3, xmax=4))


def line(*, hs=("73041900", 0.99), description=("pipes", 0.99)) -> LineItem:
    return LineItem(
        description=ref(*description), quantity=ref("1"), net_weight_kg=ref(1.0), gross_weight_kg=ref(1.0),
        hs_code_declared=ref(*hs),
    )


def doc(document_id: str = "pl", doc_type: str = "PACKING_LIST", doc_conf: float = 0.99, **fields) -> ExtractedDocument:
    return ExtractedDocument(document_id=document_id, doc_type=doc_type, doc_type_confidence=doc_conf, **fields)


def check(check_id: str, *evidence: dict[str, Any]) -> dict[str, Any]:
    return {"check_id": check_id, "severity": "PASS", "message": "", "evidence": list(evidence)}


def ev(doc_id: str, field: str, line_item: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"doc": doc_id, "field": field}
    if line_item is not None:
        entry["line_item"] = line_item
    return entry


async def route(docs: list[ExtractedDocument], checks: list[dict[str, Any]] | None = None,
                math_status: str = COMPLIANT) -> dict[str, Any]:
    ctx: dict[str, Any] = {"extracted": docs, "math_status": math_status}
    if checks is not None:
        ctx["checks"] = checks
    return await confidence.route(ctx)


# ---------------------------------------------------------------------------
# an irrelevant low-confidence field no longer forces review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_irrelevant_low_confidence_field_does_not_force_review() -> None:
    packing = doc(consignee=ref("ACME"), port_of_loading=ref("INNSA", 0.80), total_net_weight_kg=ref(14000.0))
    checks = [check("W-001", ev("pl", "total_net_weight_kg")), check("E-consignee", ev("pl", "consignee"))]

    ctx = await route([packing], checks)
    result = ctx["confidence"]

    assert result["action"] == "AUTO_ACCEPT"
    assert "force_status" not in ctx
    assert result["min_overall_confidence"] == 0.80  # the old semantics are still reported
    assert result["min_field_confidence"] == 0.99
    assert result["low_confidence_fields"] == []


@pytest.mark.asyncio
async def test_the_same_field_forces_review_once_a_check_cites_it() -> None:
    packing = doc(consignee=ref("ACME"), port_of_loading=ref("INNSA", 0.80))

    ctx = await route([packing], [check("X-001", ev("pl", "port_of_loading"))])

    assert ctx["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# a low-confidence cited field forces review, and says why
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cited_field_below_the_high_threshold_forces_interactive_review_and_is_listed() -> None:
    packing = doc("packing_list", total_net_weight_kg=ref(14000.0, 0.88), total_gross_weight_kg=ref(14280.0))
    checks = [
        check("W-001", ev("packing_list", "total_net_weight_kg"), ev("packing_list", "total_gross_weight_kg")),
        check("W-002", ev("packing_list", "total_net_weight_kg")),
    ]

    ctx = await route([packing], checks)
    result = ctx["confidence"]

    assert result["action"] == "INTERACTIVE_REVIEW"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"
    assert result["min_field_confidence"] == 0.88
    assert result["low_confidence_fields"] == [
        {"document_id": "packing_list", "field": "total_net_weight_kg", "confidence": 0.88,
         "used_by": ["W-001", "W-002"]},
    ]
    assert result["reason"] == (
        "Lowest confidence among fields used by checks: packing_list.total_net_weight_kg (0.88) -> interactive review."
    )


@pytest.mark.asyncio
async def test_a_cited_field_below_the_minimum_threshold_is_manual_entry() -> None:
    packing = doc(total_net_weight_kg=ref(14000.0, 0.64))

    ctx = await route([packing], [check("W-001", ev("pl", "total_net_weight_kg"))])

    assert ctx["confidence"]["action"] == "MANUAL_ENTRY"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"
    assert ctx["confidence"]["reason"].endswith("(0.64) -> manual entry.")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("conf", "action"),
    [(0.95, "AUTO_ACCEPT"), (0.9499, "INTERACTIVE_REVIEW"), (0.65, "INTERACTIVE_REVIEW"), (0.6499, "MANUAL_ENTRY")],
)
async def test_the_thresholds_are_unchanged(conf, action) -> None:
    ctx = await route([doc(total_net_weight_kg=ref(1.0, conf))], [check("W-001", ev("pl", "total_net_weight_kg"))])
    assert ctx["confidence"]["action"] == action


@pytest.mark.asyncio
async def test_high_confidence_with_a_failed_check_is_auto_flag() -> None:
    ctx = await route([doc(total_net_weight_kg=ref(1.0))], [check("W-001", ev("pl", "total_net_weight_kg"))],
                      math_status="MATERIAL_CONTRADICTION")
    assert ctx["confidence"]["action"] == "AUTO_FLAG"
    assert "force_status" not in ctx


@pytest.mark.asyncio
async def test_an_all_confident_bundle_says_so() -> None:
    ctx = await route([doc(total_net_weight_kg=ref(1.0))], [check("W-001", ev("pl", "total_net_weight_kg"))])
    assert ctx["confidence"]["reason"] == "Every field used by a check and every document classification is >= 0.95."
    assert ctx["confidence"]["low_confidence_fields"] == []


# ---------------------------------------------------------------------------
# document classification confidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_document_at_030_drives_the_tier_and_is_listed_as_doc_type() -> None:
    packing = doc(total_net_weight_kg=ref(14000.0))
    unknown = doc("unk-1", "UNKNOWN", 0.30, document_number=ref("DOC-UNK-001", 0.30))
    checks = [check("W-001", ev("pl", "total_net_weight_kg"))]  # nothing cites the unknown document

    ctx = await route([packing, unknown], checks)
    result = ctx["confidence"]

    assert result["action"] == "MANUAL_ENTRY"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"
    assert result["min_doc_type_confidence"] == 0.30
    assert result["min_field_confidence"] == 0.99  # the cited fields are fine; the classification is not
    assert result["min_overall_confidence"] == 0.30
    assert {"document_id": "unk-1", "field": "doc_type", "confidence": 0.30} in result["low_confidence_fields"]
    assert "unk-1" in result["reason"] and "document classification" in result["reason"]
    assert result["reason"].endswith("(0.30) -> manual entry.")


@pytest.mark.asyncio
@pytest.mark.parametrize(("doc_conf", "action"), [(0.95, "AUTO_ACCEPT"), (0.80, "INTERACTIVE_REVIEW"), (0.50, "MANUAL_ENTRY")])
async def test_the_doc_type_confidence_alone_sets_the_tier(doc_conf, action) -> None:
    packing = doc(doc_conf=doc_conf, total_net_weight_kg=ref(1.0))

    ctx = await route([packing], [check("W-001", ev("pl", "total_net_weight_kg"))])

    assert ctx["confidence"]["action"] == action
    assert ctx["confidence"]["min_doc_type_confidence"] == doc_conf


@pytest.mark.asyncio
async def test_the_tier_is_the_lower_of_the_field_and_the_doc_type_confidence() -> None:
    low_field = doc(doc_conf=0.90, total_net_weight_kg=ref(1.0, 0.60))
    ctx = await route([low_field], [check("W-001", ev("pl", "total_net_weight_kg"))])
    assert ctx["confidence"]["action"] == "MANUAL_ENTRY"  # 0.60 field beats 0.90 classification

    low_type = doc(doc_conf=0.70, total_net_weight_kg=ref(1.0, 0.90))
    ctx = await route([low_type], [check("W-001", ev("pl", "total_net_weight_kg"))])
    assert ctx["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert ctx["confidence"]["reason"].startswith("Lowest confidence is the document classification of pl (0.70)")


@pytest.mark.asyncio
async def test_a_field_and_a_doc_type_at_the_same_confidence_name_the_field() -> None:
    packing = doc(doc_conf=0.80, total_net_weight_kg=ref(1.0, 0.80))
    ctx = await route([packing], [check("W-001", ev("pl", "total_net_weight_kg"))])
    assert ctx["confidence"]["reason"].startswith("Lowest confidence among fields used by checks: pl.total_net_weight_kg")


@pytest.mark.asyncio
async def test_every_low_doc_type_is_listed_even_when_no_check_cites_the_document() -> None:
    docs = [doc("a", doc_conf=0.90, total_net_weight_kg=ref(1.0)), doc("b", doc_conf=0.70), doc("c", doc_conf=0.99)]

    ctx = await route(docs, [check("W-001", ev("a", "total_net_weight_kg"))])

    assert [(e["document_id"], e["field"], e["confidence"]) for e in ctx["confidence"]["low_confidence_fields"]] == [
        ("b", "doc_type", 0.70), ("a", "doc_type", 0.90),
    ]


# ---------------------------------------------------------------------------
# what counts as a cited field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cited_field_with_no_value_is_ignored() -> None:
    packing = doc(consignee=ref(None, 0.10), total_net_weight_kg=ref(14000.0))

    ctx = await route([packing], [check("E-consignee", ev("pl", "consignee")), check("W-001", ev("pl", "total_net_weight_kg"))])

    assert ctx["confidence"]["min_field_confidence"] == 0.99
    assert ctx["confidence"]["action"] == "AUTO_ACCEPT"
    assert ctx["confidence"]["min_overall_confidence"] == 0.99  # an unpopulated field is never counted anywhere


@pytest.mark.asyncio
async def test_a_line_item_index_selects_that_line_only() -> None:
    invoice = doc("inv", "COMMERCIAL_INVOICE", line_items=[line(), line(hs=("73041900", 0.80))])

    only_clean = await route([invoice], [check("G-001", ev("inv", "hs_code_declared", 0))])
    assert only_clean["confidence"]["action"] == "AUTO_ACCEPT"

    only_weak = await route([invoice], [check("G-001", ev("inv", "hs_code_declared", 1))])
    assert only_weak["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert only_weak["confidence"]["low_confidence_fields"] == [
        {"document_id": "inv", "field": "hs_code_declared", "line_item": 1, "confidence": 0.80, "used_by": ["G-001"]},
    ]
    assert "inv.line_items[1].hs_code_declared (0.80)" in only_weak["confidence"]["reason"]


@pytest.mark.asyncio
async def test_a_line_item_field_without_an_index_covers_every_line_of_the_document() -> None:
    invoice = doc("inv", "COMMERCIAL_INVOICE", line_items=[line(), line(hs=("73041900", 0.80))])

    ctx = await route([invoice], [check("H-002", ev("inv", "hs_code_declared"))])

    assert ctx["confidence"]["min_field_confidence"] == 0.80
    assert [(e["field"], e["line_item"]) for e in ctx["confidence"]["low_confidence_fields"]] == [("hs_code_declared", 1)]


@pytest.mark.asyncio
async def test_the_same_line_field_is_one_entry_even_when_several_checks_cite_it() -> None:
    invoice = doc("inv", "COMMERCIAL_INVOICE", line_items=[line(hs=("73041900", 0.80))])
    checks = [check("H-002", ev("inv", "hs_code_declared")), check("G-001", ev("inv", "hs_code_declared", 0)),
              check("H-003-MILL_TEST_CERTIFICATE", ev("inv", "hs_code_declared", 0))]

    ctx = await route([invoice], checks)

    [entry] = ctx["confidence"]["low_confidence_fields"]
    assert entry["used_by"] == ["G-001", "H-002", "H-003-MILL_TEST_CERTIFICATE"]


@pytest.mark.asyncio
async def test_a_header_hs_code_resolves_as_a_top_level_field() -> None:
    certificate = doc("mtc", "MILL_TEST_CERTIFICATE", hs_code_header=ref("73041900", 0.85))

    ctx = await route([certificate], [check("H-003-MILL_TEST_CERTIFICATE", ev("mtc", "hs_code_header"))])

    assert ctx["confidence"]["min_field_confidence"] == 0.85
    assert "line_item" not in ctx["confidence"]["low_confidence_fields"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_entry",
    [
        ev("nobody", "total_net_weight_kg"),            # unknown document
        ev("pl", "no_such_field"),                       # unknown field
        ev("pl", "line_items"),                          # not a FieldRef
        ev("pl", "doc_type"),                            # not a FieldRef
        ev("pl", "hs_code_declared", 7),                 # line index out of range
        ev("pl", "total_net_weight_kg", 0),              # a header field addressed as a line item
        {"doc": "pl"},                                   # no field
        {"field": "total_net_weight_kg"},                # no doc
        {"doc": "pl", "field": 5},                       # field is not a name
        {"doc": "pl", "field": "hs_code_declared", "line_item": -1},
        {"doc": "pl", "field": "hs_code_declared", "line_item": "0"},
        {"doc": "pl", "field": "hs_code_declared", "line_item": True},
    ],
)
async def test_unresolvable_evidence_is_ignored_and_falls_back_to_all_populated_fields(bad_entry) -> None:
    packing = doc(total_net_weight_kg=ref(14000.0, 0.70), consignee=ref("ACME"), line_items=[line()])

    ctx = await route([packing], [check("W-001", bad_entry)])
    result = ctx["confidence"]

    assert result["min_field_confidence"] == 0.70  # no field resolved: every populated field is in scope
    assert result["action"] == "INTERACTIVE_REVIEW"
    assert result["reason"].startswith("Lowest confidence among all populated fields (no check cites a field)")


@pytest.mark.asyncio
@pytest.mark.parametrize("checks", [None, [], [check("D-DUP-X")], [{"check_id": "X", "severity": "PASS", "message": ""}]])
async def test_without_any_evidence_all_populated_fields_are_in_scope(checks) -> None:
    packing = doc(total_net_weight_kg=ref(14000.0), port_of_loading=ref("INNSA", 0.80))

    ctx = await route([packing], checks)

    assert ctx["confidence"]["min_field_confidence"] == 0.80
    assert ctx["confidence"]["min_overall_confidence"] == 0.80
    assert ctx["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert ctx["confidence"]["low_confidence_fields"] == [
        {"document_id": "pl", "field": "port_of_loading", "confidence": 0.80, "used_by": []},
    ]


@pytest.mark.asyncio
async def test_evidence_that_is_not_a_list_of_dicts_never_breaks_routing() -> None:
    packing = doc(total_net_weight_kg=ref(14000.0, 0.70))
    checks = [{"check_id": "W-001", "evidence": ["pl.total_net_weight_kg", None, 7]}, {"check_id": "W-002", "evidence": None}]

    ctx = await route([packing], checks)

    assert ctx["confidence"]["min_field_confidence"] == 0.70  # nothing resolved: fall back to all populated fields
    assert ctx["confidence"]["action"] == "INTERACTIVE_REVIEW"


@pytest.mark.asyncio
async def test_one_resolvable_entry_among_unresolvable_ones_keeps_the_scope_narrow() -> None:
    packing = doc(total_net_weight_kg=ref(14000.0), port_of_loading=ref("INNSA", 0.80))

    ctx = await route([packing], [check("W-001", ev("nobody", "x"), ev("pl", "total_net_weight_kg"))])

    assert ctx["confidence"]["action"] == "AUTO_ACCEPT"
    assert ctx["confidence"]["min_field_confidence"] == 0.99


# ---------------------------------------------------------------------------
# nothing to route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_bundle_is_manual_entry() -> None:
    ctx = await route([], [check("W-001", ev("pl", "x"))])
    result = ctx["confidence"]

    assert result["action"] == "MANUAL_ENTRY"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"
    assert result["min_field_confidence"] == 0.0
    assert result["min_overall_confidence"] is None
    assert result["min_doc_type_confidence"] is None
    assert result["low_confidence_fields"] == []
    assert result["reason"] == "No documents were extracted -> manual entry."


@pytest.mark.asyncio
async def test_documents_with_no_populated_field_are_manual_entry() -> None:
    ctx = await route([doc(doc_conf=0.99)], [check("W-001", ev("pl", "total_net_weight_kg"))])
    result = ctx["confidence"]

    assert result["action"] == "MANUAL_ENTRY"
    assert result["min_field_confidence"] == 0.0
    assert result["min_overall_confidence"] is None
    assert result["min_doc_type_confidence"] == 0.99
    assert result["reason"] == "No populated field was extracted -> manual entry."


@pytest.mark.asyncio
async def test_a_bundle_with_no_checks_key_at_all_still_routes() -> None:
    ctx = await confidence.route({"extracted": [doc(consignee=ref("ACME"))]})
    assert ctx["confidence"]["action"] == "AUTO_ACCEPT"


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_old_keys_are_still_present_and_the_result_validates_as_a_schema() -> None:
    ctx = await route([doc(total_net_weight_kg=ref(1.0, 0.9))], [check("W-001", ev("pl", "total_net_weight_kg"))])
    result = ctx["confidence"]

    assert {"min_field_confidence", "action"} <= set(result)
    assert set(result) == {"min_field_confidence", "action", "min_overall_confidence", "min_doc_type_confidence",
                           "low_confidence_fields", "reason"}
    validated = ConfidenceResult(**result)
    assert validated.min_overall_confidence == 0.9
    assert validated.model_dump() == result


def test_a_confidence_result_stored_before_the_new_fields_still_loads() -> None:
    old = ConfidenceResult(min_field_confidence=0.9, action="INTERACTIVE_REVIEW")

    assert old.min_overall_confidence is None
    assert old.min_doc_type_confidence is None
    assert old.low_confidence_fields == []
    assert old.reason is None


@pytest.mark.asyncio
async def test_values_are_rounded_to_four_decimals() -> None:
    ctx = await route([doc(doc_conf=0.987654321, total_net_weight_kg=ref(1.0, 0.912345678))],
                      [check("W-001", ev("pl", "total_net_weight_kg"))])
    assert ctx["confidence"]["min_field_confidence"] == 0.9123
    assert ctx["confidence"]["min_doc_type_confidence"] == 0.9877
    assert ctx["confidence"]["low_confidence_fields"][0]["confidence"] == 0.9123


@pytest.mark.asyncio
async def test_low_confidence_fields_are_ascending_and_capped_at_ten() -> None:
    items = [line(hs=("73041900", 0.60 + i * 0.02)) for i in range(14)]
    invoice = doc("inv", "COMMERCIAL_INVOICE", line_items=items)

    ctx = await route([invoice], [check("H-002", ev("inv", "hs_code_declared"))])
    entries = ctx["confidence"]["low_confidence_fields"]

    assert len(entries) == 10
    assert [e["confidence"] for e in entries] == sorted(e["confidence"] for e in entries)
    assert entries[0]["confidence"] == 0.60 and entries[0]["line_item"] == 0
    assert "inv.line_items[0].hs_code_declared (0.60)" in ctx["confidence"]["reason"]


@pytest.mark.asyncio
async def test_a_field_at_exactly_the_high_threshold_is_not_listed() -> None:
    ctx = await route([doc(total_net_weight_kg=ref(1.0, 0.95))], [check("W-001", ev("pl", "total_net_weight_kg"))])
    assert ctx["confidence"]["low_confidence_fields"] == []


# ---------------------------------------------------------------------------
# wiring: confidence runs after grounding and sees G-001 and H-003
# ---------------------------------------------------------------------------


def test_the_pipeline_runs_confidence_after_discrepancy_and_grounding() -> None:
    assert PIPELINE_STAGES.index("discrepancy") < PIPELINE_STAGES.index("ground") < PIPELINE_STAGES.index("confidence")


@pytest.mark.asyncio
async def test_a_low_confidence_hs_field_cited_only_by_g001_routes_to_review() -> None:
    """The bill of lading's commodity line is in no other check: only G-001 cites its HS code."""
    invoice = doc("inv-001", "COMMERCIAL_INVOICE", line_items=[line()])
    packing = doc("pl-001", "PACKING_LIST", line_items=[line()])
    bol = doc("bol-001", "BILL_OF_LADING", line_items=[line(hs=("73041900", 0.80))])
    docs = [invoice, packing, bol]

    before_grounding = await confidence.route(await calculation.run({"extracted": docs}))
    # no check before G-001 cites the bill of lading line, so nothing is listed and no review is forced
    # (the bundle has no weights, so W-001 warns and the high-confidence tier reads AUTO_FLAG)
    assert before_grounding["confidence"]["action"] in ("AUTO_ACCEPT", "AUTO_FLAG")
    assert before_grounding["confidence"]["low_confidence_fields"] == []
    assert "force_status" not in before_grounding

    ctx = await run_grounding_agent(await calculation.run({"extracted": docs}))
    ctx = await confidence.route(ctx)

    assert ctx["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"
    assert ctx["confidence"]["low_confidence_fields"] == [
        {"document_id": "bol-001", "field": "hs_code_declared", "line_item": 0, "confidence": 0.80,
         "used_by": ["G-001"]},
    ]


@pytest.mark.asyncio
async def test_a_low_confidence_certificate_hs_field_is_seen_through_h003() -> None:
    invoice = doc("inv-001", "COMMERCIAL_INVOICE", line_items=[line()])
    certificate = doc("mtc-001", "MILL_TEST_CERTIFICATE", hs_code_header=ref("73041900", 0.85))

    ctx = await confidence.route(await calculation.run({"extracted": [invoice, certificate]}))

    assert ctx["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert ctx["confidence"]["low_confidence_fields"] == [
        {"document_id": "mtc-001", "field": "hs_code_header", "confidence": 0.85,
         "used_by": ["H-003-MILL_TEST_CERTIFICATE"]},
    ]


# ---------------------------------------------------------------------------
# Case C
# ---------------------------------------------------------------------------

CASE_C = {"inv-001": "commercial_invoice.pdf", "bol-001": "bill_of_lading.pdf", "pl-001": "packing_list.pdf",
          "mtc-001": "mtc_pipe_test_cert.pdf"}


async def case_c(iteration: int) -> dict[str, Any]:
    wanted = ["inv-001", "bol-001", "pl-001"] + (["mtc-001"] if iteration == 2 else [])
    docs = [extraction._generate_fixture_for_file(doc_id, CASE_C[doc_id]) for doc_id in wanted]
    ctx = await calculation.run({"extracted": docs})
    ctx = await run_grounding_agent(ctx)
    return await confidence.route(ctx)


@pytest.mark.asyncio
async def test_case_c_iteration_2_is_still_auto_accept_and_the_numbers_are_explained() -> None:
    ctx = await case_c(2)
    result = ctx["confidence"]

    assert result["action"] == "AUTO_ACCEPT"
    assert "force_status" not in ctx
    assert result["min_doc_type_confidence"] == 0.99
    assert result["min_field_confidence"] >= result["min_overall_confidence"] >= 0.95
    assert result["low_confidence_fields"] == []
    assert result["reason"] == "Every field used by a check and every document classification is >= 0.95."


@pytest.mark.asyncio
async def test_case_c_iteration_1_has_the_same_confidence_tier() -> None:
    ctx = await case_c(1)
    assert ctx["confidence"]["action"] == "AUTO_ACCEPT"
    assert ctx["confidence"]["min_doc_type_confidence"] == 0.99
