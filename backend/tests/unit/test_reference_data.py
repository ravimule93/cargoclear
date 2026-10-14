"""The curated reference tables: they load, they are strict, they say what they are, and their key values are pinned.

The pinned values are the REVIEWER'S CHECKLIST (app/reference/README.md): changing one must be a deliberate edit of both the
table and this test, so a number cannot drift unnoticed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.reference import loader
from app.reference.loader import FILES, REFERENCE_DIR, fingerprint, get_reference, load_reference

TABLES = ["hs_rules", "specs", "duty_rates", "valuation_defaults", "exchange_rates", "anti_dumping"]


@pytest.fixture
def copy_of_tables(tmp_path: Path) -> Path:
    for filename, _model in FILES.values():
        shutil.copy(REFERENCE_DIR / filename, tmp_path / filename)
    return tmp_path


def edit(directory: Path, filename: str, mutate) -> None:
    path = directory / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# what they are
# ---------------------------------------------------------------------------


def test_every_table_loads_and_names_its_provenance_and_verification() -> None:
    reference = get_reference()

    for name in TABLES:
        table = getattr(reference, name)
        assert table.rule_set and table.regulation_ref, name
        assert table.verification.status in ("unverified", "verified"), name


def test_nothing_claims_to_be_official_or_verified_until_a_reviewer_says_so() -> None:
    reference = get_reference()

    for name in TABLES:
        table = getattr(reference, name)
        assert table.rule_set == "demo-curated", f"{name}: a table is relabelled by its reviewer, deliberately"
        assert table.verification.status == "unverified" and table.verification.reviewer is None, name
        assert "official" not in table.rule_set.lower()
        assert "not an official source" in table.regulation_ref or "NOT" in table.regulation_ref, f"{name} must say it is not official"


def test_the_placeholder_tables_say_so_loudly() -> None:
    reference = get_reference()

    assert all(rate.illustrative for rate in reference.exchange_rates.rates)
    assert "ILLUSTRATIVE" in reference.exchange_rates.regulation_ref and "ILLUSTRATIVE" in reference.anti_dumping.regulation_ref
    assert all(entry.notification_ref is None for entry in reference.anti_dumping.entries), "no invented notification numbers"


# ---------------------------------------------------------------------------
# strictness: a typo must stop the service, not become "no rule found"
# ---------------------------------------------------------------------------


def test_a_misspelt_key_is_refused(copy_of_tables: Path) -> None:
    edit(copy_of_tables, "duty_rates.json", lambda d: d["destinations"]["IN"]["entries"][0].update(bcd_percent=7.5))

    with pytest.raises(ValidationError, match="bcd_percent"):
        load_reference(copy_of_tables)


def test_a_rate_that_is_text_is_refused(copy_of_tables: Path) -> None:
    edit(copy_of_tables, "duty_rates.json", lambda d: d["destinations"]["IN"]["entries"][0].update(bcd_pct="seven and a half"))

    with pytest.raises(ValidationError):
        load_reference(copy_of_tables)


def test_a_table_without_provenance_is_refused(copy_of_tables: Path) -> None:
    edit(copy_of_tables, "specs.json", lambda d: d.pop("regulation_ref"))

    with pytest.raises(ValidationError, match="regulation_ref"):
        load_reference(copy_of_tables)


def test_an_unknown_alloy_class_is_refused(copy_of_tables: Path) -> None:
    edit(copy_of_tables, "hs_rules.json", lambda d: d["alloy_class_by_prefix"][0].update({"class": "semi_alloy"}))

    with pytest.raises(ValidationError):
        load_reference(copy_of_tables)


def test_a_missing_table_is_refused(copy_of_tables: Path) -> None:
    (copy_of_tables / "anti_dumping.json").unlink()

    with pytest.raises(FileNotFoundError):
        load_reference(copy_of_tables)


@pytest.mark.asyncio
async def test_a_broken_table_stops_the_service_at_startup(monkeypatch) -> None:
    from app import main

    def broken():
        raise ValidationError.from_exception_data("Reference", [])

    monkeypatch.setattr(main, "require_reference", broken)

    with pytest.raises(ValidationError):
        async with main.app.router.lifespan_context(main.app):
            pass


@pytest.mark.asyncio
async def test_the_shipped_tables_let_the_service_start() -> None:
    from app import main

    async with main.app.router.lifespan_context(main.app):
        pass


# ---------------------------------------------------------------------------
# the fingerprint ties a verdict to the exact tables
# ---------------------------------------------------------------------------


def test_the_fingerprint_names_every_file_and_changes_with_its_content(copy_of_tables: Path) -> None:
    before = loader._fingerprint_of(copy_of_tables)
    assert set(before) == {filename for filename, _ in FILES.values()}
    assert all(len(v) == 16 for v in before.values())

    edit(copy_of_tables, "duty_rates.json", lambda d: d["destinations"]["IN"]["entries"][0].update(bcd_pct=10.0))
    after = loader._fingerprint_of(copy_of_tables)

    assert after["duty_rates.json"] != before["duty_rates.json"]
    assert {k: v for k, v in after.items() if k != "duty_rates.json"} == {k: v for k, v in before.items() if k != "duty_rates.json"}


def test_the_default_fingerprint_is_computed_once_and_is_not_shared_mutable_state() -> None:
    first = fingerprint()
    first["hs_rules.json"] = "tampered"

    assert fingerprint()["hs_rules.json"] != "tampered"
    assert fingerprint() == fingerprint()


# ---------------------------------------------------------------------------
# the reviewer's checklist: pinned values
# ---------------------------------------------------------------------------


def test_note_1f_thresholds_are_the_ones_the_readme_asks_the_reviewer_to_check() -> None:
    thresholds = get_reference().hs_rules.note_1f_alloy_thresholds_pct

    assert thresholds == {
        "Al": 0.30, "B": 0.0008, "Cr": 0.30, "Co": 0.30, "Cu": 0.40, "Pb": 0.40, "Mn": 1.65, "Mo": 0.08,
        "Ni": 0.30, "Nb": 0.06, "Si": 0.60, "Ti": 0.05, "W": 0.30, "V": 0.10, "Zr": 0.05,
    }
    stainless = get_reference().hs_rules.stainless
    assert (stainless.cr_min_pct, stainless.c_max_pct) == (10.5, 1.2)


@pytest.mark.parametrize(
    ("hs", "alloy_class"),
    [("7304.31.00", "non_alloy"), ("73043900", "non_alloy"), ("730451", "alloy"), ("73045900", "alloy"), ("73044100", "stainless"),
     ("73041900", "any"), ("73042300", "any"), ("73049000", "any"), ("7208.10", "non_alloy"), ("72252000", "alloy"), ("72193100", "stainless")],
)
def test_the_alloy_class_of_a_code_follows_the_longest_matching_prefix(hs, alloy_class) -> None:
    assert get_reference().hs_rules.alloy_class_of(hs).alloy_class == alloy_class


def test_codes_without_a_rule_have_none() -> None:
    rules = get_reference().hs_rules

    assert rules.alloy_class_of("10019910") is None and rules.alloy_class_of("") is None and rules.alloy_class_of("73") is None


def test_the_alloy_twin_of_a_subheading_has_the_class_it_is_listed_under() -> None:
    rules = get_reference().hs_rules

    for prefix, twins in rules.alloy_twin_subheading.items():
        for twin_class, twin in twins.items():
            assert rules.alloy_class_of(twin).alloy_class == twin_class, f"{prefix} -> {twin_class} -> {twin}"
            assert twin != prefix


def test_specification_limits_are_the_ones_the_readme_asks_the_reviewer_to_check() -> None:
    specs = {s.id: s for s in get_reference().specs.specs}

    assert specs["API5L-PSL2-B"].element_max_pct == {"C": 0.24, "Si": 0.40, "Mn": 1.20, "P": 0.025, "S": 0.015}
    assert specs["API5L-PSL2-B"].ce_iiw_max == 0.43 and specs["API5L-PSL2-B"].pcm_max == 0.25
    assert specs["API5L-PSL2-B"].assumes, "the thickness dependence of the CE limit is a stated assumption"
    assert specs["ASTM-A106-B"].element_max_pct["Cr"] == 0.40 and specs["ASTM-A106-B"].element_min_pct == {"Mn": 0.29, "Si": 0.10}
    assert specs["ASTM-A106-B"].element_max_pct["Mn"] == 1.06
    assert specs["API5L-PSL2-B"].mechanical["YS"].min == 245 and specs["ASTM-A106-B"].mechanical["UTS"].min == 415


@pytest.mark.parametrize(
    ("printed", "spec_id"),
    [("API 5L PSL2 GR.B", "API5L-PSL2-B"), ("api 5l psl 2 grade b", "API5L-PSL2-B"), ("API 5L PSL1 Gr B", "API5L-PSL1-B"),
     ("ASTM A106 GR B", "ASTM-A106-B"), ("ASTM A106/A106M Grade B", "ASTM-A106-B"), ("ASTM A53 Gr.B", "ASTM-A53-B"),
     ("ASTM A106 GR A", None), ("API 5L PSL2 GR X52", None), ("EN 10216-1 P235TR1", None), ("", None), (None, None)],
)
def test_a_printed_specification_matches_one_entry_or_none(printed, spec_id) -> None:
    match = get_reference().specs.match(printed)

    assert (match.id if match else None) == spec_id


def test_an_ambiguous_specification_is_not_guessed() -> None:
    reference = get_reference()
    twin = reference.specs.specs[0].model_copy(update={"id": "TWIN"})
    ambiguous = reference.specs.model_copy(update={"specs": [*reference.specs.specs, twin]})

    assert ambiguous.match("API 5L PSL2 GR.B") is None


def test_duty_rates_are_the_ones_the_readme_asks_the_reviewer_to_check() -> None:
    rates = get_reference().duty_rates.destinations

    india = rates["IN"].entry_for("73043100")
    assert (india.bcd_pct, india.sws_pct_of_bcd, india.igst_pct) == (7.5, 10.0, 18.0)
    assert rates["IN"].currency == "INR" and rates["IN"].model == "IN_BCD_SWS_IGST"
    singapore = rates["SG"].entry_for("73041900")
    assert (singapore.customs_duty_pct, singapore.gst_pct) == (0.0, 9.0) and rates["SG"].currency == "SGD"
    assert rates["IN"].entry_for("10019910") is None, "no rate is invented for a code the table does not name"


def test_exchange_rates_and_defaults() -> None:
    reference = get_reference()

    assert reference.exchange_rates.rate("USD", "USD").rate == 1.0
    assert reference.exchange_rates.rate("USD", "INR").rate == 85.0 and reference.exchange_rates.rate("USD", "XXX") is None
    defaults = reference.valuation_defaults.destinations
    assert (defaults["IN"].freight_pct_of_fob, defaults["IN"].insurance_pct_of_fob) == (20.0, 1.125)
    assert defaults["SG"].freight_pct_of_fob is None


def test_anti_dumping_matches_destination_origin_and_code() -> None:
    table = get_reference().anti_dumping

    assert [e.id for e in table.matches("IN", "CN", "7304.31.00")] == ["ADD-IN-7304-CN-ILLUSTRATIVE"]
    assert table.matches("IN", "IN", "73043100") == [] and table.matches("SG", "CN", "73043100") == []
    assert table.matches("IN", "CN", "72081000") == []
