"""services/page_coverage.py: the assessment says which pages the model was not shown (P-001, P-002)."""

from __future__ import annotations

from app.services import page_coverage


def plan(total, kept, boilerplate=(), over_cap=(), basis="text_layer"):
    return {"total": total, "kept": list(kept), "boilerplate": list(boilerplate), "over_cap": list(over_cap), "basis": basis}


DOCS = [{"document_id": "doc-b", "filename": "bill_of_lading.pdf"}, {"document_id": "doc-a", "filename": "invoice.pdf"}]


def test_no_plans_no_checks() -> None:
    assert page_coverage.checks(None, DOCS) == [] and page_coverage.checks({}, DOCS) == []


def test_a_document_read_whole_says_nothing() -> None:
    assert page_coverage.checks({"doc-a": plan(3, (1, 2, 3))}, DOCS) == []


def test_pages_left_out_by_the_cap_are_a_warning_that_names_them_and_the_document() -> None:
    [check] = page_coverage.checks({"doc-a": plan(30, range(1, 11), over_cap=range(11, 31))}, DOCS)

    assert check.check_id == "P-001-doc-a" and check.severity == "WARN" and check.focus_document == "doc-a"
    assert "invoice.pdf: 20 of 30 pages were not read: pages 11-30" in check.message
    assert "Pages read: 1-10" in check.message and "not in this assessment" in check.message


def test_a_scan_with_no_text_says_why_its_first_pages_were_the_ones_read() -> None:
    [check] = page_coverage.checks({"doc-a": plan(25, range(1, 11), over_cap=range(11, 26), basis="no_text_layer")}, DOCS)

    assert "the file gave no text, so the first pages were taken" in check.message


def test_skipped_terms_are_a_pass_that_lists_them() -> None:
    [check] = page_coverage.checks({"doc-a": plan(16, (1,), boilerplate=range(2, 17))}, DOCS)

    assert check.check_id == "P-002-doc-a" and check.severity == "PASS"
    assert "15 of 16 pages were skipped as terms and conditions" in check.message and "pages 2-16" in check.message


def test_both_findings_can_exist_for_one_document_and_ids_stay_unique() -> None:
    results = page_coverage.checks({"doc-a": plan(40, range(1, 11), boilerplate=(12, 14), over_cap=(11, 13, 15))}, DOCS)

    assert [r.check_id for r in results] == ["P-001-doc-a", "P-002-doc-a"]


def test_checks_follow_the_bundles_document_order_and_unlisted_documents_come_last() -> None:
    results = page_coverage.checks(
        {"doc-a": plan(30, (1,), over_cap=(2,)), "doc-b": plan(30, (1,), over_cap=(2,)), "doc-z": plan(30, (1,), over_cap=(2,))}, DOCS
    )

    assert [r.check_id for r in results] == ["P-001-doc-b", "P-001-doc-a", "P-001-doc-z"]
    assert "doc-z: " in results[-1].message  # no file name known: the id


async def test_a_warning_makes_the_status_a_review_not_a_pass() -> None:
    from app.services import calculation

    ctx = {"extracted": [], "documents": DOCS, "page_plans": {"doc-a": plan(30, range(1, 11), over_cap=range(11, 31))}}
    out = await calculation.run(ctx)

    assert out["math_status"] == "SPECIALIST_REVIEW_REQUIRED"
    assert [c["check_id"] for c in out["checks"]] == ["P-001-doc-a"]
