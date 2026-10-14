"""The declaration pre-fill pack: which value is taken from which document, what is flagged, and what the pack says about itself.

``assemble`` is pure, so these tests hand it plain dicts (the shape of a stored extraction and of an iteration).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.domain.prefill import SCHEMA_ID, SCHEMA_VERSION, PrefillPack
from app.reference.loader import get_reference
from app.services import audit
from app.services.prefill import assemble, content_hash

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


def ref(value: Any, confidence: float = 0.99, unit: str | None = None, page: int = 1, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "confidence": confidence, "bbox": {"page": page, "ymin": 10, "xmin": 10, "ymax": 20, "xmax": 90}}
    if unit is not None:
        out["unit"] = unit
    out.update(extra)
    return out


def line(description: str = "SEAMLESS PIPE", hs: str = "73041900", total: str = "1000", **extra: Any) -> dict[str, Any]:
    return {
        "description": ref(description), "quantity": ref("100 PCS"), "hs_code_declared": ref(hs), "unit_price": ref("10"),
        "total_value": ref(total), "currency": ref("USD"), "net_weight_kg": ref(None, 0.5), "gross_weight_kg": ref(None, 0.5), **extra,
    }


def docs() -> list[dict[str, Any]]:
    return [
        {"document_id": "inv", "doc_type": "COMMERCIAL_INVOICE", "document_number": ref("INV-1"), "consignee": ref("ACME PTE. LTD."),
         "consignor": ref("TIANJIN STEEL CO"), "incoterm": ref("FOB TIANJIN"), "country_of_origin": ref("CHINA"),
         "invoice_value": ref("1000"), "invoice_currency": ref("USD"), "line_items": [line()]},
        {"document_id": "bol", "doc_type": "BILL_OF_LADING", "document_number": ref("BL-9"), "consignee": ref("ACME PTE LTD"),
         "vessel_or_flight": ref("MV TEST"), "port_of_loading": ref("TIANJIN"), "port_of_discharge": ref("NHAVA SHEVA"),
         "total_gross_weight_kg": ref("14,280.50", unit="KGS"), "freight_amount": ref("1850"), "freight_currency": ref("USD"), "line_items": []},
        {"document_id": "pl", "doc_type": "PACKING_LIST", "document_number": ref("PL-3"), "consignee": ref("ACME PTE LTD"),
         "total_gross_weight_kg": ref("14.2805", unit="MT"), "total_net_weight_kg": ref("14000", unit="KGS"), "package_count": ref("25"),
         "line_items": [line("SEAMLESS PIPE (PL)")]},
        {"document_id": "mtc", "doc_type": "MILL_TEST_CERTIFICATE", "specification": ref("ASTM A106 GR B"),
         "heat_numbers": [ref("H1"), ref("H2"), ref("H1")], "test_results": [], "line_items": []},
    ]


def bundle(destination: str = "SG") -> dict[str, Any]:
    return {
        "id": "bnd-1", "reference": "SHIP-7", "destination_country": destination,
        "documents": [
            {"document_id": "inv", "filename": "inv.pdf", "doc_type": "COMMERCIAL_INVOICE", "sha256": "a" * 64, "bytes": 10},
            {"document_id": "bol", "filename": "bol.pdf", "doc_type": "BILL_OF_LADING", "sha256": "b" * 64, "bytes": 11},
            {"document_id": "pl", "filename": "pl.pdf", "doc_type": "PACKING_LIST", "sha256": "c" * 64, "bytes": 12},
            {"document_id": "mtc", "filename": "mtc.pdf", "doc_type": "MILL_TEST_CERTIFICATE", "sha256": "d" * 64, "bytes": 13},
            {"document_id": "later", "filename": "later.pdf", "doc_type": "UNKNOWN", "sha256": "e" * 64, "bytes": 14},
        ],
    }


def iteration(status: str = "COMPLIANT_FOR_SUBMISSION", checks: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {"iteration": 2, "status": status, "checks": checks or [], "missing_evidence": [], "documents": ["inv", "bol", "pl", "mtc"],
            "run_mode": "full", "data_source": "fixture", "created_at": "2026-10-14T08:00:00+00:00", "valuation": None,
            "reference_data": {"hs_rules.json": "abc"}, "corrections": [], **extra}


def make(extracted: list[dict[str, Any]] | None = None, **kw: Any) -> PrefillPack:
    return assemble(
        bundle=kw.pop("bundle_", bundle()), iteration=kw.pop("iteration_", iteration()), extracted=extracted if extracted is not None else docs(),
        audit_events=kw.pop("audit_events", []), reference=get_reference(), now=NOW, **kw,
    )


# ---------------------------------------------------------------------------


def test_each_value_comes_from_the_best_document_and_the_others_are_listed_beside_it() -> None:
    pack = make()
    consignee = pack.parties.consignee
    assert consignee.value == "ACME PTE. LTD." and consignee.source and consignee.source.document_id == "inv"
    assert consignee.source.filename == "inv.pdf" and consignee.source.page == 1 and consignee.source.bbox is not None
    assert [(a.document_id, a.value) for a in consignee.alternatives] == [("bol", "ACME PTE LTD"), ("pl", "ACME PTE LTD")]
    assert consignee.conflict is False and consignee.review == [], "punctuation is not a disagreement"

    s = pack.shipment
    assert (s.invoice_number.value, s.bill_of_lading_number.value, s.packing_list_number.value) == ("INV-1", "BL-9", "PL-3")
    assert s.vessel_or_flight.source and s.vessel_or_flight.source.document_id == "bol"
    assert (s.port_of_loading.value, s.port_of_discharge.value, s.incoterm.value, s.country_of_origin.value) == ("TIANJIN", "NHAVA SHEVA", "FOB TIANJIN", "CHINA")
    assert s.total_gross_weight.value == "14,280.50" and s.total_gross_weight.unit == "KGS" and s.total_gross_weight.source.document_id == "bol"  # type: ignore[union-attr]
    assert s.total_net_weight.source.document_id == "pl" and s.package_count.value == "25"  # type: ignore[union-attr]
    c = pack.commercial
    assert (c.invoice_value.value, c.invoice_currency.value, c.freight_amount.value) == ("1000", "USD", "1850")
    assert c.freight_amount.source.document_id == "bol" and c.insurance_amount.value is None  # type: ignore[union-attr]


def test_the_same_weight_in_another_unit_agrees_and_a_different_weight_is_a_conflict() -> None:
    assert make().shipment.total_gross_weight.conflict is False, "14,280.50 KGS = 14.2805 MT"

    changed = docs()
    changed[2]["total_gross_weight_kg"] = ref("14.4", unit="MT")  # 120 kg more than the bill of lading: beyond the tolerance
    value = make(changed).shipment.total_gross_weight
    assert value.conflict is True and value.value == "14,280.50", "the pack does not choose silently: it keeps the preferred document's value"
    assert value.review == ["documents disagree: PACKING_LIST says 14.4 MT"]
    assert [(a.doc_type, a.value, a.unit) for a in value.alternatives] == [("PACKING_LIST", "14.4", "MT")]


def test_documents_that_disagree_are_flagged_with_who_says_what() -> None:
    changed = docs()
    changed[1]["consignee"] = ref("GLOBEX LTD")
    value = make(changed).parties.consignee
    assert value.value == "ACME PTE. LTD." and value.conflict is True
    assert value.review == ["documents disagree: BILL_OF_LADING says GLOBEX LTD"]


def test_a_value_the_model_was_unsure_of_or_nobody_states_is_marked_and_a_corrected_one_is_not() -> None:
    changed = docs()
    changed[0]["consignor"] = ref("TIANJIN STEEL CO", confidence=0.8)
    pack = make(changed)
    assert pack.parties.consignor.review == ["read with confidence 0.80"] and pack.parties.consignor.confidence == 0.8
    assert pack.shipment.shipment_date.value is None and pack.shipment.shipment_date.source is None
    assert pack.shipment.shipment_date.review == ["not stated on any document"]

    changed[0]["consignor"] = ref("TIANJIN STEEL CO", confidence=1.0, corrected=True, original_value="TIANJIN STEEL CD")
    fixed = make(changed).parties.consignor
    assert fixed.corrected is True and fixed.confidence == 1.0 and fixed.review == []


def test_a_value_an_open_finding_cites_says_which_finding() -> None:
    checks = [
        {"check_id": "M-001", "severity": "MATERIAL", "message": "alloy", "evidence": [{"doc": "inv", "field": "hs_code_declared", "line_item": 0}]},
        {"check_id": "W-001", "severity": "PASS", "message": "ok", "evidence": [{"doc": "bol", "field": "total_gross_weight_kg"}]},
        {"check_id": "E-consignee", "severity": "WARN", "message": "w", "evidence": [{"doc": "inv", "field": "consignee"}]},
    ]
    pack = make(iteration_=iteration("MATERIAL_CONTRADICTION", checks))
    assert pack.lines[0].hs_code.review == ["M-001 (material) cites this value"]
    assert pack.parties.consignee.review == ["E-consignee (warn) cites this value"]
    assert pack.shipment.total_gross_weight.review == [], "a passing check raises nothing"
    assert [f.check_id for f in pack.assessment.blocking] == ["M-001"] and [f.check_id for f in pack.assessment.review] == ["E-consignee"]


def test_lines_are_the_invoices_else_the_packing_lists_and_never_joined() -> None:
    pack = make()
    assert [(l.line_no, l.document_id, l.description.value, l.hs_code.value) for l in pack.lines] == [(1, "inv", "SEAMLESS PIPE", "73041900")]
    assert pack.lines[0].quantity.value == "100 PCS" and pack.lines[0].line_value.value == "1000" and pack.lines[0].net_weight.value is None

    no_invoice_lines = docs()
    no_invoice_lines[0]["line_items"] = []
    assert [(l.document_id, l.description.value) for l in make(no_invoice_lines).lines] == [("pl", "SEAMLESS PIPE (PL)")]

    none = docs()
    none[0]["line_items"] = none[2]["line_items"] = []
    assert make(none).lines == []


def test_the_banner_says_not_cleared_before_anything_else() -> None:
    assert make().banner is None, "a cleared bundle with every correction included has nothing to warn about"

    blocked = make(iteration_=iteration(
        "MATERIAL_CONTRADICTION",
        [{"check_id": "M-001", "severity": "MATERIAL", "message": "m"}, {"check_id": "SEC-002", "severity": "WARN", "message": "w"}],
        missing_evidence=[{"id": "ME-X", "document_label": "Certificate X"}],
    ))
    assert blocked.banner is not None and blocked.banner.startswith("NOT CLEARED. The assessment is material contradiction: 1 contradiction(s), 1 missing document(s), 1 item(s)")
    assert blocked.assessment.missing_documents == ["Certificate X"]

    pending = make(pending_corrections=2).banner
    assert pending is not None and "2 correction change(s)" in pending and "Recompute first" in pending

    old = make(latest_iteration=5).banner
    assert old is not None and old.startswith("SUPERSEDED. This pack is for assessment 2; assessment 5 is newer.")
    assert make(latest_iteration=2).banner is None


def test_material_certificate_heats_are_listed_once_and_a_missing_certificate_is_said() -> None:
    assert make().material.heat_numbers == ["H1", "H2"] and make().material.specification.value == "ASTM A106 GR B"
    assert make().material.certificate_document_id == "mtc"
    without = make([d for d in docs() if d["doc_type"] != "MILL_TEST_CERTIFICATE"]).material
    assert without.certificate_document_id is None and without.specification.review == ["no mill test certificate in the bundle"]


def test_what_the_declarant_must_supply_depends_on_the_destination() -> None:
    india = make(bundle_=bundle("IN"))
    assert india.declaration.declaration == "Import declaration (Bill of Entry)" and india.declaration.rule_set == "demo-curated"
    assert "IEC" in [i.id for i in india.to_be_supplied] and "UEN" not in [i.id for i in india.to_be_supplied]
    assert "UEN" in [i.id for i in make(bundle_=bundle("sg")).to_be_supplied]
    unknown = make(bundle_=bundle("JP"))
    assert unknown.declaration.declaration == "Customs declaration" and unknown.declaration.destination_country == "JP" and unknown.to_be_supplied


def test_the_pack_carries_the_assessments_estimate_corrections_documents_and_audit_head() -> None:
    estimate = {"destination_country": "SG", "status": "ESTIMATED", "total_duty": 12.5, "duties": [], "assumptions": ["a"], "disclaimer": "d"}
    applied = [{"correction_id": "cor-4", "seq": 4, "document_id": "inv", "path": "consignee", "value": "X", "original_value": "Y", "created_at": "t", "status": "applied"}]
    chain: list[dict[str, Any]] = []
    for n in range(1, 4):
        prev = chain[-1]["hash"] if chain else "GENESIS"
        chain.append(audit._build_event("bnd-1", 1, "SYSTEM_EVENT", "system", {"n": n}, prev, n))
    pack = make(iteration_=iteration(valuation=estimate, corrections=applied), audit_events=chain)

    assert pack.valuation is not None and pack.valuation.total_duty == 12.5 and pack.valuation.assumptions == ["a"]
    assert [(c.correction_id, c.status) for c in pack.corrections] == [("cor-4", "applied")]
    assert [d.document_id for d in pack.documents] == ["inv", "bol", "pl", "mtc"], "only the documents this assessment read"
    assert pack.provenance.audit_events == 3 and pack.provenance.audit_head_hash == chain[-1]["hash"] and pack.provenance.audit_chain_verified is True
    assert pack.provenance.reference_data == {"hs_rules.json": "abc"}

    chain[1]["payload"] = {"n": 99}  # tampered
    assert make(audit_events=chain).provenance.audit_chain_verified is False


def test_the_integrity_hash_can_be_recomputed_by_anyone_and_changes_with_any_value() -> None:
    pack = make()
    assert pack.schema_id == SCHEMA_ID and pack.schema_version == SCHEMA_VERSION and pack.generated_at == NOW.isoformat()
    assert len(pack.integrity.content_sha256) == 64 and pack.integrity.content_sha256 == content_hash(pack)

    # a reader holding only the JSON file gets the same answer
    reread = PrefillPack.model_validate(json.loads(pack.model_dump_json()))
    assert content_hash(reread) == pack.integrity.content_sha256

    changed = docs()
    changed[0]["consignee"] = ref("SOMEBODY ELSE")
    assert make(changed).integrity.content_sha256 != pack.integrity.content_sha256


def test_an_old_extraction_without_the_new_fields_still_makes_a_pack() -> None:
    bare = [{"document_id": "inv", "doc_type": "COMMERCIAL_INVOICE", "line_items": []}]
    pack = make(bare, iteration_={"iteration": 1, "status": "MISSING_EVIDENCE", "documents": ["inv"]})
    assert pack.parties.consignee.review == ["not stated on any document"] and pack.lines == [] and pack.assessment.status == "MISSING_EVIDENCE"
