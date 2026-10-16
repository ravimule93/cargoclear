"""Fix item 11: the declared type of an upload (T-001) and the script of the values read (L-001): services/document_identity.py, the
upload field, the record, the audit event and the assessment. No Gemini, no credentials."""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.schemas import ExtractedDocument, TextField
from app.gateway.errors import ValidationError
from app.services import calculation, document_identity
from app.services.document_identity import (
    DECLARABLE_TYPES,
    checks,
    letters_by_script,
    parse_declared_type,
    script_checks,
    type_checks,
)
from tests.helpers import api_client, case_c_pdf
from tests.unit.extraction_fakes import good_doc


def doc(document_id: str = "doc-1", doc_type: str = "COMMERCIAL_INVOICE", confidence: float = 0.97) -> ExtractedDocument:
    return ExtractedDocument.model_validate(good_doc(doc_type) | {"document_id": document_id, "doc_type_confidence": confidence})


def with_values(document_id: str, text: str, *, unit: str | None = None, doc_type: str = "COMMERCIAL_INVOICE") -> ExtractedDocument:
    """A document whose every printed value (and unit) is ``text``."""
    raw = good_doc(doc_type) | {"document_id": document_id}

    def put(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "value" and isinstance(child, str):
                    node[key] = text
                elif key == "unit" and isinstance(child, str):
                    node[key] = unit if unit is not None else text
                else:
                    put(child)
        elif isinstance(node, list):
            for child in node:
                put(child)

    put(raw)
    return ExtractedDocument.model_validate(raw)


def meta(document_id: str, declared: str | None = None, filename: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"document_id": document_id, "filename": filename or f"{document_id}.pdf"}
    if declared:
        record["declared_type"] = declared
    return record


# --- the field ---


@pytest.mark.parametrize(("given", "expected"), [
    (None, None), ("", None), ("   ", None),
    ("COMMERCIAL_INVOICE", "COMMERCIAL_INVOICE"), ("commercial_invoice", "COMMERCIAL_INVOICE"), (" Bill of Lading ", "BILL_OF_LADING"),
    ("packing-list", "PACKING_LIST"), ("Mill_Test  Certificate", "MILL_TEST_CERTIFICATE"), ("phytosanitary", "PHYTOSANITARY"),
])
def test_a_declared_type_is_normalised_and_an_empty_field_means_none(given, expected) -> None:
    assert parse_declared_type(given) == expected


@pytest.mark.parametrize("given", ["UNKNOWN", "invoice", "passport", "COMMERCIAL_INVOICE;", "x" * 500])
def test_a_name_that_is_not_one_of_the_six_types_is_refused_and_the_message_lists_them(given) -> None:
    with pytest.raises(ValidationError) as caught:
        parse_declared_type(given)
    assert caught.value.detail is not None and caught.value.detail["allowed"] == list(DECLARABLE_TYPES)
    assert len(caught.value.detail["declared_type"]) <= 64
    assert all(name in caught.value.message for name in DECLARABLE_TYPES)


# --- T-001 ---


def test_a_document_read_as_another_type_than_declared_is_flagged_with_both_names_and_the_confidence() -> None:
    [flag] = type_checks([meta("doc-1", "COMMERCIAL_INVOICE", "invoice.pdf")], [doc("doc-1", "BILL_OF_LADING", 0.99)])

    assert flag.check_id == "T-001-doc-1" and flag.severity == "WARN" and flag.focus_document == "doc-1"
    assert flag.message.startswith("invoice.pdf: uploaded as a Commercial Invoice, but the model read it as a Bill of Lading (confidence 99%).")
    assert "No other file was read as a Commercial Invoice, so one is still missing." in flag.message
    assert "correct the document type" in flag.message


def test_the_missing_sentence_is_left_out_when_another_file_was_read_as_the_declared_type() -> None:
    flags = type_checks(
        [meta("doc-1", "COMMERCIAL_INVOICE"), meta("doc-2")], [doc("doc-1", "BILL_OF_LADING"), doc("doc-2", "COMMERCIAL_INVOICE")]
    )

    assert len(flags) == 1 and "still missing" not in flags[0].message


def test_a_document_the_model_could_not_type_is_flagged_as_such() -> None:
    [flag] = type_checks([meta("doc-1", "PACKING_LIST")], [doc("doc-1", "UNKNOWN", 0.2)])

    assert "the model could not tell what it is (confidence 20%)" in flag.message


@pytest.mark.parametrize(("declared", "read"), [
    (None, "BILL_OF_LADING"),                                   # nothing declared: nothing to compare
    ("BILL_OF_LADING", "BILL_OF_LADING"),                       # the same
])
def test_no_finding_without_a_declared_type_or_when_it_matches(declared, read) -> None:
    assert type_checks([meta("doc-1", declared)], [doc("doc-1", read)]) == []


def test_a_document_that_was_not_extracted_is_not_flagged_and_each_mismatch_gets_its_own_id() -> None:
    flags = type_checks(
        [meta("doc-1", "PACKING_LIST"), meta("doc-2", "BILL_OF_LADING"), meta("doc-3", "PACKING_LIST")],
        [doc("doc-1", "COMMERCIAL_INVOICE"), doc("doc-2", "PACKING_LIST")],
    )

    assert [f.check_id for f in flags] == ["T-001-doc-1", "T-001-doc-2"]


# --- L-001 ---

CHINESE = "新加坡精密管道有限公司"


def test_a_document_whose_values_are_chinese_is_flagged_with_the_counts_and_the_reason() -> None:
    [flag] = script_checks([meta("doc-1", filename="发票.pdf")], [with_values("doc-1", CHINESE, unit="吨")])

    assert flag.check_id == "L-001-doc-1" and flag.severity == "WARN" and flag.focus_document == "doc-1"
    assert flag.message.startswith("发票.pdf: ") and "are not Latin script (mostly Chinese or Japanese ideographs)" in flag.message
    assert "no translation" in flag.message and "difference of language" in flag.message


def test_a_latin_document_is_not_flagged_and_neither_is_one_in_a_latin_script_that_is_not_english() -> None:
    assert script_checks([meta("doc-1")], [doc("doc-1")]) == []
    for text in ("Sociedad Anónima de Tuberías Ñandú", "Công ty trách nhiệm hữu hạn ống thép", "Société à responsabilité limitée Çelik"):
        assert script_checks([meta("doc-1")], [with_values("doc-1", text)]) == [], text


def test_fullwidth_latin_letters_count_as_latin() -> None:
    counts = letters_by_script(with_values("doc-1", "ＡＢＣＤＥＦ ＰＩＰＥ"))

    assert set(counts) == {"LATIN"}


def test_digits_punctuation_and_spaces_are_not_letters() -> None:
    counts = letters_by_script(with_values("doc-1", "1,234.50 - 2024/10/16 ()", unit="%"))

    assert sum(counts.values()) == 0
    assert script_checks([meta("doc-1")], [with_values("doc-1", "1,234.50 - 2024/10/16 ()")]) == []


def test_it_takes_more_than_half_of_the_letters_and_at_least_four_that_are_not_latin() -> None:
    def mix(latin: int, other: int) -> ExtractedDocument:  # one printed value, so the letters counted are exactly these
        return ExtractedDocument(
            document_id="doc-1", doc_type="COMMERCIAL_INVOICE", doc_type_confidence=0.9,
            consignee=TextField(value="a" * latin + "中" * other, confidence=0.9),
        )

    assert script_checks([meta("doc-1")], [mix(4, 4)]) == []       # exactly half: not most
    assert len(script_checks([meta("doc-1")], [mix(3, 4)])) == 1   # 4 of 7
    assert script_checks([meta("doc-1")], [mix(0, 3)]) == []       # most, but only three letters
    assert len(script_checks([meta("doc-1")], [mix(0, 4)])) == 1


@pytest.mark.parametrize(("text", "script"), [
    ("ООО Трубопрокат Москва", "Cyrillic"), ("شركة الأنابيب الفولاذية", "Arabic"), ("ฟอร์จ สตีล จำกัด", "Thai"),
    ("한국철강주식회사", "Korean"), ("भारत सीमलेस पाइप्स", "Devanagari"),
])
def test_the_script_is_named(text, script) -> None:
    [flag] = script_checks([meta("doc-1")], [with_values("doc-1", text)])

    assert f"(mostly {script})" in flag.message


def test_only_the_printed_values_are_read_not_the_type_the_ids_or_the_boxes() -> None:
    # the type name, ids and confidences are Latin text or numbers outside any value; a document whose values are Chinese stays Chinese
    counts = letters_by_script(with_values("doc-ENGLISH-ID", CHINESE, doc_type="BILL_OF_LADING"))

    assert counts["LATIN"] == 0 and counts["CJK"] > 0


def test_the_order_is_the_bundles_and_each_document_gets_its_own_id() -> None:
    flags = script_checks(
        [meta("doc-2"), meta("doc-1"), meta("doc-3")],
        [with_values("doc-1", CHINESE), doc("doc-3"), with_values("doc-2", CHINESE)],
    )

    assert [f.check_id for f in flags] == ["L-001-doc-2", "L-001-doc-1"]


def test_checks_lists_the_type_findings_first() -> None:
    both = checks([meta("doc-1", "PACKING_LIST")], [with_values("doc-1", CHINESE)])

    assert [c.check_id for c in both] == ["T-001-doc-1", "L-001-doc-1"]


# --- in the assessment ---


@pytest.mark.asyncio
async def test_the_findings_are_part_of_the_checks_and_keep_the_status_from_being_compliant() -> None:
    ctx: dict[str, Any] = {
        "extracted": [doc("doc-1", "BILL_OF_LADING")],
        "documents": [meta("doc-1", "COMMERCIAL_INVOICE")],
        "destination_country": "SG",
    }

    result = await calculation.run(ctx)

    flagged = [c for c in result["checks"] if c["check_id"] == "T-001-doc-1"]
    assert len(flagged) == 1 and flagged[0]["severity"] == "WARN"
    assert result["math_status"] != "COMPLIANT_FOR_SUBMISSION"


@pytest.mark.asyncio
async def test_a_corrected_document_type_clears_the_finding() -> None:
    ctx: dict[str, Any] = {"extracted": [doc("doc-1", "COMMERCIAL_INVOICE")], "documents": [meta("doc-1", "COMMERCIAL_INVOICE")]}

    result = await calculation.run(ctx)

    assert not [c for c in result["checks"] if c["check_id"].startswith("T-001-")]


# --- the upload route ---


async def new_bundle(client: Any) -> str:
    return (await client.post("/api/v1/bundles", json={"reference": "IDENTITY", "destination_country": "SG"})).json()["id"]


async def upload(client: Any, bundle_id: str, name: str, **form: str) -> Any:
    return await client.post(
        f"/api/v1/bundles/{bundle_id}/documents", files={"file": (name, case_c_pdf(name), "application/pdf")}, data=form or None
    )


@pytest.mark.asyncio
async def test_the_declared_type_is_stored_returned_listed_and_audited() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "bill_of_lading.pdf", declared_type="bill of lading")

        assert response.status_code == 201 and response.json()["declared_type"] == "BILL_OF_LADING"
        listed = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]
        assert [d["declared_type"] for d in listed] == ["BILL_OF_LADING"]
        events = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["events"]
        [uploaded] = [e for e in events if e["event_type"] == "DOCUMENT_UPLOADED"]
        assert uploaded["payload"]["declared_type"] == "BILL_OF_LADING"


@pytest.mark.asyncio
async def test_without_a_declared_type_nothing_is_stored_for_it_and_the_audit_payload_is_what_it_was() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "bill_of_lading.pdf")

        assert response.status_code == 201 and response.json()["declared_type"] is None
        events = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["events"]
        [uploaded] = [e for e in events if e["event_type"] == "DOCUMENT_UPLOADED"]
        assert set(uploaded["payload"]) == {"document_id", "filename", "sha256", "bytes"}


@pytest.mark.asyncio
async def test_an_empty_declared_type_field_is_none_and_a_wrong_one_is_a_422_that_stores_nothing() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        empty = await upload(client, bundle_id, "bill_of_lading.pdf", declared_type="")
        wrong = await upload(client, bundle_id, "packing_list.pdf", declared_type="UNKNOWN")

        assert empty.status_code == 201 and empty.json()["declared_type"] is None
        assert wrong.status_code == 422 and wrong.json()["detail"]["allowed"] == list(DECLARABLE_TYPES)
        assert len((await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]) == 1


@pytest.mark.asyncio
async def test_the_same_bytes_uploaded_again_with_another_declared_type_replace_the_record() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        await upload(client, bundle_id, "bill_of_lading.pdf", declared_type="PACKING_LIST")

        again = await upload(client, bundle_id, "bill_of_lading.pdf", declared_type="BILL_OF_LADING")

        assert again.status_code == 201
        listed = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]
        assert [d["declared_type"] for d in listed] == ["BILL_OF_LADING"]


@pytest.mark.asyncio
async def test_a_declared_type_reaches_the_assessment_in_demo_mode_too() -> None:
    from tests.helpers import wait_for_run

    async with api_client() as client:
        bundle_id = await new_bundle(client)
        await upload(client, bundle_id, "commercial_invoice.pdf", declared_type="PACKING_LIST")  # the fixture reads it as an invoice
        await upload(client, bundle_id, "bill_of_lading.pdf", declared_type="BILL_OF_LADING")
        run = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        assert (await wait_for_run(bundle_id, run.json()["run_id"], timeout=30))["state"] == "COMPLETE"

        checks = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()["checks"]

        flagged = [c for c in checks if c["check_id"].startswith("T-001-")]
        assert len(flagged) == 1 and "uploaded as a Packing List" in flagged[0]["message"]
        assert "read it as a Commercial Invoice" in flagged[0]["message"]


def test_the_types_a_person_may_declare_are_the_ones_the_extraction_reads() -> None:
    from typing import get_args

    from app.domain.schemas import DocType

    assert set(DECLARABLE_TYPES) == set(get_args(DocType)) - {"UNKNOWN"}
    assert set(document_identity.TYPE_LABELS) == set(DECLARABLE_TYPES)


def test_the_web_apps_type_picker_offers_the_types_the_backend_accepts_under_the_names_it_shows() -> None:
    import re

    from tests.helpers import REPO_ROOT

    web = (REPO_ROOT / "frontend" / "lib" / "documentTypes.ts").read_text(encoding="utf-8")
    offered = dict(re.findall(r'\{ value: "([A-Z_]+)", label: "([^"]+)" \}', web))

    assert offered == document_identity.TYPE_LABELS


@pytest.mark.parametrize(("declared", "says_missing"), [
    ("COMMERCIAL_INVOICE", True), ("BILL_OF_LADING", True), ("PACKING_LIST", True),     # the assessment always expects these three
    ("CERTIFICATE_OF_ORIGIN", False), ("PHYTOSANITARY", False), ("MILL_TEST_CERTIFICATE", False),
])
def test_a_document_is_called_missing_only_where_the_assessment_expects_it(declared, says_missing) -> None:
    [flag] = type_checks([meta("doc-1", declared)], [doc("doc-1", "UNKNOWN" if declared == "PACKING_LIST" else "PACKING_LIST")])

    assert ("so one is still missing" in flag.message) is says_missing
    assert f"No other file was read as a {document_identity.TYPE_LABELS[declared]}" in flag.message


def test_the_required_types_are_the_ones_the_grounding_agent_always_expects() -> None:
    from app.agents.grounding import CORE_TRADE_DOCUMENTS

    assert document_identity.REQUIRED_TYPES == {doc_type for doc_type, _label in CORE_TRADE_DOCUMENTS}
