"""The A/B tooling for the model's input: degraded copies of the sample PDFs, grading them by name, comparing two reports."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.core.config import settings
from tests.helpers import REPO_ROOT, load_script

smoke = load_script("live_smoke_extraction.py")
make = load_script("make_degraded_scans.py")
compare = load_script("compare_smoke_reports.py")

needs_poppler = pytest.mark.skipif(
    shutil.which("pdftoppm") is None, reason="poppler is not installed"
)


@needs_poppler
def test_every_degradation_yields_a_one_page_image_pdf_with_the_same_page_size_as_a_clean_render() -> None:
    from pdf2image import convert_from_bytes

    source = (REPO_ROOT / "fixtures" / "case_c" / "commercial_invoice.pdf").read_bytes()
    clean = convert_from_bytes(source, dpi=200, fmt="png")[0]
    for how in make.DEGRADATIONS:
        pdf = make.degrade(source, how)
        pages = convert_from_bytes(pdf, dpi=200, fmt="png")
        assert pdf.startswith(b"%PDF") and len(pages) == 1, how
        expected = clean.size[::-1] if how.startswith("sideways") else clean.size  # a sideways scan is a landscape page
        assert pages[0].size == expected, how


@needs_poppler
def test_the_generator_writes_the_same_file_names_under_one_folder_per_degradation(tmp_path) -> None:
    code = make.main(["--out", str(tmp_path), "--docs", str(REPO_ROOT / "fixtures" / "case_c" / "packing_list.pdf"), "--only", "skew3", "blur"])
    assert code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["blur", "skew3"]
    assert (tmp_path / "skew3" / "packing_list.pdf").read_bytes().startswith(b"%PDF")
    assert (tmp_path / "skew3" / "packing_list.pdf").read_bytes() != (tmp_path / "blur" / "packing_list.pdf").read_bytes()


@needs_poppler
def test_a_degraded_copy_is_graded_by_its_name_but_only_when_asked(tmp_path) -> None:
    copy = tmp_path / "commercial_invoice.pdf"
    copy.write_bytes(make.degrade((REPO_ROOT / "fixtures" / "case_c" / "commercial_invoice.pdf").read_bytes(), "skew3"))
    stranger = tmp_path / "not_a_fixture.pdf"
    stranger.write_bytes(copy.read_bytes())

    [ungraded] = smoke.load_documents([copy])
    [graded] = smoke.load_documents([copy], as_fixtures=True)
    [unknown] = smoke.load_documents([stranger], as_fixtures=True)
    assert ungraded.expected is None, "by default only files in the fixtures folders have expectations"
    assert graded.expected is not None and graded.expected.doc_type == "COMMERCIAL_INVOICE"
    assert unknown.expected is None, "a name that is not a fixture's cannot be graded"


def test_both_fixture_folders_are_graded_case_d_included() -> None:
    [certificate] = smoke.load_documents([REPO_ROOT / "fixtures" / "case_d" / "case_d_mtc_test_cert.pdf"])
    assert certificate.expected is not None and certificate.expected.doc_type == "MILL_TEST_CERTIFICATE"
    assert certificate.expected.heat_numbers, "the Case D certificate's heats are expectations too"


def test_the_ab_options_set_the_preprocessing_and_are_reported(monkeypatch) -> None:
    args = smoke.parse_args(["--page-mode", "gray", "--deskew", "--as-fixtures"])
    assert (args.page_mode, args.deskew, args.as_fixtures) == ("gray", True, True)
    assert smoke.parse_args([]).page_mode is None and smoke.parse_args([]).deskew is False

    monkeypatch.setattr(settings, "page_image_mode", "gray")
    monkeypatch.setattr(settings, "preprocess_deskew", True)
    environment = smoke.environment("png")
    assert environment["page_image_mode"] == "gray" and environment["preprocess_deskew"] is True


def report(path: Path, mode: str, failed: dict[str, list[str]], deskew: bool = False) -> Path:
    path.write_text(json.dumps({
        "environment": {"page_image_mode": mode, "preprocess_deskew": deskew, "model": "m"},
        "documents": [{"file": name, "runs": [{"check": {"failed": names}}]} for name, names in failed.items()],
    }))
    return path


def test_two_reports_are_compared_expectation_by_expectation(tmp_path, capsys) -> None:
    a = report(tmp_path / "a.json", "bw", {"inv.pdf": ["weight", "hs"], "mtc.pdf": []})
    b = report(tmp_path / "b.json", "gray", {"inv.pdf": ["hs"], "mtc.pdf": ["heat TH-1"]})
    assert compare.main([str(a), str(b)]) == 0
    out = capsys.readouterr().out
    assert "A: a.json  page_image_mode=bw deskew=False" in out and "B: b.json  page_image_mode=gray deskew=False" in out
    assert "fails only in A: weight" in out and "fails only in B: heat TH-1" in out
    assert "failures only in A: 1   failures only in B: 1   (totals: A 2, B 2)" in out


def test_identical_reports_say_so_and_a_missing_document_is_named(tmp_path, capsys) -> None:
    a = report(tmp_path / "a.json", "bw", {"inv.pdf": ["x"]})
    same = report(tmp_path / "same.json", "gray", {"inv.pdf": ["x"]})
    compare.main([str(a), str(same)])
    assert "A and B are the same on every expectation." in capsys.readouterr().out

    other = report(tmp_path / "other.json", "gray", {"inv.pdf": ["x"], "extra.pdf": []})
    compare.main([str(a), str(other)])
    assert "extra.pdf: only in B" in capsys.readouterr().out


def test_a_failed_extraction_counts_as_failing_every_expectation_of_that_run(tmp_path, capsys) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"documents": [{"file": "inv.pdf", "runs": [{"error": {"message": "boom"}}]}]}))
    ok = report(tmp_path / "ok.json", "bw", {"inv.pdf": []})
    compare.main([str(ok), str(broken)])
    assert "fails only in B: (extraction failed)" in capsys.readouterr().out
