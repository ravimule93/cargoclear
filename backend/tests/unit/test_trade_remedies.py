"""E-origin, SEC-001 near-threshold alloy evasion, SEC-002 anti-dumping (services/trade_remedies.py)."""

from __future__ import annotations

import pytest

from app.services import trade_remedies
from tests.unit.material_fakes import GOOD_HEAT, certificate, invoice, line, packing, result, severity


def with_(**changes: str) -> dict[str, str]:
    return {**GOOD_HEAT, **changes}


def inv(hs: str = "73043100", origin: str | None = "CHINA", **kw):
    return invoice(line(hs), origin=origin, **kw)


def run(docs, destination="IN"):
    return trade_remedies.run(list(docs), destination)


# ---------------------------------------------------------------------------
# E-origin
# ---------------------------------------------------------------------------


def test_the_same_origin_on_two_documents_passes_whatever_the_spelling() -> None:
    check = result(run([inv(origin="CHINA"), packing(origin="People's Republic of China")]), "E-origin")

    assert check.severity == "PASS" and "CN on all 2 documents" in check.message
    assert [e["doc"] for e in check.evidence] == ["inv-1", "pl-1"] and all(e["bbox"] for e in check.evidence)


def test_origins_that_disagree_are_a_contradiction_that_names_both_documents() -> None:
    check = result(run([inv(origin="CHINA"), packing(origin="INDIA")]), "E-origin")

    assert check.severity == "MATERIAL"
    assert "Commercial invoice: CHINA" in check.message and "Packing list: INDIA" in check.message


def test_an_origin_the_rule_set_does_not_recognise_is_a_warning_not_a_guess() -> None:
    check = result(run([inv(origin="ATLANTIS"), packing(origin="ATLANTIS")]), "E-origin")

    assert check.severity == "WARN" and "'ATLANTIS' is not a name the rule set recognises" in check.message


def test_one_document_stating_the_origin_has_nothing_to_be_compared_with() -> None:
    assert result(run([inv(origin="CHINA"), packing()]), "E-origin") is None
    assert result(run([inv(origin=None)]), "E-origin") is None


# ---------------------------------------------------------------------------
# SEC-001
# ---------------------------------------------------------------------------


def test_a_value_just_under_an_alloy_threshold_on_a_non_alloy_declaration_is_noticed() -> None:
    check = result(run([inv(), certificate({"H1": with_(Cr="0.27")})]), "SEC-001")

    assert check.severity == "WARN"
    assert "Cr 0.27%" in check.message and "within 20 % below the 0.3 %" in check.message
    assert check.evidence[0]["raw_value"] == "H1: Cr 0.27%" and check.assumptions
    assert check.rule_set == "demo-curated"


def test_boron_just_under_its_threshold_is_noticed_too() -> None:
    assert severity(run([inv(), certificate({"H1": with_(B="0.0007")})]), "SEC-001") == "WARN"


def test_nothing_is_flagged_when_the_steel_is_clearly_inside_or_clearly_outside() -> None:
    assert result(run([inv(), certificate()]), "SEC-001") is None                                   # far from every threshold
    assert result(run([inv(), certificate({"H1": with_(Cr="0.35")})]), "SEC-001") is None            # alloy: M-001's business
    assert result(run([inv("73045100"), certificate({"H1": with_(Cr="0.27")})]), "SEC-001") is None  # declared alloy already
    assert result(run([inv("73041900"), certificate({"H1": with_(Cr="0.27")})]), "SEC-001") is None  # 'any': nothing to evade
    assert result(run([inv()]), "SEC-001") is None                                                    # no certificate


def test_a_second_near_value_is_counted_not_listed() -> None:
    check = result(run([inv(), certificate({"H1": with_(Cr="0.27", Mn="1.50")})]), "SEC-001")

    assert "1 more value(s) are also close" in check.message


# ---------------------------------------------------------------------------
# SEC-002
# ---------------------------------------------------------------------------


def test_chinese_seamless_tube_into_india_may_attract_anti_dumping_duty() -> None:
    check = result(run([inv("73043100", "CHINA")]), "SEC-002")

    assert check.severity == "WARN"                                       # ALWAYS a warning: the rate is producer-specific
    assert "7304.31.00 (declared)" in check.message and "12 % of the assessable value" in check.message
    assert "ADD-IN-7304-CN-ILLUSTRATIVE" in check.message and "notification not supplied" in check.message
    assert "producer-specific" in check.message and "indicative duty estimate" in check.message
    assert check.assumptions and "not been verified" in check.assumptions[0]
    assert check.rule_set == "demo-curated" and "ILLUSTRATIVE" in check.regulation_ref


def test_the_code_the_chemistry_points_to_is_screened_as_well_and_reported_once_with_the_declared_one() -> None:
    check = result(run([inv("73043100", "CHINA"), certificate({"H1": with_(Cr="0.35")})]), "SEC-002")

    assert check.message.count("ADD-IN-7304-CN-ILLUSTRATIVE") == 1
    assert "7304.31.00 (declared) and 7304.51 (the code the certificate's chemistry points to)" in check.message


def test_no_anti_dumping_finding_when_destination_origin_or_code_do_not_match() -> None:
    assert result(run([inv("73043100", "CHINA")], "SG"), "SEC-002") is None        # no entry for that destination
    assert result(run([inv("73043100", "INDIA")]), "SEC-002") is None              # origin not covered
    assert result(run([inv("72081000", "CHINA")]), "SEC-002") is None              # code not covered
    assert result(run([inv("73043100", "VIETNAM")]), "SEC-002") is None


def test_an_unstated_origin_cannot_rule_out_anti_dumping() -> None:
    check = result(run([inv("73043100", None)]), "SEC-002")

    assert check.severity == "WARN" and "No country of origin is stated" in check.message and "CN" in check.message


def test_an_unrecognised_origin_cannot_rule_out_anti_dumping() -> None:
    check = result(run([inv("73043100", "ATLANTIS")]), "SEC-002")

    assert check.severity == "WARN" and "'ATLANTIS' is not recognised" in check.message


def test_a_matching_origin_on_any_document_is_enough() -> None:
    assert severity(run([inv("73043100", "INDIA"), packing(origin="CHINA")]), "SEC-002") == "WARN"


def test_the_match_list_feeds_the_valuation() -> None:
    docs = [inv("73043100", "CHINA"), certificate({"H1": with_(Cr="0.35")})]

    matches = trade_remedies.anti_dumping_matches(docs, "IN")

    assert [(m.hs_digits, m.implied) for m in matches] == [("73043100", False), ("730451", True)]
    assert all(m.origin.code == "CN" for m in matches)
    assert trade_remedies.anti_dumping_matches(docs, "SG") == []


def test_run_returns_only_what_applies() -> None:
    assert run([inv("72081000", "INDIA")]) == []
    assert [r.check_id for r in run([inv(), packing(origin="CHINA")])] == ["E-origin", "SEC-002"]


@pytest.mark.parametrize("destination", ["in", "IN", "In"])
def test_the_destination_is_case_insensitive(destination) -> None:
    assert severity(run([inv("73043100", "CHINA")], destination), "SEC-002") == "WARN"
