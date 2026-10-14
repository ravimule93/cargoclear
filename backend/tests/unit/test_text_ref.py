"""TextRef: text fields hold strings. A model that emits 73041900 as a number still yields "73041900"."""

from __future__ import annotations

import pytest

from app.domain import schemas
from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LineItem, QuantityRef

HEADER_TEXT_FIELDS = (
    "document_number", "consignee", "consignor", "vessel_or_flight", "port_of_loading", "port_of_discharge",
    "shipment_date", "invoice_currency", "hs_code_header",
)
LINE_TEXT_FIELDS = ("description", "quantity", "hs_code_declared", "currency")
NUMERIC_HEADER_FIELDS = ("invoice_value", "package_count")
NUMERIC_LINE_FIELDS = ("unit_price", "total_value")

BOX = BBox(page=1, ymin=1, xmin=2, ymax=3, xmax=4)


def plain(value, conf=0.9) -> FieldRef:
    return FieldRef(value=value, confidence=conf, bbox=BOX)


def line(**overrides) -> LineItem:
    base = dict(description=plain("pipes"), quantity=plain("1"), net_weight_kg=plain(1.0), gross_weight_kg=plain(1.0),
                hs_code_declared=plain("73041900"))
    return LineItem(**{**base, **overrides})


def doc(**fields) -> ExtractedDocument:
    return ExtractedDocument(document_id="d", doc_type="COMMERCIAL_INVOICE", doc_type_confidence=0.9, **fields)


# ---------------------------------------------------------------------------
# coercion
# ---------------------------------------------------------------------------


def test_text_ref_is_a_field_ref_whose_value_is_text() -> None:
    ref = schemas.TextRef(value="ACME", confidence=0.9)
    assert isinstance(ref, FieldRef)
    assert ref.value == "ACME"
    assert schemas.TextRef(value=None, confidence=0.0).value is None


@pytest.mark.parametrize(
    ("raw", "text"),
    [(73041900, "73041900"), (73041900.0, "73041900"), (14.5, "14.5"), (0, "0"), ("73041900", "73041900"),
     ("7304.19.00", "7304.19.00"), (" keep as printed ", " keep as printed ")],
)
def test_numbers_become_text_and_text_is_left_alone(raw, text) -> None:
    assert schemas.TextRef(value=raw, confidence=0.9).value == text


def test_int_hs_code_becomes_text_on_a_line_item() -> None:
    assert line(hs_code_declared=plain(73041900)).hs_code_declared.value == "73041900"


def test_float_hs_code_becomes_text_without_the_point_zero() -> None:
    assert line(hs_code_declared=plain(73041900.0)).hs_code_declared.value == "73041900"


def test_int_hs_code_becomes_text_in_the_header() -> None:
    assert doc(hs_code_header=plain(73041900)).hs_code_header.value == "73041900"


def test_none_stays_none() -> None:
    assert doc(consignee=plain(None)).consignee.value is None


# ---------------------------------------------------------------------------
# plain FieldRef input is accepted for every TextRef field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", HEADER_TEXT_FIELDS)
def test_every_header_text_field_accepts_a_plain_field_ref(name: str) -> None:
    d = doc(**{name: plain(12345)})
    ref = getattr(d, name)
    assert isinstance(ref, schemas.TextRef)
    assert ref.value == "12345"
    assert ref.confidence == 0.9
    assert ref.bbox == BOX  # nothing but the value type changes


@pytest.mark.parametrize("name", LINE_TEXT_FIELDS)
def test_every_line_item_text_field_accepts_a_plain_field_ref(name: str) -> None:
    item = line(**{name: plain(12345)})
    ref = getattr(item, name)
    assert isinstance(ref, schemas.TextRef)
    assert ref.value == "12345"
    assert ref.bbox == BOX


@pytest.mark.parametrize("name", HEADER_TEXT_FIELDS)
def test_header_text_fields_accept_a_text_ref_directly(name: str) -> None:
    d = doc(**{name: schemas.TextRef(value="x", confidence=0.5)})
    assert type(getattr(d, name)) is schemas.TextRef


def test_every_text_field_is_optional_where_it_was_optional() -> None:
    d = doc()
    assert all(getattr(d, name) is None for name in HEADER_TEXT_FIELDS)
    assert line().currency is None


# ---------------------------------------------------------------------------
# numeric fields are untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", NUMERIC_HEADER_FIELDS)
def test_numeric_header_fields_stay_plain_field_refs_and_keep_numbers(name: str) -> None:
    d = doc(**{name: plain(84000.0)})
    ref = getattr(d, name)
    assert type(ref) is FieldRef
    assert ref.value == 84000.0


@pytest.mark.parametrize("name", NUMERIC_LINE_FIELDS)
def test_numeric_line_fields_stay_plain_field_refs_and_keep_numbers(name: str) -> None:
    item = line(**{name: plain(700.0)})
    ref = getattr(item, name)
    assert type(ref) is FieldRef
    assert ref.value == 700.0


def test_weights_are_still_quantity_refs() -> None:
    assert isinstance(line().net_weight_kg, QuantityRef)


# ---------------------------------------------------------------------------
# the JSON shape of ExtractedDocument.model_dump() is unchanged
# ---------------------------------------------------------------------------


def test_model_dump_keys_are_unchanged() -> None:
    d = doc(consignee=plain("ACME"), hs_code_header=plain("73041900"), invoice_value=plain(1.0),
            total_net_weight_kg=QuantityRef(value=1.0, unit="KGS", confidence=0.9), line_items=[line()])
    dumped = d.model_dump()

    assert set(dumped) == {
        "document_id", "doc_type", "doc_type_confidence", "document_number", "consignee", "consignor",
        "vessel_or_flight", "port_of_loading", "port_of_discharge", "shipment_date", "invoice_value",
        "invoice_currency", "total_net_weight_kg", "total_gross_weight_kg", "tare_weight_kg", "package_count",
        "hs_code_header", "line_items",
        # terms of sale and valuation inputs, and the material evidence of a certificate (all optional / empty by default)
        "incoterm", "country_of_origin", "freight_amount", "freight_currency", "insurance_amount", "insurance_currency",
        "specification", "heat_numbers", "test_results",
    }
    assert set(dumped["consignee"]) == {"value", "confidence", "bbox"}  # a TextRef dumps like a FieldRef
    assert set(dumped["invoice_value"]) == {"value", "confidence", "bbox"}
    assert set(dumped["total_net_weight_kg"]) == {"value", "confidence", "bbox", "unit"}
    assert set(dumped["line_items"][0]) == {
        "description", "quantity", "net_weight_kg", "gross_weight_kg", "hs_code_declared",
        "unit_price", "total_value", "currency", "unit_price_basis",
    }


def test_a_dumped_document_validates_back_to_the_same_values() -> None:
    d = doc(hs_code_header=plain(73041900), line_items=[line(hs_code_declared=plain("7304.19.00"))])
    again = ExtractedDocument.model_validate(d.model_dump())
    assert again.hs_code_header.value == "73041900"
    assert again.line_items[0].hs_code_declared.value == "7304.19.00"
    assert again == d


def test_json_schema_types_text_values_as_strings_and_numeric_values_as_numbers() -> None:
    schema = ExtractedDocument.model_json_schema()
    defs = schema["$defs"]
    text_value = defs["TextRef"]["properties"]["value"]
    assert {opt.get("type") for opt in text_value["anyOf"]} == {"string", "null"}
    numeric_value = defs["FieldRef"]["properties"]["value"]
    assert {opt.get("type") for opt in numeric_value["anyOf"]} >= {"number", "integer", "string"}


def test_an_extraction_stored_before_the_material_and_sale_term_fields_still_loads() -> None:
    """Iterations are immutable and extractions are persisted per iteration: old JSON has none of the new keys."""
    legacy = {
        "document_id": "doc-old",
        "doc_type": "COMMERCIAL_INVOICE",
        "doc_type_confidence": 0.99,
        "consignee": {"value": "ACME", "confidence": 0.9, "bbox": None},
        "line_items": [
            {
                "description": {"value": "pipes", "confidence": 0.9, "bbox": None},
                "quantity": {"value": "1", "confidence": 0.9, "bbox": None},
                "net_weight_kg": {"value": 1.0, "confidence": 0.9, "bbox": None, "unit": "KGS"},
                "gross_weight_kg": {"value": 1.0, "confidence": 0.9, "bbox": None, "unit": "KGS"},
                "hs_code_declared": {"value": "73041900", "confidence": 0.9, "bbox": None},
            }
        ],
    }

    loaded = ExtractedDocument.model_validate(legacy)

    assert loaded.incoterm is None and loaded.specification is None
    assert loaded.heat_numbers == [] and loaded.test_results == []
    assert loaded.line_items[0].unit_price_basis is None


def test_a_lab_result_row_reads_numbers_as_printed_text() -> None:
    """A model that answers a chemistry value as a JSON number still gives text ("0.18"), like every other text field."""
    from app.domain.schemas import LabResult

    row = LabResult.model_validate({"value": 0.18, "confidence": 0.97, "parameter": "C", "heat_number": "H-1", "unit": "%"})

    assert row.value == "0.18" and row.parameter == "C" and row.heat_number == "H-1" and row.unit == "%"
    assert LabResult.model_validate({"value": "<0.005", "confidence": 0.9, "parameter": "B"}).value == "<0.005"
