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
from app.domain.schemas import ExtractedDocument, FieldRef, LineItem, BBox
from app.services.calculation import (
    check_weight_parity,
    check_hs_consistency,
    check_entity_alignment,
    _roll_up,
    _tolerance,
    DEFAULT_TARE_RATIO,
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


def make_packing(net=14000.0, tare=None, hs="73041900", consignee="ACME"):
    return ExtractedDocument(
        document_id="pl-001",
        doc_type="PACKING_LIST",
        doc_type_confidence=0.99,
        total_net_weight_kg=ref(net),
        tare_weight_kg=ref(tare) if tare is not None else None,
        consignee=ref(consignee),
        line_items=[
            LineItem(
                description=ref("Steel pipes"),
                quantity=ref("100 PCS"),
                net_weight_kg=ref(net),
                gross_weight_kg=ref(net + (tare or DEFAULT_TARE_RATIO * net)),
                hs_code_declared=ref(hs),
            )
        ],
    )


def make_bol(gross=14280.0, consignee="ACME"):
    return ExtractedDocument(
        document_id="bol-001",
        doc_type="BILL_OF_LADING",
        doc_type_confidence=0.99,
        total_gross_weight_kg=ref(gross),
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
    def test_pass_within_tolerance(self):
        """net + default_tare ≈ gross → PASS."""
        net = 14000.0
        gross = net * (1 + DEFAULT_TARE_RATIO)  # exact
        packing = make_packing(net=net)
        bol = make_bol(gross=gross)
        result = check_weight_parity(packing, bol)
        assert result.severity == "PASS"
        assert result.check_id == "W-001"

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
        net = 14000.0
        gross = 14280.0  # expected ≈ 14000 + 280 (2% tare) = 14280
        gross_wrong = 14460.0  # delta = 180 kg, tol = max(0.5% × 14460, 5) ≈ 72.3 kg
        packing = make_packing(net=net)
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
        """Delta exactly at tolerance boundary → PASS (≤ tol)."""
        net = 14000.0
        tol = _tolerance(14280.0)
        expected = net + DEFAULT_TARE_RATIO * net
        gross_boundary = expected + tol  # delta == tol exactly → PASS
        packing = make_packing(net=net)
        bol = make_bol(gross=gross_boundary)
        result = check_weight_parity(packing, bol)
        assert result.severity == "PASS"

    def test_boundary_just_over_tolerance(self):
        """Delta just above tolerance → MATERIAL."""
        net = 14000.0
        tol = _tolerance(14280.0)
        expected = net + DEFAULT_TARE_RATIO * net
        gross_over = expected + tol + 0.01
        packing = make_packing(net=net)
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

    def test_material_consignee_mismatch(self):
        docs = [make_packing(consignee="ACME LTD"), make_bol(consignee="ACME PTE LTD")]
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
            CheckResult("W-001", "PASS", "ok"),
            CheckResult("H-002", "PASS", "ok"),
        ]
        assert _roll_up(results) == "COMPLIANT_FOR_SUBMISSION"

    def test_specialist_when_only_warn(self):
        from app.services.calculation import CheckResult
        results = [CheckResult("W-001", "WARN", "missing data")]
        assert _roll_up(results) == "SPECIALIST_REVIEW_REQUIRED"

    def test_material_wins_over_warn(self):
        from app.services.calculation import CheckResult
        results = [
            CheckResult("W-001", "WARN", "missing data"),
            CheckResult("H-002", "MATERIAL", "hs mismatch"),
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
