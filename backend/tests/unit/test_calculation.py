"""Unit tests for the deterministic calculation engine.

Coverage requirement: ≥95% of app/services/calculation.py

Test cases:
  - Weight parity: PASS, WARN (missing data), MATERIAL (exceeds tolerance)
  - HS consistency: PASS, WARN (missing HS), MATERIAL (divergence)
  - Entity alignment: PASS, MATERIAL (inconsistent consignee/vessel)
  - Status roll-up: all 3 outcomes
  - Tolerance boundary conditions
"""

import pytest
from app.domain.schemas import ExtractedDocument, FieldRef, LineItem, BBox, QuantityRef
from app.services.calculation import (
    check_weight_parity,
    check_hs_consistency,
    check_entity_alignment,
    _roll_up,
    _tolerance,
    REL_TOL,
    ABS_TOL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ref(v, c=0.97):
    return FieldRef(
        value=v, confidence=c,
        bbox=BBox(page=1, ymin=0, xmin=0, ymax=100, xmax=100),
    )


def qty(v, unit="KGS", c=0.97):
    """A weight as the documents state it: the number AND its printed unit."""
    return QuantityRef(
        value=v, unit=unit, confidence=c,
        bbox=BBox(page=1, ymin=0, xmin=0, ymax=100, xmax=100),
    )


def make_packing(net=14000.0, tare=None, hs="73041900", consignee="ACME"):
    return ExtractedDocument(
        document_id="pl-001",
        doc_type="PACKING_LIST",
        doc_type_confidence=0.99,
        total_net_weight_kg=qty(net),
        tare_weight_kg=qty(tare) if tare is not None else None,
        consignee=ref(consignee),
        line_items=[
            LineItem(
                description=ref("Steel pipes"),
                quantity=ref("100 PCS"),
                net_weight_kg=qty(net),
                gross_weight_kg=qty(net + (tare or 0.0)),
                hs_code_declared=ref(hs),
            )
        ],
    )


def make_bol(gross=14280.0, consignee="ACME"):
    return ExtractedDocument(
        document_id="bol-001",
        doc_type="BILL_OF_LADING",
        doc_type_confidence=0.99,
        total_gross_weight_kg=qty(gross),
        consignee=ref(consignee),
    )


def make_invoice(hs="73041900"):
    return ExtractedDocument(
        document_id="inv-001",
        doc_type="COMMERCIAL_INVOICE",
        doc_type_confidence=0.99,
        line_items=[
            LineItem(
                description=ref("Steel pipes"),
                quantity=ref("100 PCS"),
                net_weight_kg=ref(14000.0),
                gross_weight_kg=ref(14280.0),
                hs_code_declared=ref(hs),
            )
        ],
    )


# ---------------------------------------------------------------------------
# Tolerance helper
# ---------------------------------------------------------------------------


def test_tolerance_uses_absolute_minimum():
    """For small gross weights, tolerance should be ABS_TOL (5 kg)."""
    assert _tolerance(100.0) == ABS_TOL  # 0.5% × 100 = 0.5 < 5


def test_tolerance_uses_relative_for_large_weights():
    """For large gross weights, tolerance should be REL_TOL × gross."""
    gross = 10_000.0
    assert _tolerance(gross) == REL_TOL * gross  # 50 kg > 5 kg


# ---------------------------------------------------------------------------
# Weight parity checks
# ---------------------------------------------------------------------------


class TestWeightParity:
    """W-001 against explicit, DECLARED tare. The no-tare / no-unit / unit-conversion rules live in
    tests/unit/test_weight_rules.py; the first versions of these tests relied on a silent 2% default tare."""

    def test_pass_within_tolerance(self):
        """net + declared tare ≈ gross → PASS."""
        net, tare = 14000.0, 280.0
        gross = net + tare  # exact
        packing = make_packing(net=net, tare=tare)
        bol = make_bol(gross=gross)
        result = check_weight_parity(packing, bol)
        assert result.severity == "PASS"
        assert result.check_id == "W-001"
        assert result.assumptions == []

    def test_pass_explicit_tare(self):
        """Explicit tare declared — still within tolerance."""
        net, tare, gross = 14000.0, 280.0, 14280.0
        packing = make_packing(net=net, tare=tare)
        bol = make_bol(gross=gross)
        result = check_weight_parity(packing, bol)
        assert result.severity == "PASS"
        assert result.delta is not None
        assert result.delta <= result.tolerance

    def test_material_large_delta(self):
        """Delta of 180 kg on 14 000 kg gross → MATERIAL."""
        net, tare = 14000.0, 280.0  # expected 14 280 kg
        gross_wrong = 14460.0  # delta = 180 kg, tol = max(0.5% × 14460, 5) ≈ 72.3 kg
        packing = make_packing(net=net, tare=tare)
        bol = make_bol(gross=gross_wrong)
        result = check_weight_parity(packing, bol)
        assert result.severity == "MATERIAL"
        assert result.delta is not None
        assert result.delta > result.tolerance

    def test_warn_missing_net_weight(self):
        """Missing net weight → WARN, not crash."""
        packing = ExtractedDocument(
            document_id="pl-no-net",
            doc_type="PACKING_LIST",
            doc_type_confidence=0.9,
        )
        bol = make_bol()
        result = check_weight_parity(packing, bol)
        assert result.severity == "WARN"

    def test_warn_missing_gross_weight(self):
        """Missing gross weight → WARN."""
        packing = make_packing()
        bol = ExtractedDocument(
            document_id="bol-no-gross",
            doc_type="BILL_OF_LADING",
            doc_type_confidence=0.9,
        )
        result = check_weight_parity(packing, bol)
        assert result.severity == "WARN"

    def test_boundary_exactly_at_tolerance(self):
        """Delta exactly at the tolerance boundary → PASS (≤ tol).

        Tolerance is computed on the BoL gross: 1 000 kg gross -> the 5 kg floor; 900 + 95 = 995, delta == 5.0.
        (The first version of this test claimed to sit on the boundary but was 0.357 kg inside it.)
        """
        packing = make_packing(net=900.0, tare=95.0)
        bol = make_bol(gross=1000.0)
        result = check_weight_parity(packing, bol)
        assert result.delta == result.tolerance == ABS_TOL
        assert result.severity == "PASS"

    def test_boundary_just_over_tolerance(self):
        """Delta just above tolerance → MATERIAL."""
        net, tare = 14000.0, 280.0
        expected = net + tare
        gross_over = (expected / (1.0 - REL_TOL)) + 1.0
        packing = make_packing(net=net, tare=tare)
        bol = make_bol(gross=gross_over)
        result = check_weight_parity(packing, bol)
        assert result.severity == "MATERIAL"


# ---------------------------------------------------------------------------
# HS consistency checks
# ---------------------------------------------------------------------------


class TestHsConsistency:
    def test_pass_same_hs(self):
        invoice = make_invoice(hs="73041900")
        packing = make_packing(hs="73041900")
        result = check_hs_consistency(invoice, packing)
        assert result.severity == "PASS"

    def test_material_hs_divergence(self):
        invoice = make_invoice(hs="73041900")
        packing = make_packing(hs="73043100")
        result = check_hs_consistency(invoice, packing)
        assert result.severity == "MATERIAL"

    def test_warn_missing_hs_on_invoice(self):
        invoice = ExtractedDocument(
            document_id="inv-no-hs",
            doc_type="COMMERCIAL_INVOICE",
            doc_type_confidence=0.9,
        )
        packing = make_packing(hs="73041900")
        result = check_hs_consistency(invoice, packing)
        assert result.severity == "WARN"


# ---------------------------------------------------------------------------
# Entity alignment checks
# ---------------------------------------------------------------------------


class TestEntityAlignment:
    def test_pass_all_consistent(self):
        docs = [make_packing(consignee="ACME"), make_bol(consignee="ACME")]
        results = check_entity_alignment(docs)
        assert all(r.severity in ("PASS",) for r in results) or results == []

    def test_normalized_entity_names_match(self):
        docs = [
            make_packing(consignee="SINGAPORE TRADING PTE. LTD."),
            make_bol(consignee="SINGAPORE TRADING PTE LTD"),
        ]
        results = check_entity_alignment(docs)
        consignee_results = [r for r in results if r.check_id == "E-consignee"]
        # normalised names agree: not flagged as inconsistent; the agreement itself is now reported as a PASS
        assert [r.severity for r in consignee_results] == ["PASS"]
        assert len(consignee_results[0].evidence) == 2

    def test_document_number_excluded_from_alignment(self):
        from app.domain.schemas import FieldRef
        doc1 = make_packing()
        doc1.document_number = FieldRef(value="INV-001", confidence=0.9)
        doc2 = make_bol()
        doc2.document_number = FieldRef(value="BL-8941", confidence=0.9)
        results = check_entity_alignment([doc1, doc2])
        docnum_results = [r for r in results if r.check_id == "E-docnum"]
        assert len(docnum_results) == 0

    def test_material_consignee_mismatch(self):
        docs = [make_packing(consignee="ACME CORP"), make_bol(consignee="XYZ CORP")]
        results = check_entity_alignment(docs)
        consignee_result = next((r for r in results if r.check_id == "E-consignee"), None)
        assert consignee_result is not None
        assert consignee_result.severity == "MATERIAL"


# ---------------------------------------------------------------------------
# Roll-up
# ---------------------------------------------------------------------------


class TestRollUp:
    def test_compliant_when_all_pass(self):
        from app.services.calculation import CheckResult
        results = [
            CheckResult(check_id="W-001", severity="PASS", message="ok"),
            CheckResult(check_id="H-002", severity="PASS", message="ok"),
        ]
        assert _roll_up(results) == "COMPLIANT_FOR_SUBMISSION"

    def test_specialist_when_only_warn(self):
        from app.services.calculation import CheckResult
        results = [CheckResult(check_id="W-001", severity="WARN", message="missing data")]
        assert _roll_up(results) == "SPECIALIST_REVIEW_REQUIRED"

    def test_material_wins_over_warn(self):
        from app.services.calculation import CheckResult
        results = [
            CheckResult(check_id="W-001", severity="WARN", message="missing data"),
            CheckResult(check_id="H-002", severity="MATERIAL", message="hs mismatch"),
        ]
        assert _roll_up(results) == "MATERIAL_CONTRADICTION"

    def test_empty_is_compliant(self):
        assert _roll_up([]) == "COMPLIANT_FOR_SUBMISSION"


# ---------------------------------------------------------------------------
# Async run entry point
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_packing_and_bol():
    """Full pipeline run through the calculation stage."""
    from app.services import calculation

    packing = make_packing(net=14000.0, tare=280.0)
    bol = make_bol(gross=14280.0)
    ctx = {
        "extracted": [packing, bol],
    }
    result_ctx = await calculation.run(ctx)
    assert "checks" in result_ctx
    assert "math_status" in result_ctx
    assert result_ctx["math_status"] == "COMPLIANT_FOR_SUBMISSION"
