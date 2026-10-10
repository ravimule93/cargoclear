"""Schema additions for the unit layer: QuantityRef (value + printed unit) and CheckResult.assumptions."""

from __future__ import annotations

import pytest

from app.domain import schemas
from app.domain.schemas import BBox, CheckResult, ExtractedDocument, FieldRef, LineItem
from app.services import confidence

WEIGHT_HEADER_FIELDS = ("total_net_weight_kg", "total_gross_weight_kg", "tare_weight_kg")
WEIGHT_LINE_FIELDS = ("net_weight_kg", "gross_weight_kg")


def _fieldref(value, conf=0.98) -> FieldRef:
    return FieldRef(value=value, confidence=conf, bbox=BBox(page=1, ymin=0, xmin=0, ymax=10, xmax=10))


def _line(**overrides) -> LineItem:
    base = dict(
        description=_fieldref("pipes"), quantity=_fieldref("1"), net_weight_kg=_fieldref(1.0),
        gross_weight_kg=_fieldref(1.0), hs_code_declared=_fieldref("73041900"),
    )
    return LineItem(**{**base, **overrides})


def test_quantity_ref_is_a_field_ref_with_an_optional_unit() -> None:
    q = schemas.QuantityRef(value="14,280", confidence=0.9, unit="KGS")
    assert isinstance(q, FieldRef)
    assert q.unit == "KGS"
    assert q.value == "14,280"  # kept exactly as printed
    assert schemas.QuantityRef(value=1.0, confidence=0.9).unit is None
    assert "never converted" in schemas.QuantityRef.model_fields["unit"].description


@pytest.mark.parametrize("name", WEIGHT_HEADER_FIELDS)
def test_header_weight_fields_hold_quantity_refs(name: str) -> None:
    doc = ExtractedDocument(
        document_id="d", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        **{name: schemas.QuantityRef(value=14000.0, confidence=0.9, unit="MT")},
    )
    ref = getattr(doc, name)
    assert isinstance(ref, schemas.QuantityRef)
    assert ref.unit == "MT"
    assert doc.model_dump()[name]["unit"] == "MT"


@pytest.mark.parametrize("name", WEIGHT_LINE_FIELDS)
def test_line_item_weight_fields_hold_quantity_refs(name: str) -> None:
    item = _line(**{name: schemas.QuantityRef(value=5.0, confidence=0.9, unit="LBS")})
    ref = getattr(item, name)
    assert isinstance(ref, schemas.QuantityRef)
    assert ref.unit == "LBS"


@pytest.mark.parametrize("name", WEIGHT_HEADER_FIELDS)
def test_plain_field_refs_are_still_accepted_for_weights_with_no_unit(name: str) -> None:
    """Existing callers (and tests) build weights with FieldRef; they become QuantityRef with unit=None."""
    doc = ExtractedDocument(
        document_id="d", doc_type="PACKING_LIST", doc_type_confidence=0.9, **{name: _fieldref(14000.0)}
    )
    ref = getattr(doc, name)
    assert isinstance(ref, schemas.QuantityRef)
    assert ref.unit is None
    assert ref.value == 14000.0
    assert ref.bbox is not None and ref.confidence == 0.98  # nothing else is lost in the conversion


def test_plain_field_refs_are_accepted_for_line_item_weights() -> None:
    item = _line()
    assert isinstance(item.net_weight_kg, schemas.QuantityRef)
    assert item.net_weight_kg.unit is None


def test_non_weight_fields_never_become_quantity_refs() -> None:
    """Text fields are TextRef (see test_text_ref.py), numeric fields stay plain FieldRef; neither carries a unit."""
    doc = ExtractedDocument(
        document_id="d", doc_type="PACKING_LIST", doc_type_confidence=0.9,
        consignee=_fieldref("ACME"), invoice_value=_fieldref(84000.0),
    )
    assert type(doc.consignee) is schemas.TextRef
    assert type(doc.invoice_value) is FieldRef
    assert type(_line().hs_code_declared) is schemas.TextRef
    assert not any(isinstance(r, schemas.QuantityRef) for r in (doc.consignee, doc.invoice_value))


def test_weight_field_descriptions_tell_the_model_not_to_convert() -> None:
    descriptions = [ExtractedDocument.model_fields[n].description for n in WEIGHT_HEADER_FIELDS]
    descriptions += [LineItem.model_fields[n].description for n in WEIGHT_LINE_FIELDS]
    for description in descriptions:
        assert description is not None
        assert "as printed" in description
        assert "unit goes in `unit`" in description
        assert "do NOT convert to kg" in description


def test_unit_is_in_the_json_schema_of_every_weight_field() -> None:
    schema = ExtractedDocument.model_json_schema()
    defs = schema["$defs"]
    assert "unit" in defs["QuantityRef"]["properties"]
    for name in WEIGHT_HEADER_FIELDS:
        assert "QuantityRef" in str(schema["properties"][name])
    for name in WEIGHT_LINE_FIELDS:
        assert "QuantityRef" in str(defs["LineItem"]["properties"][name])


def test_check_result_carries_assumptions() -> None:
    plain = CheckResult(check_id="W-001", severity="PASS", message="ok")
    assert plain.assumptions == []
    assert plain.model_dump()["assumptions"] == []

    flagged = CheckResult(check_id="W-001", severity="WARN", message="m", assumptions=["no unit stated; assumed kg"])
    assert flagged.assumptions == ["no unit stated; assumed kg"]
    assert CheckResult(**flagged.model_dump()).assumptions == flagged.assumptions

    # the default list is not shared between instances
    plain.assumptions.append("x")
    assert CheckResult(check_id="W-002", severity="PASS", message="ok").assumptions == []


# ---------------------------------------------------------------------------
# C3: confidence routing still sees QuantityRef confidences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confidence_routing_collects_confidence_from_quantity_refs() -> None:
    """A low-confidence weight must pull the minimum down even though it is a QuantityRef (FieldRef subclass)."""
    doc = ExtractedDocument(
        document_id="d", doc_type="PACKING_LIST", doc_type_confidence=0.99,
        consignee=_fieldref("ACME", 0.99),
        total_net_weight_kg=schemas.QuantityRef(value=14000.0, confidence=0.40, unit="KGS"),
        line_items=[_line(net_weight_kg=schemas.QuantityRef(value=1.0, confidence=0.80, unit="KGS"))],
    )

    ctx = await confidence.route({"extracted": [doc], "math_status": "COMPLIANT_FOR_SUBMISSION"})

    assert ctx["confidence"]["min_field_confidence"] == 0.40
    assert ctx["confidence"]["action"] == "MANUAL_ENTRY"
    assert ctx["force_status"] == "SPECIALIST_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_confidence_routing_collects_line_item_quantity_refs() -> None:
    doc = ExtractedDocument(
        document_id="d", doc_type="PACKING_LIST", doc_type_confidence=0.99,
        line_items=[_line(
            description=_fieldref("pipes", 0.99), quantity=_fieldref("1", 0.99), hs_code_declared=_fieldref("1", 0.99),
            net_weight_kg=schemas.QuantityRef(value=1.0, confidence=0.70, unit="KGS"),
            gross_weight_kg=schemas.QuantityRef(value=1.0, confidence=0.99, unit="KGS"),
        )],
    )

    ctx = await confidence.route({"extracted": [doc]})

    assert ctx["confidence"]["min_field_confidence"] == 0.70
    assert ctx["confidence"]["action"] == "INTERACTIVE_REVIEW"
