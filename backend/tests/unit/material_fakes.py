"""Builders for the Phase 1 engine tests: certificates with chemistry, packing lists with heats, invoices with prices."""

from __future__ import annotations

from typing import Any

from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LabResult, LineItem, QuantityRef

BOX = BBox(page=1, ymin=100, xmin=100, ymax=130, xmax=350)


def ref(value: Any, conf: float = 0.98, bbox: BBox | None = BOX) -> FieldRef:
    return FieldRef(value=value, confidence=conf, bbox=bbox)


def lab(value: Any, parameter: str, heat: str | None = "H1", unit: str | None = "%", conf: float = 0.97) -> LabResult:
    return LabResult(value=value, confidence=conf, bbox=BOX, parameter=parameter, heat_number=heat, unit=unit)


# a heat that is plainly non-alloy and inside API 5L PSL2 Grade B
GOOD_HEAT = {"C": "0.18", "Mn": "0.95", "Si": "0.25", "P": "0.015", "S": "0.005", "Cr": "0.08", "Ni": "0.05",
             "Mo": "0.02", "Cu": "0.10", "V": "0.01", "Nb": "0.01", "Ti": "0.01", "YS": "310", "UTS": "450"}


def heat_rows(heat: str, values: dict[str, str], *, unit: str | None = "%", conf: float = 0.97) -> list[LabResult]:
    return [lab(v, p, heat, "MPa" if p in ("YS", "UTS") else unit, conf) for p, v in values.items()]


def certificate(
    heats: dict[str, dict[str, str]] | None = None,
    *,
    spec: str | None = "API 5L PSL2 GR.B",
    document_id: str = "mtc-1",
    unit: str | None = "%",
    heat_cells: list[str] | None = None,
    hs: str | None = None,
) -> ExtractedDocument:
    heats = {"H1": GOOD_HEAT} if heats is None else heats
    rows = [row for heat, values in heats.items() for row in heat_rows(heat, values, unit=unit)]
    return ExtractedDocument(
        document_id=document_id, doc_type="MILL_TEST_CERTIFICATE", doc_type_confidence=0.99,
        specification=ref(spec) if spec else None,
        heat_numbers=[ref(h) for h in (heat_cells if heat_cells is not None else heats)],
        test_results=rows, hs_code_header=ref(hs) if hs else None,
    )


def line(
    hs: str = "73041900", *, desc: str = "Seamless pipes", qty: Any = "120 LENGTHS", price: Any = 700.0, total: Any = 84000.0,
    currency: str | None = "USD", basis: str | None = None, net: Any = None,
) -> LineItem:
    return LineItem(
        description=ref(desc), quantity=ref(qty), net_weight_kg=QuantityRef(value=net if net is not None else 14000.0, unit="KGS", confidence=0.98),
        gross_weight_kg=QuantityRef(value=14280.0, unit="KGS", confidence=0.98), hs_code_declared=ref(hs),
        unit_price=ref(price) if price is not None else None, total_value=ref(total) if total is not None else None,
        currency=ref(currency) if currency else None, unit_price_basis=ref(basis) if basis else None,
    )


def invoice(
    *lines: LineItem, value: Any = 84000.0, currency: str | None = "USD", incoterm: str | None = None,
    origin: str | None = None, freight: Any = None, freight_currency: str | None = None, document_id: str = "inv-1",
    insurance: Any = None,
) -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id, doc_type="COMMERCIAL_INVOICE", doc_type_confidence=0.99,
        invoice_value=ref(value) if value is not None else None, invoice_currency=ref(currency) if currency else None,
        incoterm=ref(incoterm) if incoterm else None, country_of_origin=ref(origin) if origin else None,
        freight_amount=ref(freight) if freight is not None else None, freight_currency=ref(freight_currency) if freight_currency else None,
        insurance_amount=ref(insurance) if insurance is not None else None,
        line_items=list(lines) or [line()],
    )


def packing(heats: list[str] | None = None, *, origin: str | None = None, hs: str = "73041900", document_id: str = "pl-1") -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id, doc_type="PACKING_LIST", doc_type_confidence=0.99,
        heat_numbers=[ref(h) for h in (heats or [])], country_of_origin=ref(origin) if origin else None, line_items=[line(hs)],
    )


def bill_of_lading(freight: Any = None, currency: str | None = "USD", document_id: str = "bl-1") -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id, doc_type="BILL_OF_LADING", doc_type_confidence=0.99,
        freight_amount=ref(freight) if freight is not None else None, freight_currency=ref(currency) if currency else None,
    )


def severity(results: list, check_id: str) -> str | None:
    return next((r.severity for r in results if r.check_id == check_id), None)


def result(results: list, check_id: str):
    return next((r for r in results if r.check_id == check_id), None)
