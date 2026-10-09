"""Deterministic math engine — weight parity + entity alignment + HS consistency.

This service is PURE Python with NO I/O and NO LLM calls.
It receives the structured extraction output and applies deterministic rules.

Math rules (v4.0 §3.1):
  Σ net_weight_k (PackingList) + tare ≟ gross_weight (BillOfLading)
  Tolerance: abs(delta) ≤ max(0.5% × gross, 5 kg)
  Missing tare: use 2% × net as industry default.

Entity rules (v4.0 §3.2):
  consignee, consignor, vessel_or_flight, document_number must be consistent
  across all documents in the bundle.

This module has a ≥95% unit test coverage requirement (see §11 of the tech plan).
"""

from __future__ import annotations


from app.domain.schemas import ExtractedDocument, CheckResult

# ---------------------------------------------------------------------------
# Constants (from v4.0 §3.1)
# ---------------------------------------------------------------------------

REL_TOL: float = 0.005      # 0.5% of gross weight
ABS_TOL: float = 5.0        # 5 kg minimum tolerance
DEFAULT_TARE_RATIO: float = 0.02   # 2% of net weight when tare not declared


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tolerance(gross_kg: float) -> float:
    """Return the allowed weight delta for a given gross weight."""
    return max(REL_TOL * gross_kg, ABS_TOL)


def _float_or_none(field_ref) -> float | None:  # type: ignore[no-untyped-def]
    """Extract float value from a FieldRef, returning None if absent."""
    if field_ref is None:
        return None
    v = field_ref.value
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_weight_parity(
    packing: ExtractedDocument,
    bol: ExtractedDocument,
) -> CheckResult:
    """Verify: net + tare (Packing List) ≈ gross (Bill of Lading).

    Returns PASS, WARN (missing data), or MATERIAL (exceeds tolerance).
    """
    net = _float_or_none(packing.total_net_weight_kg)
    tare = _float_or_none(packing.tare_weight_kg)
    gross = _float_or_none(bol.total_gross_weight_kg)

    evidence = [
        {"doc": packing.document_id, "field": "total_net_weight_kg"},
        {"doc": bol.document_id, "field": "total_gross_weight_kg"},
    ]

    if net is None or gross is None:
        return CheckResult(
            check_id="W-001",
            severity="WARN",
            message="Weight parity not evaluable: net or gross weight is missing.",
            evidence=evidence,
        )

    if tare is None:
        tare = DEFAULT_TARE_RATIO * net

    expected = net + tare
    delta = abs(expected - gross)
    tol = _tolerance(gross)

    if delta <= tol:
        return CheckResult(
            check_id="W-001",
            severity="PASS",
            message=(
                f"Net+tare ({expected:.1f} kg) matches BoL gross ({gross:.1f} kg) "
                f"within tolerance (±{tol:.1f} kg)."
            ),
            delta=delta,
            tolerance=tol,
            evidence=evidence,
        )

    return CheckResult(
        check_id="W-001",
        severity="MATERIAL",
        message=(
            f"Weight mismatch of {delta:.1f} kg exceeds ±{tol:.1f} kg tolerance. "
            f"Expected ≈{expected:.1f} kg, BoL declares {gross:.1f} kg."
        ),
        delta=delta,
        tolerance=tol,
        evidence=evidence,
    )


def check_hs_consistency(
    invoice: ExtractedDocument,
    packing: ExtractedDocument,
) -> CheckResult:
    """8-digit declared HS codes must be consistent across invoice and packing list."""
    invoice_codes = {
        i.hs_code_declared.value
        for i in invoice.line_items
        if i.hs_code_declared and i.hs_code_declared.value
    }
    packing_codes = {
        i.hs_code_declared.value
        for i in packing.line_items
        if i.hs_code_declared and i.hs_code_declared.value
    }

    if not invoice_codes or not packing_codes:
        return CheckResult(
            check_id="H-002",
            severity="WARN",
            message="HS code absent on one or more documents — cannot verify consistency.",
        )

    if invoice_codes == packing_codes:
        return CheckResult(
            check_id="H-002",
            severity="PASS",
            message=f"Declared HS codes are consistent: {sorted(invoice_codes)}.",
        )

    return CheckResult(
        check_id="H-002",
        severity="MATERIAL",
        message=(
            f"HS code divergence detected. "
            f"Invoice: {sorted(invoice_codes)}, Packing List: {sorted(packing_codes)}."
        ),
    )


def check_entity_alignment(docs: list[ExtractedDocument]) -> list[CheckResult]:
    """Consignee, consignor, vessel, and document_number must be consistent across all docs."""
    results: list[CheckResult] = []

    for attr, check_id in (
        ("consignee", "E-consignee"),
        ("consignor", "E-consignor"),
        ("vessel_or_flight", "E-vessel"),
        ("document_number", "E-docnum"),
    ):
        vals: set[str] = set()
        for doc in docs:
            field_ref = getattr(doc, attr, None)
            if field_ref and field_ref.value:
                vals.add(str(field_ref.value).strip().upper())

        if len(vals) > 1:
            results.append(
                CheckResult(
                    check_id=check_id,
                    severity="MATERIAL",
                    message=f"Inconsistent {attr} across documents: {sorted(vals)}.",
                )
            )

    return results


# ---------------------------------------------------------------------------
# Roll-up to status
# ---------------------------------------------------------------------------


def _roll_up(results: list[CheckResult]) -> str:
    """Convert a list of check results to a single status string."""
    if any(r.severity == "MATERIAL" for r in results):
        return "MATERIAL_CONTRADICTION"
    if any(r.severity == "WARN" for r in results):
        return "SPECIALIST_REVIEW_REQUIRED"
    return "COMPLIANT_FOR_SUBMISSION"


# ---------------------------------------------------------------------------
# Pipeline stage entry point
# ---------------------------------------------------------------------------


async def run(ctx: dict) -> dict:
    """Deterministic check engine — pipeline stage entry point.

    Reads:  ctx["extracted"]  (list[ExtractedDocument])
    Writes: ctx["checks"]     (list[dict] — serialised CheckResults)
            ctx["math_status"] (str — one of the 4 status strings)
    """
    docs: list[ExtractedDocument] = ctx.get("extracted", [])
    by_type: dict[str, ExtractedDocument] = {d.doc_type: d for d in docs}
    results: list[CheckResult] = []

    # Weight parity: Packing List vs Bill of Lading
    if "PACKING_LIST" in by_type and "BILL_OF_LADING" in by_type:
        results.append(check_weight_parity(by_type["PACKING_LIST"], by_type["BILL_OF_LADING"]))

    # HS code consistency: Commercial Invoice vs Packing List
    if "COMMERCIAL_INVOICE" in by_type and "PACKING_LIST" in by_type:
        results.append(
            check_hs_consistency(by_type["COMMERCIAL_INVOICE"], by_type["PACKING_LIST"])
        )

    # Entity alignment across all documents
    results.extend(check_entity_alignment(docs))

    ctx["checks"] = [r.model_dump() for r in results]
    ctx["math_status"] = _roll_up(results)
    return ctx
