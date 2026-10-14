"""scripts/measured_results.py: the only door numbers about the project's performance may come through.

The rules under test are the claim-audit rules, written as code: a demo-mode run is not the product, a latency never travels
without its pass rate and run count, a p95 needs 20 runs, nothing that identifies a deployment is committed, and the page
checked into docs/ is exactly what the data renders to (so nobody can type a number into it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import REPO_ROOT, load_script

mr = load_script("measured_results.py")

CHECKED_IN = REPO_ROOT / "docs" / "MEASURED_RESULTS.md"


def e2e_report(*, mode: str = "live", runs: int = 10, fail: set[int] | None = None, case: str = "c",
               base_url: str = "https://cargoclear-ui-abc123-uc.a.run.app", corrections: bool = False) -> dict[str, Any]:
    fail = fail or set()
    out_runs = []
    for i in range(1, runs + 1):
        steps = {"create_bundle": 0.1, "analyze": 30.0 + i, "audit": 0.05}
        statuses = {"analyze": "MISSING_EVIDENCE" if case == "c" else "MATERIAL_CONTRADICTION"}
        if case == "c":
            steps["reassess"] = 20.0 + i
            statuses["reassess"] = "COMPLIANT_FOR_SUBMISSION"
        if corrections:
            steps["recompute"], steps["recompute_after_undo"] = 0.5, 0.6
            statuses["recompute"], statuses["recompute_after_undo"] = "SPECIALIST_REVIEW_REQUIRED", "MATERIAL_CONTRADICTION"
        out_runs.append({
            "index": i, "bundle_id": f"bnd-secret{i}", "steps": steps,
            "stages": {"analyze": {"preprocess": 2.0, "extract": 20.0 + i}}, "statuses": statuses,
            "failures": [f"POST /bundles/bnd-secret{i}/analyze -> 502 at https://internal.example/x"] if i in fail else [],
            "notes": {"checks": {"M-001": "MATERIAL"}},
        })
    return {
        "generated_at": "2026-11-02T10:15:00+00:00", "base_url": base_url, "case": case,
        "options": {"corrections": corrections, "expect_signer": None},
        "meta": {"app_mode": mode, "pipeline_engine": "native"},
        "summary": {"runs": runs}, "runs": out_runs,
    }


def smoke_report(*, model: str | None = "gemini-2.5-flash", failed: bool = False) -> dict[str, Any]:
    row_ok = {"name": "hs_code_header", "kind": "hs", "gating": True, "status": "OK", "iou": 0.8}
    row_bad = {"name": "total_net_weight_kg", "kind": "weight", "gating": True, "status": "MISMATCH", "iou": 0.7}
    rows = [row_ok, row_bad] if failed else [row_ok]
    run = {"check": {"rows": rows, "failed": ["total_net_weight_kg"] if failed else [], "iou_mean": 0.75},
           "stats": {"attempts": 1, "latency_ms": 12000, "prompt_tokens": 5000, "output_tokens": 900}}
    return {
        "generated_at": "2026-11-02T11:00:00+00:00", "runs": 2,
        "environment": {"project": "my-secret-project", "credential_source": "adc", "location": "asia-south1", "model": model,
                        "sdk_version": "1.2.3", "pages": "png", "page_image_mode": "bw", "preprocess_deskew": False,
                        "thinking_budget": 0},
        "documents": [{"file": "commercial_invoice.pdf", "document_id": "doc-x", "has_expectations": True, "runs": [run, run],
                       "agreement": {"fields": 10, "identical_every_run": 9, "pct": 90.0, "disagreeing": {"x": ["1", "2"]}}}],
    }


def ingest(tmp_path: Path, report: dict[str, Any], label: str, **kw: Any) -> dict[str, Any]:
    raw = tmp_path / f"raw-{label}.json"
    raw.write_text(json.dumps(report))
    target = mr.ingest(raw, label, kw.get("model"), kw.get("note"), tmp_path / "measurements")
    return json.loads(target.read_text())


# --- sanitizing -------------------------------------------------------------------------------------------------------


def test_nothing_that_identifies_a_deployment_survives_ingest(tmp_path: Path) -> None:
    e2e = ingest(tmp_path, e2e_report(fail={2}), "hosted-c", model="gemini-2.5-flash")
    smoke = ingest(tmp_path, smoke_report(), "smoke")
    text = json.dumps(e2e) + json.dumps(smoke)
    for secret in ("bnd-secret", "a.run.app", "https://", "internal.example", "my-secret-project", "credential_source", "doc-x"):
        assert secret not in text, secret
    assert e2e["stack"] == {"where": "hosted", "app_mode": "live", "pipeline_engine": "native"}
    assert "<url>" in e2e["runs"][1]["failures"][0] and "<bnd-id>" in e2e["runs"][1]["failures"][0]


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("ConnectError: cargoclear-ui-ab12.a.run.app: name not resolved", "run.app"),
        ("403 for cargoclear-tasks-sa@my-proj-123.iam.gserviceaccount.com", "my-proj-123"),
        ("permission denied on projects/my-secret-project/locations/asia-south1", "my-secret-project"),
        ("could not connect to 10.20.30.40:443", "10.20.30.40"),
        ("project 123456789012 has no quota", "123456789012"),
        ("tried https://x.example.com/api/v1/bundles/bnd-abc123/analyze", "example.com"),
        ("DNS failure for api.internal", "api.internal"),
        ("timeout talking to cargoclear.example.io", "example.io"),
    ],
)
def test_the_sanitizer_removes_hosts_accounts_projects_addresses_and_ids_from_failure_text(text: str, gone: str) -> None:
    redacted = mr._redact(text)
    assert gone not in redacted, redacted
    assert "<" in redacted


def test_the_sanitizer_leaves_ordinary_failure_text_readable() -> None:
    text = "M-001 is PASS after the correction; expected MATERIAL for heat TH-77121 in case_d_mtc_test_cert.pdf"
    assert mr._redact(text) == text


def test_a_measurement_is_never_overwritten_and_the_same_report_ingested_twice_is_accepted(tmp_path: Path) -> None:
    failing = e2e_report(fail={1, 2, 3, 4})
    first = ingest(tmp_path, failing, "hosted-c")
    again = ingest(tmp_path, failing, "hosted-c")  # the same report: the same file, nothing lost
    assert again == first

    rerun = e2e_report()  # the operator runs again until it passes, then tries to record it under the same label and time
    raw = tmp_path / "rerun.json"
    raw.write_text(json.dumps(rerun))
    directory = tmp_path / "measurements"
    with pytest.raises(ValueError, match="already exists with different content"):
        mr.ingest(raw, "hosted-c", None, None, directory)
    kept = next(directory.glob("*hosted-c.json"))
    assert sum(r["ok"] for r in json.loads(kept.read_text())["runs"]) == 6, "the failing run is still on record"


def test_a_second_run_at_another_time_is_a_second_measurement(tmp_path: Path) -> None:
    earlier = e2e_report(fail={1, 2, 3, 4})
    later = {**e2e_report(), "generated_at": "2026-11-02T14:00:00+00:00"}
    ingest(tmp_path, earlier, "hosted-c")
    ingest(tmp_path, later, "hosted-c")
    names = sorted(p.name for p in (tmp_path / "measurements").glob("*.json"))
    assert names == ["20261102T101500-e2e-hosted-c.json", "20261102T140000-e2e-hosted-c.json"]
    page = mr.render(mr.load_measurements(tmp_path / "measurements"))
    assert "6 of 10" in page and "10 of 10" in page, "both are on the page: the one that failed is not hidden by the one that passed"


def test_a_local_stack_is_recorded_as_local(tmp_path: Path) -> None:
    assert ingest(tmp_path, e2e_report(base_url="http://127.0.0.1:8080"), "l")["stack"]["where"] == "local"
    assert mr.host_kind("http://localhost:3000") == "local" and mr.host_kind("https://x.run.app") == "hosted"


def test_a_report_of_unknown_shape_is_refused(tmp_path: Path) -> None:
    raw = tmp_path / "x.json"
    raw.write_text(json.dumps({"hello": 1}))
    with pytest.raises(ValueError, match="not a live_e2e_hosted"):
        mr.ingest(raw, "x", None, None, tmp_path / "m")


def test_an_old_report_without_a_case_is_classified_by_its_steps(tmp_path: Path) -> None:
    report = e2e_report(case="c")
    del report["case"], report["options"]
    assert ingest(tmp_path, report, "old")["case"] == "c"
    report = e2e_report(case="d")
    del report["case"], report["options"]
    assert ingest(tmp_path, report, "old-d")["case"] == "d"


# --- what may be quoted ------------------------------------------------------------------------------------------------


def test_a_demo_mode_run_is_never_quotable(tmp_path: Path) -> None:
    m = ingest(tmp_path, e2e_report(mode="demo"), "demo")
    ok, reasons = mr.quotable(m)
    assert not ok and "demo mode" in reasons[0]
    page = mr.render([{**m, "_file": "x.json"}])
    assert "May be quoted as" not in page and "Not quotable as the product's performance" in page


def test_a_live_run_is_quotable_with_its_run_count_and_pass_rate(tmp_path: Path) -> None:
    m = ingest(tmp_path, e2e_report(fail={3}), "live", model="gemini-2.5-flash")
    ok, _ = mr.quotable(m)
    assert ok
    n = mr.e2e_numbers(m)
    assert (n["runs"], n["passed"]) == (10, 9)
    sentence = mr.e2e_sentence(m, n)
    assert "9 of 10 runs met every expectation" in sentence
    assert "over 9 runs" in sentence, "the latency states the runs behind it, failed ones excluded"
    assert "gemini-2.5-flash (as declared by the operator)" in sentence and "synthetic documents" in sentence


def test_failed_runs_are_counted_but_kept_out_of_the_timings(tmp_path: Path) -> None:
    m = ingest(tmp_path, e2e_report(fail={1}), "live")  # run 1 was the fastest (31.0 s) and failed
    analyze = mr.e2e_numbers(m)["steps"]["analyze"]
    assert analyze["n"] == 9 and analyze["min"] == 32.0, "a failed run does not enter the timings..."
    assert mr.e2e_numbers(m)["failures"], "...and it is listed as a failure, not dropped"
    assert "x1" in mr.render([{**m, "_file": "f.json"}])


def test_few_runs_are_shown_but_never_offered_as_a_sentence(tmp_path: Path) -> None:
    ok, reasons = mr.quotable(ingest(tmp_path, e2e_report(runs=3), "few"))
    assert not ok and "fewer than 5 runs" in reasons[0]


def test_p95_needs_twenty_runs(tmp_path: Path) -> None:
    assert "p95" not in mr.e2e_numbers(ingest(tmp_path, e2e_report(runs=10), "ten"))["steps"]["analyze"]
    twenty = mr.e2e_numbers(ingest(tmp_path, e2e_report(runs=20), "twenty"))["steps"]["analyze"]
    assert (twenty["p95"], twenty["max"], twenty["median"]) == (49.0, 50.0, 40.5), "from 20 runs the p95 is a different number from the maximum"


def test_the_two_recomputes_are_reported_apart(tmp_path: Path) -> None:
    m = ingest(tmp_path, e2e_report(case="d", corrections=True), "dc")
    steps = mr.e2e_numbers(m)["steps"]
    assert steps["recompute"]["median"] == 0.5 and steps["recompute_after_undo"]["median"] == 0.6
    page = mr.render([{**m, "_file": "f.json"}])
    assert "with a correction, recompute and pre-fill download" in page and "SPECIALIST_REVIEW_REQUIRED x10" in page


def test_an_extraction_accuracy_sentence_carries_its_corpus(tmp_path: Path) -> None:
    m = ingest(tmp_path, smoke_report(failed=True), "smoke")
    page = mr.render([{**m, "_file": "s.json"}])
    assert "met 2 of 4 gating expectations" in page, "two rows over two runs, one of the two rows wrong in both runs"
    assert "not accuracy on real scanned documents" in page and "text PDFs, not scans" in page
    assert m["environment"]["model"] == "gemini-2.5-flash" and "project" not in m["environment"]


def test_an_extraction_that_errored_counts_as_meeting_nothing_and_the_sentence_says_so(tmp_path: Path) -> None:
    report = smoke_report()
    run_ok = report["documents"][0]["runs"][0]
    report["documents"][0]["runs"] = [run_ok, run_ok, {"error": {"type": "UpstreamError"}}, {"error": {"type": "UpstreamError"}}]
    m = ingest(tmp_path, report, "smoke-errors")
    n = mr.extraction_numbers(m)["documents"][0]
    assert (n["runs"], n["errors"], n["gating_ok"], n["gating_total"]) == (4, 2, 2, 4), "two runs of one expectation each: two errored runs meet none"
    page = mr.render([{**m, "_file": "s.json"}])
    assert "met 2 of 4 gating expectations" in page
    assert "2 of 4 extraction runs ended in an error and count as meeting none of theirs" in page


def test_a_smoke_report_that_names_no_model_is_not_quotable(tmp_path: Path) -> None:
    ok, reasons = mr.quotable(ingest(tmp_path, smoke_report(model=None), "nomodel"))
    assert not ok and "does not name the model" in reasons[0]


# --- the blank layer ----------------------------------------------------------------------------------------------------


def test_with_no_measurement_the_page_says_what_is_missing() -> None:
    page = mr.render([])
    assert page.count("None recorded.") == 2
    for gap in ("Case C end to end on a live stack", "Case D end to end", "Extraction accuracy of the real model",
                "grayscale against 1-bit", "deskew A/B", "real customer documents"):
        assert gap in page


def test_a_demo_run_does_not_fill_a_gap(tmp_path: Path) -> None:
    demo = ingest(tmp_path, e2e_report(mode="demo"), "demo")
    assert any("Case C end to end on a live stack" in line for line in mr.not_yet_measured([demo]))
    live = ingest(tmp_path, e2e_report(), "live")
    assert not any("Case C end to end on a live stack" in line for line in mr.not_yet_measured([live]))


# --- the checked-in page is the data's rendering, nothing else ------------------------------------------------------------


def test_the_checked_in_page_is_exactly_what_the_data_renders_to() -> None:
    rendered = mr.render(mr.load_measurements())
    assert CHECKED_IN.read_text(encoding="utf-8") == rendered, (
        "docs/MEASURED_RESULTS.md was edited by hand or the data changed: run `python3 scripts/measured_results.py render`"
    )


def test_render_check_exit_codes(tmp_path: Path) -> None:
    out, data = tmp_path / "M.md", tmp_path / "measurements"
    data.mkdir()
    assert mr.main(["render", "--check", "--dir", str(data), "--out", str(out)]) == 1, "missing file is out of date"
    assert mr.main(["render", "--dir", str(data), "--out", str(out)]) == 0
    assert mr.main(["render", "--check", "--dir", str(data), "--out", str(out)]) == 0
    out.write_text(out.read_text() + "\nQuick win: 99 % faster\n")
    assert mr.main(["render", "--check", "--dir", str(data), "--out", str(out)]) == 1


def test_every_committed_measurement_is_sanitized_and_known() -> None:
    for path in sorted((REPO_ROOT / "docs" / "measurements").glob("*.json")):
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        assert data["schema"] == mr.SCHEMA, path.name
        for forbidden in ("https://", "http://", "bnd-", "run.app", "credential", "project"):
            assert forbidden not in text, f"{path.name} contains {forbidden!r}"
