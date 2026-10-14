"""Confidence routing over a certificate's table cells and heat numbers (rows of test_results / heat_numbers)."""

from __future__ import annotations

import pytest

from app.services import confidence, metallurgy
from tests.unit.material_fakes import GOOD_HEAT, certificate, invoice, line, packing


def route(docs, *, math_status="COMPLIANT_FOR_SUBMISSION"):
    checks = [r.model_dump() for r in metallurgy.run(docs)]
    import asyncio

    return asyncio.run(confidence.route({"extracted": docs, "checks": checks, "math_status": math_status}))["confidence"]


def test_a_cited_chemistry_cell_with_low_confidence_sends_the_bundle_to_review() -> None:
    cert = certificate({"H1": GOOD_HEAT})
    weak = next(i for i, r in enumerate(cert.test_results) if r.parameter == "Cr")
    cert.test_results[weak].confidence = 0.80      # a smudged chromium value: it enters the carbon equivalent (M-002)

    result = route([invoice(line("73043100")), packing(["H1"]), cert])

    assert result["action"] == "INTERACTIVE_REVIEW" and result["min_field_confidence"] == 0.8
    low = result["low_confidence_fields"][0]
    assert low["document_id"] == "mtc-1" and low["field"] == "test_results" and low["row"] == weak
    assert "line_item" not in low and "M-002" in low["used_by"]
    assert f"mtc-1.test_results[{weak}]" in result["reason"]


def test_a_cell_no_check_cites_does_not_force_a_review() -> None:
    cert = certificate({"H1": GOOD_HEAT})
    unused = next(i for i, r in enumerate(cert.test_results) if r.parameter == "Nb")   # no limit, no threshold use here
    cert.test_results[unused].confidence = 0.30

    result = route([invoice(line("73041900")), packing(["H1"]), cert])

    assert result["min_overall_confidence"] == 0.30           # kept for reference ...
    assert result["min_field_confidence"] >= 0.95 and result["action"] == "AUTO_ACCEPT"   # ... but it decides nothing


def test_a_low_confidence_heat_number_cell_is_cited_by_the_traceability_check() -> None:
    pl = packing(["H1"])
    pl.heat_numbers[0].confidence = 0.70

    result = route([invoice(line("73041900")), pl, certificate({"H1": GOOD_HEAT})])

    assert result["action"] == "INTERACTIVE_REVIEW"
    assert any(f["field"] == "heat_numbers" and f["document_id"] == "pl-1" and f["row"] == 0 for f in result["low_confidence_fields"])


def test_rows_resolve_by_list_name_and_index_and_nothing_else() -> None:
    cert = certificate({"H1": GOOD_HEAT})

    assert confidence._resolve(cert, "test_results", None, 0)[0][2] == "test_results"
    assert confidence._resolve(cert, "test_results", None, 10_000) == []
    assert confidence._resolve(cert, "test_results", None, -1) == []
    assert confidence._resolve(cert, "test_results", None, True) == []
    assert confidence._resolve(cert, "test_results", None, None) == []        # a row list needs a row
    assert confidence._resolve(cert, "heat_numbers", None, 0)[0][1].value == "H1"
    assert confidence._resolve(cert, "specification", None, None)[0][0] is None   # a header field still resolves as before


def test_every_populated_row_counts_towards_the_overall_minimum() -> None:
    cert = certificate({"H1": GOOD_HEAT})
    fields = list(confidence._iter_fields(cert))

    rows = [f for f in fields if f[3] == "test_results"]
    assert len(rows) == len(cert.test_results) and {f[0] for f in rows} == {"test_results"}
    assert [f for f in fields if f[3] == "heat_numbers"][0][1] == 0
    assert all(f[3] is None for f in fields if f[0] not in ("test_results", "heat_numbers"))


@pytest.mark.parametrize("collection", ["test_results", "heat_numbers"])
def test_the_label_names_the_list_and_the_row(collection) -> None:
    scoped = confidence._Scoped("mtc-1", collection, 3, 0.9, collection=collection)

    assert scoped.label == f"mtc-1.{collection}[3]"
    assert confidence._Scoped("inv", "unit_price", 2, 0.9).label == "inv.line_items[2].unit_price"
