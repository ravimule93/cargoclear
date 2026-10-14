"""W-001 (packing list vs Bill of Lading) and W-002 (packing list internal consistency).

The engine's rule: a check whose result depends on an ASSUMPTION never returns PASS or MATERIAL. It returns
WARN, lists every assumption in `assumptions`, and states the computed delta in the message. PASS/MATERIAL are
reserved for results computed purely from values and units the documents actually state.
"""

from __future__ import annotations

import pytest

from app.domain.schemas import BBox, ExtractedDocument, QuantityRef
from app.services import calculation
from app.services.calculation import _tolerance, check_weight_parity

TARE_ASSUMPTION = "tare not declared; assumed 2% of net (spec default)"
NO_UNIT = "no unit stated; assumed kg"


def q(value, unit="KGS", conf=0.97) -> QuantityRef:
    return QuantityRef(value=value, unit=unit, confidence=conf, bbox=BBox(page=1, ymin=10, xmin=20, ymax=30, xmax=40))


def packing(net=None, tare=None, gross=None, unit="KGS") -> ExtractedDocument:
    return ExtractedDocument(
        document_id="pl-001",
        doc_type="PACKING_LIST",
        doc_type_confidence=0.99,
        total_net_weight_kg=q(net, unit) if net is not None else None,
        tare_weight_kg=q(tare, unit) if tare is not None else None,
        total_gross_weight_kg=q(gross, unit) if gross is not None else None,
    )


def bol(gross=None, unit="KGS") -> ExtractedDocument:
    return ExtractedDocument(
        document_id="bol-001",
        doc_type="BILL_OF_LADING",
        doc_type_confidence=0.99,
        total_gross_weight_kg=q(gross, unit) if gross is not None else None,
    )


def fields_in(result) -> set[tuple[str, str]]:
    return {(e["doc"], e["field"]) for e in result.evidence}


# ---------------------------------------------------------------------------
# W-001, branch 1: net + DECLARED tare vs BoL gross
# ---------------------------------------------------------------------------


def test_net_plus_declared_tare_within_tolerance_passes_without_assumptions() -> None:
    r = check_weight_parity(packing(net=14000.0, tare=280.0), bol(gross=14280.0))

    assert r.check_id == "W-001"
    assert r.severity == "PASS"
    assert r.assumptions == []
    assert r.delta == 0.0
    assert r.tolerance == pytest.approx(71.4)
    assert r.message == "Net+tare (14280.0 kg) matches BoL gross (14280.0 kg) within tolerance (±71.4 kg)."


def test_evidence_lists_every_field_used_with_page_and_bbox() -> None:
    r = check_weight_parity(packing(net=14000.0, tare=280.0), bol(gross=14280.0))

    assert fields_in(r) == {
        ("pl-001", "total_net_weight_kg"),
        ("pl-001", "tare_weight_kg"),
        ("bol-001", "total_gross_weight_kg"),
    }
    for entry in r.evidence:
        assert entry["page"] == 1
        assert entry["bbox"]["xmin"] == 20


def test_delta_exactly_at_tolerance_passes() -> None:
    # gross 1000 kg -> tolerance is the 5 kg floor; 900 + 95 = 995, delta exactly 5.0
    r = check_weight_parity(packing(net=900.0, tare=95.0), bol(gross=1000.0))
    assert r.delta == 5.0
    assert r.tolerance == 5.0
    assert r.severity == "PASS"


def test_one_kg_beyond_tolerance_is_material() -> None:
    r = check_weight_parity(packing(net=900.0, tare=94.0), bol(gross=1000.0))
    assert r.severity == "MATERIAL"
    assert r.delta == 6.0
    assert r.assumptions == []
    assert "6.0 kg" in r.message


def test_relative_tolerance_boundary_on_a_large_consignment() -> None:
    gross = 100_000.0
    tol = _tolerance(gross)
    assert tol > 5.0  # 0.5% dominates here
    at = check_weight_parity(packing(net=gross - tol - 1000.0, tare=1000.0), bol(gross=gross))
    over = check_weight_parity(packing(net=gross - tol - 1001.0, tare=1000.0), bol(gross=gross))
    assert at.severity == "PASS"
    assert over.severity == "MATERIAL"


# ---------------------------------------------------------------------------
# W-001, branch 2: the packing list's DECLARED gross when tare is not declared
# ---------------------------------------------------------------------------


def test_tare_missing_but_packing_gross_declared_compares_the_declared_gross_with_no_assumption() -> None:
    r = check_weight_parity(packing(net=14000.0, gross=14280.0), bol(gross=14280.0))

    assert r.severity == "PASS"
    assert r.assumptions == []
    assert r.delta == 0.0
    assert fields_in(r) == {("pl-001", "total_gross_weight_kg"), ("bol-001", "total_gross_weight_kg")}
    assert "Packing list gross" in r.message
    assert "0.0 kg" in r.message


def test_tare_missing_packing_gross_beyond_tolerance_is_material_with_no_assumption() -> None:
    r = check_weight_parity(packing(net=14000.0, gross=14280.0), bol(gross=14500.0))

    assert r.severity == "MATERIAL"
    assert r.assumptions == []
    assert r.delta == pytest.approx(220.0)
    assert "220.0 kg" in r.message


def test_packing_gross_alone_is_enough_when_net_is_missing() -> None:
    r = check_weight_parity(packing(tare=280.0, gross=14280.0), bol(gross=14280.0))
    assert r.severity == "PASS"
    assert r.assumptions == []


# ---------------------------------------------------------------------------
# W-001, branch 3 (last resort): net + 2% default tare => always WARN
# ---------------------------------------------------------------------------


def test_no_tare_and_no_packing_gross_is_warn_with_the_assumption_even_when_the_delta_is_tiny() -> None:
    r = check_weight_parity(packing(net=14000.0), bol(gross=14280.0))  # 14000 * 1.02 == 14280 exactly

    assert r.severity == "WARN"
    assert r.assumptions == [TARE_ASSUMPTION]
    assert r.delta == pytest.approx(0.0, abs=1e-9)
    assert r.tolerance == pytest.approx(71.4)
    assert "0.0 kg" in r.message
    assert fields_in(r) == {("pl-001", "total_net_weight_kg"), ("bol-001", "total_gross_weight_kg")}


def test_no_tare_and_no_packing_gross_is_warn_not_material_even_when_the_delta_is_huge() -> None:
    r = check_weight_parity(packing(net=14000.0), bol(gross=20000.0))

    assert r.severity == "WARN"
    assert r.assumptions == [TARE_ASSUMPTION]
    assert r.delta == pytest.approx(5720.0)
    assert "5720.0 kg" in r.message
    assert "exceeds" in r.message  # the message still says how far off it is


def test_default_tare_ratio_is_only_used_in_the_last_resort_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    branch1 = check_weight_parity(packing(net=14000.0, tare=280.0), bol(gross=14280.0))
    branch2 = check_weight_parity(packing(net=14000.0, gross=14280.0), bol(gross=14280.0))
    branch3 = check_weight_parity(packing(net=14000.0), bol(gross=14280.0))

    monkeypatch.setattr(calculation, "DEFAULT_TARE_RATIO", 0.5)

    assert check_weight_parity(packing(net=14000.0, tare=280.0), bol(gross=14280.0)) == branch1
    assert check_weight_parity(packing(net=14000.0, gross=14280.0), bol(gross=14280.0)) == branch2
    changed = check_weight_parity(packing(net=14000.0), bol(gross=14280.0))
    assert changed.delta != branch3.delta  # 14000 + 50% tare = 21000


# ---------------------------------------------------------------------------
# W-001: units
# ---------------------------------------------------------------------------


def test_metric_tonnes_on_the_packing_list_convert_against_a_bol_in_kgs() -> None:
    r = check_weight_parity(packing(net=14.0, tare=0.28, unit="MT"), bol(gross=14280.0, unit="KGS"))

    assert r.severity == "PASS"
    assert r.assumptions == []
    assert r.delta == pytest.approx(0.0, abs=1e-9)
    assert "14280.0 kg" in r.message


def test_bol_in_metric_tonnes_converts_too() -> None:
    r = check_weight_parity(packing(net=14000.0, tare=280.0, unit="KGS"), bol(gross=14.28, unit="M/T"))
    assert r.severity == "PASS"
    assert r.assumptions == []


def test_pounds_convert_with_the_exact_factor() -> None:
    # 20 000 lb + 400 lb tare = 9253.284348 kg
    r = check_weight_parity(packing(net=20000.0, tare=400.0, unit="LBS"), bol(gross=9253.3, unit="KGS"))
    assert r.severity == "PASS"
    assert r.delta == pytest.approx(0.0157, abs=1e-3)


def test_a_wrong_unit_is_caught_not_hidden() -> None:
    """14 000 *lb* against 14 280 kg is a 7 930 kg contradiction, not a pass."""
    r = check_weight_parity(packing(net=14000.0, tare=280.0, unit="LBS"), bol(gross=14280.0, unit="KGS"))
    assert r.severity == "MATERIAL"
    assert r.delta == pytest.approx(14280.0 - 14280.0 * 0.45359237)


def test_missing_unit_is_warn_with_the_assumed_kg_assumption_and_the_delta() -> None:
    r = check_weight_parity(packing(net=14000.0, tare=280.0, unit=None), bol(gross=14280.0, unit=None))

    assert r.severity == "WARN"
    assert r.assumptions == [NO_UNIT]  # one entry even though two values lack a unit
    assert r.delta == 0.0
    assert "0.0 kg" in r.message


def test_missing_unit_stays_warn_even_when_the_delta_is_huge() -> None:
    r = check_weight_parity(packing(net=14000.0, tare=280.0, unit=None), bol(gross=30000.0, unit="KGS"))
    assert r.severity == "WARN"
    assert r.assumptions == [NO_UNIT]
    assert "15720.0 kg" in r.message


def test_unit_printed_inside_the_value_string_counts_as_a_stated_unit() -> None:
    p = ExtractedDocument(
        document_id="pl-001", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        total_net_weight_kg=q("14,000.00 KGS", unit=None), tare_weight_kg=q("280.00 KGS", unit=None),
    )
    r = check_weight_parity(p, bol(gross=14280.0))
    assert r.severity == "PASS"
    assert r.assumptions == []


def test_the_declared_unit_wins_over_a_unit_inside_the_value_string() -> None:
    p = ExtractedDocument(
        document_id="pl-001", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        total_net_weight_kg=q("14", unit="MT"), tare_weight_kg=q("0.28", unit="MT"),
    )
    assert check_weight_parity(p, bol(gross=14280.0)).severity == "PASS"


def test_unrecognised_unit_is_warn_naming_the_unit_with_no_delta() -> None:
    r = check_weight_parity(packing(net=14000.0, tare=280.0, unit="furlongs"), bol(gross=14280.0))

    assert r.severity == "WARN"
    assert r.check_id == "W-001"
    assert "unrecognised unit 'furlongs'" in r.message
    assert r.delta is None
    assert r.tolerance is None


def test_ambiguous_thousands_separator_is_an_assumption_so_the_check_warns() -> None:
    p = ExtractedDocument(
        document_id="pl-001", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        total_net_weight_kg=q("14,000"), tare_weight_kg=q(280.0),
    )
    r = check_weight_parity(p, bol(gross=14280.0))
    assert r.severity == "WARN"
    assert r.assumptions == ["thousands separator assumed for '14,000'"]
    assert r.delta == 0.0


def test_unambiguous_separators_do_not_warn() -> None:
    p = ExtractedDocument(
        document_id="pl-001", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        total_net_weight_kg=q("14,000.00"), tare_weight_kg=q("280.00"),
    )
    r = check_weight_parity(p, bol(gross="14,280.00"))
    assert r.severity == "PASS"
    assert r.assumptions == []


# ---------------------------------------------------------------------------
# W-001: not evaluable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pl", "bl"),
    [
        (packing(net=14000.0, tare=280.0), bol(gross=None)),  # BoL gross missing
        (packing(), bol(gross=14280.0)),  # nothing usable on the packing list
        (packing(tare=280.0), bol(gross=14280.0)),  # tare alone is not a weight to compare
    ],
)
def test_missing_values_are_not_evaluable(pl, bl) -> None:
    r = check_weight_parity(pl, bl)
    assert r.check_id == "W-001"
    assert r.severity == "WARN"
    assert "not evaluable" in r.message
    assert r.delta is None


def test_unreadable_value_is_not_evaluable_not_a_crash() -> None:
    p = ExtractedDocument(
        document_id="pl-001", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        total_net_weight_kg=q("N/A"), tare_weight_kg=q(280.0),
    )
    r = check_weight_parity(p, bol(gross=14280.0))
    assert r.severity == "WARN"
    assert "not evaluable" in r.message
    assert "total_net_weight_kg" in r.message


# ---------------------------------------------------------------------------
# W-002: packing list internal consistency (net + tare vs its own declared gross)
# ---------------------------------------------------------------------------


def test_w002_passes_when_the_packing_list_adds_up() -> None:
    r = calculation.check_packing_consistency(packing(net=14000.0, tare=280.0, gross=14280.0))

    assert r is not None
    assert r.check_id == "W-002"
    assert r.severity == "PASS"
    assert r.assumptions == []
    assert r.delta == 0.0
    assert r.tolerance == pytest.approx(71.4)
    assert fields_in(r) == {
        ("pl-001", "total_net_weight_kg"),
        ("pl-001", "tare_weight_kg"),
        ("pl-001", "total_gross_weight_kg"),
    }
    assert all(e["bbox"] is not None for e in r.evidence)


def test_w002_exactly_at_tolerance_passes_and_one_kg_beyond_is_material() -> None:
    at = calculation.check_packing_consistency(packing(net=900.0, tare=95.0, gross=1000.0))
    over = calculation.check_packing_consistency(packing(net=900.0, tare=94.0, gross=1000.0))
    assert at is not None and at.severity == "PASS" and at.delta == 5.0
    assert over is not None and over.severity == "MATERIAL" and over.delta == 6.0
    assert "6.0 kg" in over.message


@pytest.mark.parametrize(
    "doc",
    [
        packing(net=14000.0, tare=280.0),  # gross missing
        packing(net=14000.0, gross=14280.0),  # tare missing
        packing(tare=280.0, gross=14280.0),  # net missing
        packing(),
    ],
)
def test_w002_is_skipped_silently_unless_net_tare_and_gross_are_all_declared(doc) -> None:
    assert calculation.check_packing_consistency(doc) is None


def test_w002_converts_units() -> None:
    mixed = ExtractedDocument(
        document_id="pl-001", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        total_net_weight_kg=q(14.0, "MT"), tare_weight_kg=q(280.0, "KGS"), total_gross_weight_kg=q(14.28, "MT"),
    )
    r = calculation.check_packing_consistency(mixed)
    assert r is not None and r.severity == "PASS" and r.assumptions == []


def test_w002_missing_unit_warns_with_the_assumption_and_the_delta() -> None:
    r = calculation.check_packing_consistency(packing(net=14000.0, tare=280.0, gross=14500.0, unit=None))
    assert r is not None
    assert r.severity == "WARN"
    assert r.assumptions == [NO_UNIT]
    assert "220.0 kg" in r.message


def test_w002_unrecognised_unit_warns_without_a_delta() -> None:
    r = calculation.check_packing_consistency(packing(net=14000.0, tare=280.0, gross=14280.0, unit="furlongs"))
    assert r is not None
    assert r.severity == "WARN"
    assert "unrecognised unit 'furlongs'" in r.message
    assert r.delta is None


# ---------------------------------------------------------------------------
# run(): W-002 is part of the stage, and the roll-up honours WARN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_emits_w001_then_w002_for_a_complete_packing_list() -> None:
    ctx = {"extracted": [packing(net=14000.0, tare=280.0, gross=14280.0), bol(gross=14280.0)]}

    result = await calculation.run(ctx)

    severities = {c["check_id"]: c["severity"] for c in result["checks"]}
    assert severities == {"W-001": "PASS", "W-002": "PASS"}
    assert [c["check_id"] for c in result["checks"]] == ["W-001", "W-002"]
    assert result["math_status"] == "COMPLIANT_FOR_SUBMISSION"
    assert all(c["assumptions"] == [] for c in result["checks"])


@pytest.mark.asyncio
async def test_run_has_no_w002_without_a_packing_gross() -> None:
    ctx = {"extracted": [packing(net=14000.0, tare=280.0), bol(gross=14280.0)]}
    result = await calculation.run(ctx)
    assert [c["check_id"] for c in result["checks"]] == ["W-001"]


@pytest.mark.asyncio
async def test_run_rolls_an_assumption_based_check_up_to_specialist_review() -> None:
    ctx = {"extracted": [packing(net=14000.0), bol(gross=14280.0)]}

    result = await calculation.run(ctx)

    w001 = result["checks"][0]
    assert w001["severity"] == "WARN"
    assert w001["assumptions"] == [TARE_ASSUMPTION]
    assert result["math_status"] == "SPECIALIST_REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# Evidence for weights that carry no bounding box
# ---------------------------------------------------------------------------


def test_a_weight_without_a_bbox_is_still_evidence_with_page_1_and_no_box() -> None:
    p = ExtractedDocument(
        document_id="pl-001", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        total_net_weight_kg=QuantityRef(value=14000.0, unit="KGS", confidence=0.9),
        tare_weight_kg=QuantityRef(value=280.0, unit="KGS", confidence=0.9),
    )
    r = check_weight_parity(p, bol(gross=14280.0))
    net_entry = next(e for e in r.evidence if e["field"] == "total_net_weight_kg")
    # the printed value and unit travel with the entry (the UI shows them, and edits them in place)
    assert net_entry == {
        "doc": "pl-001", "field": "total_net_weight_kg", "page": 1, "bbox": None, "raw_value": 14000, "unit": "KGS",
    }
    assert r.severity == "PASS"
