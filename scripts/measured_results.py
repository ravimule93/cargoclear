#!/usr/bin/env python3
"""The only source of numbers the project may quote about its own performance.

    python3 scripts/measured_results.py ingest live-e2e-report.json --label hosted-case-c [--model gemini-2.5-flash] [--note TEXT]
    python3 scripts/measured_results.py ingest report-20261101T101500Z.json --label smoke-bw      # a live_smoke_extraction.py report
    python3 scripts/measured_results.py render            # writes docs/MEASURED_RESULTS.md from docs/measurements/*.json
    python3 scripts/measured_results.py render --check    # exit 1 if docs/MEASURED_RESULTS.md is not what the data renders to

`ingest` copies a raw report into docs/measurements/ with everything that identifies a deployment removed (project, host,
bundle ids, credentials): the raw reports are git-ignored for that reason, the sanitized copies are meant to be committed.
`render` turns every file in that folder into docs/MEASURED_RESULTS.md. The page is generated: a test fails when it differs
from the data, so a number cannot be typed in by hand, and a run that did not happen cannot be quoted.

What the page refuses to do (the rules are code, see ``quotable``):

* a DEMO-mode run (synthetic extraction, no model call) is never presented as the product's latency or accuracy;
* a latency is shown with the number of runs behind it, a pass rate always sits next to it, and a p95 appears only from
  20 runs (below that it would be the maximum under another name);
* what has NOT been measured is listed, so an empty row is visible instead of silently missing.

No network, no credentials: it reads and writes local files only.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
MEASUREMENTS_DIR = REPO_ROOT / "docs" / "measurements"
OUTPUT = REPO_ROOT / "docs" / "MEASURED_RESULTS.md"
SCHEMA = "cargoclear.measurement/1"

MIN_RUNS_TO_QUOTE = 5      # fewer runs than this: the numbers are shown, never offered as a sentence
MIN_RUNS_FOR_P95 = 20      # below this a "p95" is just the maximum

CASES = {
    "c": "Case C (India to Singapore: three documents, then the certificate)",
    "d": "Case D (India import: four documents, one analysis)",
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"}


# ---------------------------------------------------------------------------
# ingest: raw report -> sanitized measurement
# ---------------------------------------------------------------------------


_REDACTIONS = (
    (re.compile(r"https?://\S+"), "<url>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),                                  # users and service accounts
    (re.compile(r"\bprojects/[\w.-]+"), "projects/<project>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b(?:[a-z0-9-]+\.)+(?:run\.app|googleapis\.com|appspot\.com|cloudfunctions\.net|internal|local|localhost)\b", re.I), "<host>"),
    (re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|dev|app|cloud)\b", re.I), "<host>"),  # any other bare hostname
    (re.compile(r"\b(bnd|doc|run)-[0-9A-Za-z-]+"), r"<\1-id>"),
    (re.compile(r"\b\d{9,}\b"), "<number>"),                                                    # project numbers
)


def _redact(text: str) -> str:
    """Failure text can quote a URL, a host, an account, a project, a bundle id or a document id; none of them belongs in a
    committed file."""
    text = str(text)
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text[:300]


def host_kind(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    return "local" if host in LOCAL_HOSTS else "hosted"


def sanitize_e2e(report: dict[str, Any], label: str, model: str | None = None, note: str | None = None) -> dict[str, Any]:
    meta = report.get("meta") or {}
    runs = []
    for run in report.get("runs", []):
        runs.append({
            "index": run.get("index"),
            "ok": not run.get("failures"),
            "steps": {k: round(float(v), 3) for k, v in (run.get("steps") or {}).items()},
            "stages": {
                kind: {k: round(float(v), 3) for k, v in (stages or {}).items()}
                for kind, stages in (run.get("stages") or {}).items()
            },
            "statuses": dict(run.get("statuses") or {}),
            "failures": [_redact(f) for f in run.get("failures") or []],
        })
    return {
        "schema": SCHEMA,
        "kind": "e2e",
        "label": label,
        "recorded_at": report.get("generated_at"),
        "tool": "scripts/live_e2e_hosted.py",
        "case": report.get("case") or _infer_case(report),
        "options": report.get("options") or {},
        "stack": {
            "where": host_kind(report.get("base_url", "")),
            "app_mode": meta.get("app_mode"),
            "pipeline_engine": meta.get("pipeline_engine"),
        },
        "declared": {"model": model, "note": note},
        "runs": runs,
    }


def _infer_case(report: dict[str, Any]) -> str:
    """Reports written before the case was recorded: Case D never reassesses."""
    return "c" if any("reassess" in (r.get("steps") or {}) for r in report.get("runs", [])) else "d"


def sanitize_smoke(report: dict[str, Any], label: str, note: str | None = None) -> dict[str, Any]:
    env = report.get("environment") or {}
    documents = []
    for doc in report.get("documents", []):
        runs = []
        for run in doc.get("runs", []):
            check = run.get("check") or {}
            runs.append({
                "error": (run.get("error") or {}).get("type"),
                "stats": run.get("stats") or {},
                "rows": [
                    {k: row.get(k) for k in ("name", "kind", "gating", "status", "iou")}
                    for row in check.get("rows", [])
                ],
                "failed": check.get("failed", []),
                "iou_mean": check.get("iou_mean"),
            })
        entry: dict[str, Any] = {"file": doc.get("file"), "has_expectations": bool(doc.get("has_expectations")), "runs": runs}
        if doc.get("agreement"):
            entry["agreement"] = {k: doc["agreement"].get(k) for k in ("fields", "identical_every_run", "pct")}
        documents.append(entry)
    return {
        "schema": SCHEMA,
        "kind": "extraction",
        "label": label,
        "recorded_at": report.get("generated_at"),
        "tool": "scripts/live_smoke_extraction.py",
        "environment": {
            k: env.get(k)
            for k in ("model", "location", "sdk_version", "pages", "page_image_mode", "preprocess_deskew", "thinking_budget")
        },
        "declared": {"model": env.get("model"), "note": note},
        "runs_per_document": report.get("runs"),
        "documents": documents,
    }


def sanitize(report: dict[str, Any], label: str, model: str | None, note: str | None) -> dict[str, Any]:
    if "documents" in report and "environment" in report:
        return sanitize_smoke(report, label, note)
    if "runs" in report and isinstance(report["runs"], list) and "summary" in report:
        return sanitize_e2e(report, label, model, note)
    raise ValueError("not a live_e2e_hosted.py report and not a live_smoke_extraction.py report")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "measurement"


def ingest(path: Path, label: str, model: str | None, note: str | None, directory: Path = MEASUREMENTS_DIR) -> Path:
    measurement = sanitize(json.loads(path.read_text(encoding="utf-8")), label, model, note)
    digits = re.sub(r"[^0-9]", "", str(measurement.get("recorded_at") or ""))
    stamp = f"{digits[:8]}T{digits[8:14]}" if len(digits) >= 14 else (digits[:8] or "undated")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stamp}-{measurement['kind']}-{slug(label)}.json"
    text = json.dumps(measurement, indent=2, sort_keys=True) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") != text:
        # A measurement is never replaced: a re-run that passes must not erase the run that failed. (The same report ingested
        # twice is the same file and is accepted.)
        raise ValueError(f"{target.name} already exists with different content; measurements are not overwritten")
    target.write_text(text, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# statistics (pure)
# ---------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def describe(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    out: dict[str, Any] = {"n": len(values), "min": min(values), "median": statistics.median(values), "max": max(values)}
    if len(values) >= MIN_RUNS_FOR_P95:
        out["p95"] = percentile(values, 0.95)
    return out


def e2e_numbers(m: dict[str, Any]) -> dict[str, Any]:
    runs = m["runs"]
    done = [r for r in runs if r["ok"]]
    series: dict[str, list[float]] = {}
    for run in done:
        for name, seconds in run["steps"].items():
            series.setdefault(name, []).append(seconds)
    stage_series: dict[str, dict[str, list[float]]] = {}
    for run in done:
        for kind, stages in run["stages"].items():
            for stage, seconds in stages.items():
                stage_series.setdefault(kind, {}).setdefault(stage, []).append(seconds)
    statuses: dict[str, Counter[str]] = {}
    for run in runs:
        for kind, status in run["statuses"].items():
            statuses.setdefault(kind, Counter())[status] += 1
    return {
        "runs": len(runs),
        "passed": len(done),
        "steps": {name: describe(values) for name, values in series.items()},
        "stages": {kind: {s: statistics.median(v) for s, v in stages.items()} for kind, stages in stage_series.items()},
        "statuses": statuses,
        "failures": Counter(f for r in runs for f in r["failures"]),
    }


def quotable(m: dict[str, Any]) -> tuple[bool, list[str]]:
    """Whether a measurement may be turned into a sentence, and the reasons it may not."""
    reasons: list[str] = []
    if m["kind"] == "e2e":
        if m["stack"].get("app_mode") != "live":
            reasons.append("demo mode: extraction is synthetic and no model is called, so this measures the pipeline's own overhead, "
                           "not the product")
        if len(m["runs"]) < MIN_RUNS_TO_QUOTE:
            reasons.append(f"fewer than {MIN_RUNS_TO_QUOTE} runs")
        if not any(r["ok"] for r in m["runs"]):
            reasons.append("no run passed")
    else:
        if not m["environment"].get("model"):
            reasons.append("the report does not name the model")
        if not any(d["has_expectations"] for d in m["documents"]):
            reasons.append("no document had expectations")
    return not reasons, reasons


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def sec(x: float | None) -> str:
    """Seconds, with milliseconds below one second (a recompute takes tens of milliseconds, not 0.02 of anything)."""
    if x is None:
        return "-"
    return f"{x:.3f} s" if abs(x) < 1 else f"{x:.2f} s"


def load_measurements(directory: Path = MEASUREMENTS_DIR) -> list[dict[str, Any]]:
    found = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise ValueError(f"{path.name}: unknown schema {data.get('schema')!r}")
        data["_file"] = path.name
        found.append(data)
    # a stable, readable order: kind, then case, plain before corrections, then label
    found.sort(key=lambda m: (m["kind"], m.get("case") or "", bool((m.get("options") or {}).get("corrections")), m["label"]))
    return found


def _stack_text(m: dict[str, Any]) -> str:
    s = m["stack"]
    return f"{s.get('app_mode') or '?'} mode, {s.get('where')}, engine {s.get('pipeline_engine') or '?'}"


def _case_text(m: dict[str, Any]) -> str:
    text = CASES.get(str(m.get("case")), str(m.get("case")))
    if (m.get("options") or {}).get("corrections"):
        text += " with a correction, recompute and pre-fill download"
    return text


def e2e_sentence(m: dict[str, Any], n: dict[str, Any]) -> str:
    analyze = (n["steps"].get("analyze") or {})
    parts = [
        f"{_case_text(m)}, {_stack_text(m)}: {n['passed']} of {n['runs']} runs met every expectation",
    ]
    if analyze:
        parts.append(f"analysis median {sec(analyze['median'])}, slowest {sec(analyze['max'])} over {analyze['n']} runs")
    reassess = n["steps"].get("reassess")
    if reassess:
        parts.append(f"reassessment median {sec(reassess['median'])}, slowest {sec(reassess['max'])}")
    declared = m["declared"].get("model")
    if declared:
        parts.append(f"model {declared} (as declared by the operator)")
    parts.append("synthetic documents, one deployment, " + (m["recorded_at"] or "undated")[:10])
    return "; ".join(parts) + "."


def render_e2e(m: dict[str, Any]) -> list[str]:
    n = e2e_numbers(m)
    ok, reasons = quotable(m)
    lines = [
        f"### {m['label']} ({m['_file']})",
        "",
        f"* Case: {_case_text(m)}",
        f"* Stack: {_stack_text(m)}; recorded {m['recorded_at']}; tool `{m['tool']}`",
        f"* Runs: **{n['passed']} of {n['runs']}** met every expectation",
    ]
    if m["declared"].get("model"):
        lines.append(f"* Model: {m['declared']['model']} (declared by the operator who ran it, not read from the stack)")
    if m["declared"].get("note"):
        lines.append(f"* Operator note: {m['declared']['note']}")
    lines += ["", "| Step (successful runs only) | n | min | median | max | p95 |", "|---|---|---|---|---|---|"]
    for name, d in n["steps"].items():
        if d:
            lines.append(f"| {name} | {d['n']} | {sec(d['min'])} | {sec(d['median'])} | {sec(d['max'])} | {sec(d.get('p95')) if 'p95' in d else 'n < 20'} |")
    for kind, stages in n["stages"].items():
        lines.append("")
        lines.append(f"Median time each pipeline stage was current during the {kind}: " + ", ".join(f"{s} {sec(v)}" for s, v in stages.items()))
    for kind, counter in n["statuses"].items():
        lines.append("")
        lines.append(f"Statuses reached by the {kind} (all runs): " + ", ".join(f"{s} x{c}" for s, c in sorted(counter.items())))
    if n["failures"]:
        lines += ["", "Failures:"] + [f"* {text} (x{count})" for text, count in sorted(n["failures"].items())]
    lines.append("")
    if ok:
        lines.append(f"**May be quoted as:** {e2e_sentence(m, n)}")
    else:
        lines.append("**Not quotable as the product's performance:** " + "; ".join(reasons) + ".")
    lines.append("")
    return lines


def extraction_numbers(m: dict[str, Any]) -> dict[str, Any]:
    per_doc = []
    for doc in m["documents"]:
        if not doc["has_expectations"]:
            continue
        gating_total = gating_ok = failed_runs = errors = 0
        rows_per_run = 0   # the gating expectations of a run that completed: what a run that errored out failed to meet
        latencies: list[float] = []
        prompt_tokens: list[float] = []
        output_tokens: list[float] = []
        ious: list[float] = []
        for run in doc["runs"]:
            if run.get("error"):
                errors += 1
                continue
            rows = [r for r in run["rows"] if r.get("gating")]
            rows_per_run = max(rows_per_run, len(rows))
            gating_total += len(rows)
            gating_ok += sum(r["status"] == "OK" for r in rows)
            failed_runs += bool(run["failed"])
            if run["stats"].get("latency_ms") is not None:
                latencies.append(run["stats"]["latency_ms"] / 1000)
            if run["stats"].get("prompt_tokens") is not None:
                prompt_tokens.append(run["stats"]["prompt_tokens"])
            if run["stats"].get("output_tokens") is not None:
                output_tokens.append(run["stats"]["output_tokens"])
            if run.get("iou_mean") is not None:
                ious.append(run["iou_mean"])
        per_doc.append({
            "file": doc["file"], "runs": len(doc["runs"]), "errors": errors, "failed_runs": failed_runs,
            "gating_total": gating_total + errors * rows_per_run, "gating_ok": gating_ok,   # an errored run met nothing
            "latency": describe(latencies), "prompt_tokens": describe(prompt_tokens), "output_tokens": describe(output_tokens),
            "iou_mean": round(statistics.mean(ious), 3) if ious else None,
            "agreement": doc.get("agreement"),
        })
    return {"documents": per_doc}


def render_extraction(m: dict[str, Any]) -> list[str]:
    n = extraction_numbers(m)
    env = m["environment"]
    ok, reasons = quotable(m)
    lines = [
        f"### {m['label']} ({m['_file']})",
        "",
        f"* Model {env.get('model')} in {env.get('location')}; pages as {env.get('pages')}; page mode **{env.get('page_image_mode')}**, "
        f"deskew **{'on' if env.get('preprocess_deskew') else 'off'}**; recorded {m['recorded_at']}",
        f"* {m['runs_per_document']} extraction(s) per document; corpus: the synthetic rendered fixtures (text PDFs, not scans)",
    ]
    if m["declared"].get("note"):
        lines.append(f"* Operator note: {m['declared']['note']}")
    lines += ["", "| Document | runs | gating expectations met | runs with a failure | extraction time (median / max) | prompt / output tokens (median) | box overlap (mean IoU) | identical across runs |",
              "|---|---|---|---|---|---|---|---|"]
    for d in n["documents"]:
        lat = d["latency"]
        agree = d["agreement"]
        errors_note = f" (+{d['errors']} errors)" if d["errors"] else ""
        lines.append(
            f"| {d['file']} | {d['runs']} | {d['gating_ok']} of {d['gating_total']} | {d['failed_runs']}{errors_note} | "
            f"{(sec(lat['median']) + ' / ' + sec(lat['max'])) if lat else '-'} | "
            f"{(str(int(d['prompt_tokens']['median'])) + ' / ' + str(int(d['output_tokens']['median']))) if d['prompt_tokens'] and d['output_tokens'] else '-'} | "
            f"{d['iou_mean'] if d['iou_mean'] is not None else '-'} | "
            f"{(str(agree['identical_every_run']) + ' of ' + str(agree['fields']) + ' fields') if agree else '-'} |"
        )
    lines.append("")
    if ok:
        met = sum(d["gating_ok"] for d in n["documents"])
        total = sum(d["gating_total"] for d in n["documents"])
        errored = sum(d["errors"] for d in n["documents"])
        runs = sum(d["runs"] for d in n["documents"])
        failed = f"; {errored} of {runs} extraction runs ended in an error and count as meeting none of theirs" if errored else ""
        lines.append(
            f"**May be quoted as:** on the synthetic rendered fixtures, model {env.get('model')} met {met} of {total} gating "
            f"expectations ({m['runs_per_document']} run(s) per document, page mode {env.get('page_image_mode')}, deskew "
            f"{'on' if env.get('preprocess_deskew') else 'off'}){failed}. This is not accuracy on real scanned documents."
        )
    else:
        lines.append("**Not quotable:** " + "; ".join(reasons) + ".")
    lines.append("")
    return lines


def not_yet_measured(measurements: list[dict[str, Any]]) -> list[str]:
    def have_e2e(case: str, corrections: bool = False) -> bool:
        return any(
            m["kind"] == "e2e" and m.get("case") == case and m["stack"].get("app_mode") == "live"
            and len(m["runs"]) >= MIN_RUNS_TO_QUOTE and bool((m.get("options") or {}).get("corrections")) == corrections
            for m in measurements
        )

    extraction = [m for m in measurements if m["kind"] == "extraction"]
    modes = {(m["environment"].get("page_image_mode"), bool(m["environment"].get("preprocess_deskew"))) for m in extraction}
    missing = []
    if not have_e2e("c"):
        missing.append("Case C end to end on a live stack (at least 5 runs): latency of the analysis and the reassessment, and that every run reaches the expected statuses")
    if not have_e2e("d"):
        missing.append("Case D end to end on a live stack (at least 5 runs)")
    if not have_e2e("d", corrections=True):
        missing.append("Case D with a correction, a recompute and the pre-fill download on a live stack (at least 5 runs): the recompute time")
    if not extraction:
        missing.append("Extraction accuracy of the real model on the fixtures (`live_smoke_extraction.py`)")
    if ("gray", False) not in modes or ("bw", False) not in modes:
        missing.append("The grayscale against 1-bit A/B on the real model (decides `PAGE_IMAGE_MODE`)")
    if ("bw", True) not in modes:
        missing.append("The deskew A/B on the real model, on the degraded scans (decides `PREPROCESS_DESKEW`)")
    missing.append("Behaviour with more than one instance (`RUN_DISPATCH=cloudtasks`): no measurement format exists for it yet; it is verified by the runbook, not measured")
    missing.append("Anything on real customer documents: nothing here was run on one")
    return missing


def render(measurements: list[dict[str, Any]]) -> str:
    e2e = [m for m in measurements if m["kind"] == "e2e"]
    extraction = [m for m in measurements if m["kind"] == "extraction"]
    out = [
        "# Measured results",
        "",
        "<!-- GENERATED by scripts/measured_results.py from docs/measurements/*.json. Do not edit by hand:",
        "     backend/tests/unit/test_measured_results.py fails when this file differs from what the data renders to. -->",
        "",
        "This page holds every number the project may quote about its own behaviour. A number that is not here is not a measurement.",
        "It is generated from the sanitized reports in [`docs/measurements/`](measurements/) (no project id, host, bundle id or credential).",
        "",
        "## Rules for quoting",
        "",
        "1. Quote the number **with** its run count, its mode and its corpus. \"Analysis takes 31 s\" is a claim; \"median 31 s over 10 live runs on three synthetic documents\" is a result.",
        "2. **Demo-mode runs are not the product's latency.** Demo mode reads no document and calls no model; its timings show only the cost of the pipeline around the model.",
        "3. A latency never travels without its pass rate. A slow run that failed is not removed to improve the median; failed runs are counted, and only runs that met every expectation enter the timings.",
        f"4. A p95 is shown from {MIN_RUNS_FOR_P95} runs. Below that it would be the maximum, and the maximum is shown as the maximum.",
        "5. All documents are synthetic, rendered from text, and are not scans. Nothing here says how the product reads a real, stamped, skewed scan.",
        "6. Stage times come from a 1 Hz event stream: a stage shorter than about a second may be credited to its neighbour. Only the step totals are exact.",
        "",
    ]
    out += ["## End-to-end runs (`live_e2e_hosted.py`)", ""]
    if e2e:
        out += ["| Measurement | Case | Stack | Runs passed | Analysis median | Analysis slowest | Quotable |", "|---|---|---|---|---|---|---|"]
        for m in e2e:
            n = e2e_numbers(m)
            a = n["steps"].get("analyze")
            ok, _ = quotable(m)
            out.append(
                f"| {m['label']} | {m.get('case', '?').upper()}{' + corrections' if (m.get('options') or {}).get('corrections') else ''} | "
                f"{_stack_text(m)} | {n['passed']} of {n['runs']} | {sec(a['median']) if a else '-'} | {sec(a['max']) if a else '-'} | {'yes' if ok else 'no'} |"
            )
        out.append("")
        for m in e2e:
            out += render_e2e(m)
    else:
        out += ["None recorded.", ""]
    out += ["## Extraction by the real model (`live_smoke_extraction.py`)", ""]
    if extraction:
        for m in extraction:
            out += render_extraction(m)
    else:
        out += ["None recorded.", ""]
    out += ["## Not yet measured", "", "Each line is a claim the project cannot make today.", ""]
    out += [f"* {line}" for line in not_yet_measured(measurements)]
    out += ["", "## How to add a measurement", "",
            "```bash", "python3 scripts/live_e2e_hosted.py --base-url https://<ui>.run.app --case c --runs 10 --expect-mode live",
            "python3 scripts/measured_results.py ingest live-e2e-report.json --label hosted-case-c --model <model id>",
            "python3 scripts/measured_results.py render", "```", "",
            "The same for `--case d`, `--case d --corrections` and a `live_smoke_extraction.py` report (`ingest` recognises the report by its shape).", ""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="measured_results.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_ingest = sub.add_parser("ingest", help="copy a raw report into docs/measurements/, sanitized")
    p_ingest.add_argument("report", type=Path)
    p_ingest.add_argument("--label", required=True, help="a short name, e.g. hosted-case-c")
    p_ingest.add_argument("--model", help="the model the stack was configured with (an e2e report cannot know it)")
    p_ingest.add_argument("--note", help="one line of context, e.g. the instance settings")
    p_ingest.add_argument("--dir", type=Path, default=MEASUREMENTS_DIR, help=argparse.SUPPRESS)
    p_render = sub.add_parser("render", help="write docs/MEASURED_RESULTS.md")
    p_render.add_argument("--check", action="store_true", help="do not write; exit 1 if the file is out of date")
    p_render.add_argument("--dir", type=Path, default=MEASUREMENTS_DIR, help=argparse.SUPPRESS)
    p_render.add_argument("--out", type=Path, default=OUTPUT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.command == "ingest":
        try:
            target = ingest(args.report, args.label, args.model, args.note, args.dir)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"cannot ingest {args.report}: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {target}")
        print("now: python3 scripts/measured_results.py render")
        return 0

    text = render(load_measurements(args.dir))
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is out of date: run `python3 scripts/measured_results.py render`", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date")
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
