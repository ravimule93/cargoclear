"""The live extraction path reads a certificate's table: heats, test results, specification, sale terms.

Gemini's answer is untrusted input. A bad box or an out-of-range confidence on ONE table cell must not reject the whole
certificate; a number returned as a JSON number must still be text; a row without a parameter is a schema failure that is
retried, like any other unusable answer.
"""

from __future__ import annotations

import pytest

from app.agents import extraction
from tests.unit.extraction_fakes import good_doc, response

BOX = {"page": 1, "ymin": 520, "xmin": 145, "ymax": 550, "xmax": 197}


def cert_answer(**extra):
    answer = good_doc("MILL_TEST_CERTIFICATE")
    answer.update(
        specification={"value": "API 5L PSL2 GR.B", "confidence": 0.98, "bbox": BOX},
        heat_numbers=[{"value": "H-24-0881", "confidence": 0.99, "bbox": BOX}],
        test_results=[
            {"value": "0.18", "confidence": 0.97, "bbox": BOX, "parameter": "C", "heat_number": "H-24-0881", "unit": "%"},
            {"value": 0.95, "confidence": 0.97, "bbox": BOX, "parameter": "Mn", "heat_number": "H-24-0881", "unit": "%"},
            {"value": "<0.005", "confidence": 0.9, "bbox": None, "parameter": "B", "heat_number": "H-24-0881", "unit": "%"},
        ],
        incoterm={"value": "FOB TIANJIN", "confidence": 0.97, "bbox": BOX},
    )
    answer.update(extra)
    return answer


def read(answer, pages=1):
    return extraction._read_response(response(answer), "doc-1", pages)


def test_a_certificate_table_is_read_with_its_heats_values_and_units() -> None:
    document, warnings = read(cert_answer())

    assert document.specification.value == "API 5L PSL2 GR.B" and document.incoterm.value == "FOB TIANJIN"
    assert [h.value for h in document.heat_numbers] == ["H-24-0881"]
    assert [(r.parameter, r.value, r.unit, r.heat_number) for r in document.test_results] == [
        ("C", "0.18", "%", "H-24-0881"), ("Mn", "0.95", "%", "H-24-0881"), ("B", "<0.005", "%", "H-24-0881"),
    ]
    assert document.test_results[0].bbox.xmin == 145 and warnings == []


def test_a_number_the_model_returns_as_a_json_number_is_still_text() -> None:
    document, _ = read(cert_answer())

    assert document.test_results[1].value == "0.95" and isinstance(document.test_results[1].value, str)


def test_a_bad_box_or_confidence_on_one_cell_costs_that_cell_its_box_not_the_certificate() -> None:
    answer = cert_answer()
    answer["test_results"][0]["bbox"] = {**BOX, "ymax": 100}                 # inverted: ymax <= ymin
    answer["test_results"][1]["confidence"] = 1.7                            # out of range
    answer["heat_numbers"][0]["bbox"] = {**BOX, "page": 9}                   # a page that was not sent

    document, warnings = read(answer, pages=1)

    assert document.test_results[0].bbox is None and document.test_results[0].value == "0.18"
    assert document.test_results[1].confidence == 1.0 and document.test_results[1].value == "0.95"
    assert document.heat_numbers[0].bbox is None and document.heat_numbers[0].value == "H-24-0881"
    paths = {w["path"] for w in warnings}
    assert {"test_results[0].bbox", "test_results[1].confidence", "heat_numbers[0].bbox"} <= paths


def test_a_row_without_a_parameter_is_a_schema_failure_that_is_retried() -> None:
    answer = cert_answer()
    del answer["test_results"][0]["parameter"]

    with pytest.raises(extraction._AttemptFailure) as caught:
        read(answer)

    assert caught.value.retryable and "test_results.0.parameter" in caught.value.summary


def test_an_answer_that_has_none_of_the_new_fields_is_unchanged() -> None:
    document, warnings = read(good_doc("COMMERCIAL_INVOICE"))

    assert document.heat_numbers == [] and document.test_results == [] and document.specification is None
    assert warnings == []


def test_the_response_schema_offered_to_gemini_describes_the_new_rows_flat() -> None:
    """No nested arrays (heats x elements would be one): a row carries its heat, parameter and unit."""
    from app.domain.schemas import ExtractedDocument

    schema = ExtractedDocument.model_json_schema()
    row = schema["$defs"]["LabResult"]

    assert {"value", "confidence", "bbox", "parameter", "heat_number", "unit"} <= set(row["properties"])
    assert row["required"] == ["confidence", "parameter"]
    assert schema["properties"]["test_results"]["items"] == {"$ref": "#/$defs/LabResult"}
    assert "items" not in row["properties"].get("heat_number", {}) and "items" not in row["properties"]["parameter"]
