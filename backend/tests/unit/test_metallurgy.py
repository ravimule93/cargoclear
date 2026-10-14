"""M-001 alloy status, M-002 carbon equivalent, M-003 specification limits, M-004 heat traceability (services/metallurgy.py)."""

from __future__ import annotations

import pytest

from app.services import metallurgy
from tests.unit.material_fakes import GOOD_HEAT, certificate, invoice, lab, line, packing, result, severity


def with_(**changes: str) -> dict[str, str]:
    return {**GOOD_HEAT, **changes}


def declared(hs: str):
    """An invoice that declares ``hs`` (and nothing else the material checks care about)."""
    return invoice(line(hs))


def run(*docs):
    return metallurgy.run(list(docs))


# ---------------------------------------------------------------------------
# classifying a heat (HS Chapter 72 Note 1)
# ---------------------------------------------------------------------------


def classify(heat_values: dict[str, str], unit: str | None = "%") -> metallurgy.HeatClass:
    heat = metallurgy.collect_heats(certificate({"H1": heat_values}, unit=unit))[0]
    return metallurgy.classify_heat(heat, metallurgy.get_reference())


def test_a_plain_carbon_steel_is_non_alloy() -> None:
    assert classify(GOOD_HEAT).alloy_class == "non_alloy"


@pytest.mark.parametrize(
    ("element", "value"),
    [("Cr", "0.30"), ("Cr", "0.35"), ("Mn", "1.65"), ("Mo", "0.08"), ("Ni", "0.30"), ("Cu", "0.40"), ("Si", "0.60"),
     ("V", "0.10"), ("Nb", "0.06"), ("Ti", "0.05"), ("Al", "0.30"), ("B", "0.0008")],
)
def test_an_element_AT_its_threshold_makes_the_steel_alloy(element, value) -> None:
    """Note 1(f) says 'X % or more': the threshold itself is alloy."""
    heat = classify(with_(**{element: value}))

    assert heat.alloy_class == "alloy"
    assert [t[0] for t in heat.triggers] == [element]


def test_just_below_a_threshold_is_non_alloy_but_is_noticed() -> None:
    heat = classify(with_(Cr="0.29"))

    assert heat.alloy_class == "non_alloy" and heat.triggers == []
    assert [n[0] for n in heat.near] == ["Cr"]


def test_far_below_a_threshold_is_not_near() -> None:
    assert classify(with_(Cr="0.08")).near == []


def test_boron_reported_in_ppm_is_converted_before_it_is_compared() -> None:
    rows = [lab("0.08", "Cr", "H1", "%"), lab("9", "B", "H1", "ppm"), lab("0.18", "C", "H1", "%")]
    from app.domain.schemas import ExtractedDocument

    doc = ExtractedDocument(document_id="c", doc_type="MILL_TEST_CERTIFICATE", doc_type_confidence=0.9, test_results=rows)
    heat = metallurgy.collect_heats(doc)[0]

    assert metallurgy.classify_heat(heat, metallurgy.get_reference()).alloy_class == "alloy"  # 9 ppm = 0.0009 % >= 0.0008 %


def test_chromium_and_carbon_decide_stainless() -> None:
    assert classify(with_(Cr="18.2", C="0.05")).alloy_class == "stainless"
    assert classify(with_(Cr="10.5", C="1.2")).alloy_class == "stainless"
    assert classify(with_(Cr="12.0", C="1.5")).alloy_class == "alloy", "above 1.2 % carbon it is not stainless; Cr still makes it alloy"


def test_an_upper_bound_at_or_above_a_threshold_is_undetermined_and_one_below_it_is_not() -> None:
    assert classify(with_(Cr="<0.5")).alloy_class == "indeterminate"
    assert classify(with_(Cr="<0.05")).alloy_class == "non_alloy"
    assert classify(with_(Cr="ND")).alloy_class == "non_alloy"


def test_any_exact_trigger_beats_an_undetermined_element() -> None:
    assert classify(with_(Cr="0.35", Mo="<0.5")).alloy_class == "alloy"


def test_the_worst_heat_decides_the_certificate() -> None:
    doc = certificate({"H1": GOOD_HEAT, "H2": with_(Cr="0.35")})

    assessment = metallurgy.assess_alloy_status([doc])

    assert assessment.alloy_class == "alloy" and assessment.deciding().heat.label == "H2"
    assert assessment.reported >= {"C", "Mn", "Cr"} and "B" in assessment.not_reported


def test_a_certificate_without_chemistry_has_no_assessment() -> None:
    assert metallurgy.assess_alloy_status([certificate({"H1": {"YS": "310"}})]) is None
    assert metallurgy.assess_alloy_status([invoice()]) is None


# ---------------------------------------------------------------------------
# M-001
# ---------------------------------------------------------------------------


def test_no_certificate_or_no_alloy_rule_means_no_check() -> None:
    assert result(run(declared("73043100")), "M-001") is None                       # no certificate
    assert result(run(declared("10019910"), certificate()), "M-001") is None        # a code the table has no rule for
    assert result(run(invoice(line(hs="")), certificate()), "M-001") is None        # no code declared


def test_a_declaration_that_matches_the_chemistry_passes_and_says_what_was_not_tested() -> None:
    check = result(run(declared("73043100"), certificate()), "M-001")

    assert check.severity == "PASS" and check.assumptions == []
    assert "reads as non-alloy" in check.message and "7304.31.00" in check.message
    assert "does not report" in check.message and "B" in check.message                 # 'as certified', not silently assumed
    assert check.rule_set == "demo-curated" and "Note 1" in check.regulation_ref


def test_line_pipe_is_not_decided_by_the_alloy_status() -> None:
    """7304.19 covers non-alloy and alloy line pipe alike: an alloy heat does not contradict it."""
    check = result(run(declared("73041900"), certificate({"H1": with_(Cr="0.35")})), "M-001")

    assert check.severity == "PASS" and "does not decide it" in check.message


def test_a_non_alloy_declaration_over_alloy_chemistry_is_a_material_contradiction() -> None:
    check = result(run(declared("73043100"), certificate({"H1": GOOD_HEAT, "H2": with_(Cr="0.35")})), "M-001")

    assert check.severity == "MATERIAL"
    assert "declared non-alloy" in check.message and "heat H2 reports Cr 0.35%" in check.message
    assert "0.3 %" in check.message and "Note 1(f)" in check.message
    assert "7304.51" in check.message and "to be confirmed" in check.message        # the twin subheading is suggested, not asserted


def test_the_alloy_finding_says_to_look_at_the_certificate_not_at_the_invoice_that_carries_the_code() -> None:
    """The invoice's HS code is the first thing the evidence cites; the finding is about the certificate. The check says so itself, so
    no consumer has to guess from the order of the evidence."""
    inv = declared("73043100")
    cert = certificate({"H1": with_(Cr="0.35")})
    for docs in ((inv, cert), (cert, inv)):  # whichever order the bundle lists them in
        check = result(run(*docs), "M-001")
        assert check.severity == "MATERIAL" and check.focus_document == cert.document_id
    assert result(run(declared("73043100"), certificate()), "M-001").focus_document == "mtc-1", "also when the verdict is a pass"


def test_a_check_without_an_opinion_focuses_on_the_first_document_its_evidence_cites() -> None:
    from app.domain.schemas import CheckResult

    cited = CheckResult(check_id="W-001", severity="MATERIAL", message="m", evidence=[{"doc": "pl-1", "field": "x"}, {"doc": "bl-1", "field": "y"}])
    assert cited.focus_document == "pl-1"
    assert CheckResult(check_id="X", severity="PASS", message="m").focus_document is None
    assert CheckResult(check_id="X", severity="PASS", message="m", evidence=[{"doc": "a"}], focus_document="b").focus_document == "b", "an explicit choice wins"


def test_the_evidence_points_at_the_declared_code_and_at_the_row_that_decides() -> None:
    cert = certificate({"H1": with_(Cr="0.35")})
    check = result(run(declared("73043100"), cert), "M-001")

    fields = [(e["field"], e.get("line_item"), e.get("row")) for e in check.evidence]
    trigger_row = next(i for i, r in enumerate(cert.test_results) if r.parameter == "Cr")
    assert ("hs_code_declared", 0, None) in fields and ("test_results", None, trigger_row) in fields
    assert next(e for e in check.evidence if e["field"] == "test_results")["raw_value"] == "H1: Cr 0.35%"
    assert all(e["bbox"] for e in check.evidence)


def test_an_alloy_declaration_over_non_alloy_chemistry_is_a_material_contradiction() -> None:
    check = result(run(declared("73045100"), certificate()), "M-001")

    assert check.severity == "MATERIAL"
    assert "declared alloy" in check.message and "reads as non-alloy" in check.message and "7304.31" in check.message


def test_a_non_alloy_declaration_over_stainless_chemistry_names_the_stainless_threshold() -> None:
    check = result(run(declared("73043100"), certificate({"H1": with_(Cr="18.2", C="0.04")})), "M-001")

    assert check.severity == "MATERIAL" and "Note 1(e)" in check.message and "7304.41" in check.message


def test_an_element_reported_only_as_an_upper_bound_cannot_confirm_a_declaration() -> None:
    check = result(run(declared("73043100"), certificate({"H1": with_(Cr="<0.5")})), "M-001")

    assert check.severity == "WARN"
    assert "does not rule out" in check.message and check.assumptions


def test_a_certificate_without_chemistry_cannot_confirm_a_non_alloy_code() -> None:
    check = result(run(declared("73043100"), certificate({"H1": {"YS": "310", "UTS": "450"}})), "M-001")

    assert check.severity == "WARN" and "states no chemistry" in check.message
    assert result(run(declared("73041900"), certificate({"H1": {"YS": "310"}})), "M-001") is None  # nothing to check for 'any'


def test_the_packing_list_declaration_is_used_when_there_is_no_invoice() -> None:
    check = result(run(packing(hs="73043100"), certificate({"H1": with_(Cr="0.35")})), "M-001")

    assert check.severity == "MATERIAL"


# ---------------------------------------------------------------------------
# M-002
# ---------------------------------------------------------------------------


def test_carbon_equivalent_formulas() -> None:
    v = {"C": 0.18, "Mn": 0.95, "Cr": 0.08, "Mo": 0.02, "V": 0.01, "Ni": 0.05, "Cu": 0.10}
    assert metallurgy.carbon_equivalent_iiw(v) == pytest.approx(0.18 + 0.95 / 6 + 0.11 / 5 + 0.15 / 15)
    p = {"C": 0.10, "Si": 0.30, "Mn": 1.20, "Cu": 0.10, "Cr": 0.10, "Ni": 0.10, "Mo": 0.02, "V": 0.02, "B": 0.0}
    assert metallurgy.carbon_equivalent_pcm(p) == pytest.approx(0.10 + 0.01 + 1.40 / 20 + 0.10 / 60 + 0.02 / 15 + 0.002)


def test_a_carbon_equivalent_inside_the_limit_passes_for_every_heat() -> None:
    check = result(run(certificate({"H1": GOOD_HEAT, "H2": with_(C="0.19", Mn="0.98")})), "M-002")

    assert check.severity == "PASS" and "heat H1 CE(IIW) 0.37" in check.message and "heat H2 CE(IIW) 0.39" in check.message
    assert "0.43" in check.message and check.assumptions == []


def test_the_value_is_rounded_to_two_decimals_like_the_standard_does() -> None:
    # C 0.24 + Mn 1.14 / 6 = 0.43 exactly (0.24 + 0.19)
    assert result(run(certificate({"H1": with_(C="0.24", Mn="1.14", Cr="0", Mo="0", V="0", Ni="0", Cu="0")})), "M-002").severity == "PASS"
    # 0.4341 rounds to 0.43 (passes); 0.4351 rounds to 0.44 (exceeds)
    assert result(run(certificate({"H1": with_(C="0.24", Mn="1.165", Cr="0", Mo="0", V="0", Ni="0", Cu="0")})), "M-002").severity == "PASS"
    assert result(run(certificate({"H1": with_(C="0.24", Mn="1.17", Cr="0", Mo="0", V="0", Ni="0", Cu="0")})), "M-002").severity == "WARN"


def test_exceeding_the_limit_is_a_warning_because_the_limit_depends_on_the_wall_thickness() -> None:
    check = result(run(certificate({"H1": with_(C="0.24", Mn="1.20", Cr="0.20", Mo="0.10")})), "M-002")

    assert check.severity == "WARN"
    assert "exceeds 0.43" in check.message and "wall thickness" in check.message
    assert any("25.0 mm" in a for a in check.assumptions)


def test_an_element_that_is_not_reported_is_taken_as_zero_and_the_assumption_is_listed() -> None:
    values = {k: v for k, v in GOOD_HEAT.items() if k != "Mo"}
    check = result(run(certificate({"H1": values})), "M-002")

    assert check.severity == "WARN"
    assert check.assumptions == ["Mo is not reported for heat H1; taken as 0 in the carbon equivalent"]


def test_a_low_carbon_heat_is_judged_by_pcm_and_unreported_boron_is_an_assumption() -> None:
    check = result(run(certificate({"H1": with_(C="0.10")})), "M-002")

    assert "Pcm" in check.message and check.severity == "WARN"
    assert any(a.startswith("B is not reported") for a in check.assumptions)


def test_no_limit_or_no_known_specification_means_no_carbon_equivalent_check() -> None:
    assert result(run(certificate(spec="ASTM A106 GR B")), "M-002") is None     # that standard sets no CE limit
    assert result(run(certificate(spec="EN 10216-1 P235TR1")), "M-002") is None
    assert result(run(certificate(spec=None)), "M-002") is None
    assert result(run(certificate({"H1": {"YS": "310"}})), "M-002") is None


# ---------------------------------------------------------------------------
# M-003
# ---------------------------------------------------------------------------


def test_every_value_inside_the_specification_passes() -> None:
    check = result(run(certificate()), "M-003")

    assert check.severity == "PASS" and "All 7 reported chemistry and strength values" in check.message
    assert "API 5L PSL2 Grade B" in check.message and check.rule_set == "demo-curated"


def test_an_element_above_the_maximum_is_a_contradiction_of_the_certificates_own_standard() -> None:
    check = result(run(certificate({"H1": GOOD_HEAT, "H2": with_(S="0.020")})), "M-003")

    assert check.severity == "MATERIAL"
    assert "heat H2: S 0.020% exceeds the maximum 0.015 %" in check.message and "heat H1" not in check.message


def test_an_element_below_a_minimum_is_a_contradiction() -> None:
    cert = certificate({"H1": with_(Mn="0.20", Si="0.25", Cr="0.1")}, spec="ASTM A106 GR B")

    check = result(run(cert), "M-003")

    assert check.severity == "MATERIAL" and "Mn 0.20% is below the minimum 0.29 %" in check.message


def test_strengths_are_compared_in_mpa_whatever_unit_the_certificate_prints() -> None:
    from app.domain.schemas import ExtractedDocument

    rows = [lab(v, p, "H1", "%") for p, v in GOOD_HEAT.items() if p not in ("YS", "UTS")] + [lab("30", "YS", "H1", "ksi"), lab("65", "UTS", "H1", "ksi")]
    cert = ExtractedDocument(document_id="c", doc_type="MILL_TEST_CERTIFICATE", doc_type_confidence=0.9, test_results=rows,
                             specification=certificate().specification)

    check = result(run(cert), "M-003")

    assert check.severity == "MATERIAL" and "YS 206.8 MPa is below the minimum 245 MPa" in check.message   # 30 ksi = 206.8 MPa
    assert "UTS" not in check.message                                                                      # 65 ksi = 448 MPa >= 415


def test_the_standard_can_be_met_and_the_hs_code_still_contradicted() -> None:
    """ASTM A106 allows 0.40 % Cr; HS Note 1(f) makes steel alloy at 0.30 %. M-003 passes while M-001 is material."""
    results = run(declared("73043100"), certificate({"H1": with_(Cr="0.35")}, spec="ASTM A106 GR B"))

    assert severity(results, "M-003") == "PASS"
    assert severity(results, "M-001") == "MATERIAL"


def test_an_unknown_or_missing_specification_cannot_be_verified() -> None:
    unknown = result(run(certificate(spec="EN 10216-1 P235TR1")), "M-003")
    missing = result(run(certificate(spec=None)), "M-003")

    assert unknown.severity == missing.severity == "WARN"
    assert "'EN 10216-1 P235TR1' is not in the rule set" in unknown.message
    assert "states no specification" in missing.message


def test_a_certificate_without_results_cannot_be_verified() -> None:
    check = result(run(certificate({})), "M-003")

    assert check.severity == "WARN" and "states no test results" in check.message


def test_an_unreported_limited_element_or_an_unprovable_bound_is_a_warning() -> None:
    no_phosphorus = {k: v for k, v in GOOD_HEAT.items() if k != "P"}
    assert "P is not reported" in result(run(certificate({"H1": no_phosphorus})), "M-003").message

    check = result(run(certificate({"H1": with_(S="<0.02")})), "M-003")
    assert check.severity == "WARN" and "does not show it is within 0.015 %" in check.message


def test_a_value_read_with_an_assumption_prevents_a_pass() -> None:
    check = result(run(certificate({"H1": GOOD_HEAT}, unit=None)), "M-003")

    assert check.severity == "WARN" and any("no unit printed" in a for a in check.assumptions)


# ---------------------------------------------------------------------------
# M-004
# ---------------------------------------------------------------------------


def test_heats_on_the_packing_list_are_covered_by_the_certificate() -> None:
    cert = certificate({"H-24-0881": GOOD_HEAT, "H-24-0882": GOOD_HEAT})

    check = result(run(packing(["H-24-0881", "H-24-0882"]), cert), "M-004")

    assert check.severity == "PASS" and "H-24-0881, H-24-0882" in check.message
    assert {e["doc"] for e in check.evidence} == {"pl-1", "mtc-1"} and all(e["bbox"] for e in check.evidence)


def test_a_heat_that_no_certificate_covers_is_a_contradiction() -> None:
    check = result(run(packing(["H1", "H9"]), certificate({"H1": GOOD_HEAT})), "M-004")

    assert check.severity == "MATERIAL" and "heat(s) H9 that no certificate covers" in check.message


def test_heat_numbers_match_regardless_of_punctuation_and_case() -> None:
    assert severity(run(packing(["h 24 0881"]), certificate({"H-24-0881": GOOD_HEAT})), "M-004") == "PASS"


def test_one_cell_may_list_several_heats() -> None:
    cert = certificate({"H1": GOOD_HEAT, "H2": GOOD_HEAT})

    assert severity(run(packing(["H1, H2"]), cert), "M-004") == "PASS"
    assert severity(run(packing(["H1 H2"]), cert), "M-004") == "PASS"          # a space-separated list
    assert severity(run(packing(["H1 H9"]), cert), "M-004") == "MATERIAL"      # ... of which one is not certified
    assert metallurgy._split_heats("H1, H2 / H3; H4") == ["H1", "H2", "H3", "H4"]
    assert metallurgy._split_heats("H 24 0881") == ["H 24 0881"]               # spaces inside a heat number are not a separator
    assert metallurgy._split_heats("") == []


def test_heats_are_collected_from_every_certificate_in_the_bundle() -> None:
    first, second = certificate({"H1": GOOD_HEAT}, document_id="mtc-1"), certificate({"H2": GOOD_HEAT}, document_id="mtc-2")

    assert severity(run(packing(["H1", "H2"]), first, second), "M-004") == "PASS"


def test_a_certificate_heat_the_packing_list_does_not_ship_is_noted_not_penalised() -> None:
    check = result(run(packing(["H1"]), certificate({"H1": GOOD_HEAT, "H2": GOOD_HEAT})), "M-004")

    assert check.severity == "PASS" and "also lists heat(s) H2" in check.message


def test_without_heat_numbers_the_shipment_cannot_be_traced() -> None:
    no_pl_heats = result(run(packing([]), certificate()), "M-004")
    no_cert_heats = result(run(packing(["H1"]), certificate({"H1": {}}, heat_cells=[])), "M-004")
    no_packing_list = result(run(certificate()), "M-004")

    assert no_pl_heats.severity == no_cert_heats.severity == no_packing_list.severity == "WARN"
    assert "packing list states no heat number" in no_pl_heats.message
    assert "certificate states no heat number" in no_cert_heats.message
    assert "packing list states no heat number" in no_packing_list.message


def test_without_a_certificate_there_is_nothing_to_trace() -> None:
    assert result(run(packing(["H1"])), "M-004") is None


def test_heats_named_only_by_test_result_rows_count() -> None:
    cert = certificate({"H1": GOOD_HEAT}, heat_cells=[])  # no heat-number cells, but the rows carry the heat

    assert severity(run(packing(["H1"]), cert), "M-004") == "PASS"


# ---------------------------------------------------------------------------
# the whole engine
# ---------------------------------------------------------------------------


def test_run_returns_the_checks_in_order_and_skips_what_does_not_apply() -> None:
    results = run(declared("73043100"), packing(["H1"]), certificate())

    assert [r.check_id for r in results] == ["M-001", "M-002", "M-003", "M-004"]
    assert run(invoice(), packing()) == []


def test_every_check_that_uses_a_table_names_it_and_a_traceability_check_names_none() -> None:
    results = run(declared("73043100"), packing(["H1"]), certificate())

    for check in results:
        if check.check_id == "M-004":
            assert check.rule_set is None
        else:
            assert check.rule_set == "demo-curated" and check.regulation_ref
