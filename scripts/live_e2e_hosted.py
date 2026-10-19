#!/usr/bin/env python3
"""End-to-end check of the Case C journey against a RUNNING stack (hosted on Cloud Run, or local). HTTP only.

    python3 scripts/live_e2e_hosted.py --base-url https://<ui-service>.run.app [options]

It does exactly what a user does, through the public front door (the UI's /api/proxy), and checks what the product
promises:

  1. GET  /meta                         reports the mode (live/demo) the stack runs in
  2. POST /bundles + 3 uploads          Commercial Invoice, Bill of Lading, Packing List (fixtures/case_c: SYNTHETIC)
  3. POST /analyze, watch /stream       -> status MISSING_EVIDENCE, with the Mill Test Certificate requirement
  4. upload the Mill Test Certificate, POST /reassess
                                         -> status COMPLIANT_FOR_SUBMISSION, and a Reasoning Delta naming the new document
  5. GET  /audit                        the hash chain verifies, and the lifecycle events are in the right order

and it MEASURES: every step's wall time, the time each pipeline stage was current (from the SSE status events), and,
with --runs N, the median and slowest of the analysis (and the p95 from 20 runs). Those numbers, ingested by
scripts/measured_results.py into docs/MEASURED_RESULTS.md, are what a pitch may quote; nothing else is.

    synthetic Case C documents only: do not run it on real customer documents

Where it can point:
  UI (public) ....... --base-url https://<ui>.run.app                       (default prefix /api/proxy; no token needed)
  API directly ...... --base-url https://<api>.run.app --prefix /api/v1 --token-env TOKEN
                      the API is private: TOKEN="$(gcloud auth print-identity-token --audiences=https://<api>.run.app)"
  local ............. --base-url http://localhost:3000   (or :8080 --prefix /api/v1)

Options:
  --case c|d                c (default): the India -> Singapore journey above. d: the India IMPORT: a bundle with destination IN, the
                            four fixtures/case_d documents, ONE analysis; expects MATERIAL_CONTRADICTION (M-001 names heat
                            TH-77121 and chromium 0.35 %), M-003 and the invoice checks PASS, SEC-002 a WARN, an ESTIMATED
                            valuation, and a verified audit chain. In live mode it needs the India tariff rows
                            (infra/bigquery/setup_tariff.sh) and real extraction of the certificate table.
  --expect-signer kms|local-demo
                            fail unless the audit chain head is SIGNED by that signer (the API verifies the signature; a KMS one
                            against the key's public half fetched from KMS). Without it the script still fails if signing is
                            configured and the head is not SIGNED, or if a signing failure is recorded.
  --corrections             with --case d (Phase 2): after the analysis, correct the chromium cell of heat TH-77121 to 0.28, RECOMPUTE
                            (no document is read, no model is called: the time is reported as recompute_seconds), expect M-001 to pass
                            and the Reasoning Delta to name the correction, download the declaration pre-fill pack (JSON: schema id,
                            integrity hash recomputed from the file alone, audit chain verified; PDF: a real PDF), undo the correction and
                            expect the contradiction back.
  --expect-mode live|demo   default: whatever /meta says; with a value the run fails if the stack disagrees
  --runs N                  repeat the whole journey N times (default 1), each on a fresh bundle
  --timeout SECONDS         per analysis (default 900; the API's own run deadline is 1200)
  --out FILE                JSON report (default ./live-e2e-report.json, git-ignored)

Exit code: 0 only if every expectation held on every run; 1 = an expectation failed or a step errored; 2 = bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_C_DIR = (REPO_ROOT / "samples" / "case_c") if (REPO_ROOT / "samples" / "case_c").is_dir() else (REPO_ROOT / "fixtures" / "case_c")
PRELOADED = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf")
MTC = "mtc_pipe_test_cert.pdf"
CASE_D_DIR = (REPO_ROOT / "samples" / "case_d") if (REPO_ROOT / "samples" / "case_d").is_dir() else (REPO_ROOT / "fixtures" / "case_d")
CASE_D_DOCUMENTS = (
    "case_d_commercial_invoice.pdf", "case_d_bill_of_lading.pdf", "case_d_packing_list.pdf", "case_d_mtc_test_cert.pdf",
)
MTC_REQUIREMENT = "ME-MILL_TEST_CERTIFICATE"
MIN_RUNS_FOR_P95 = 20
EXPECTED_EVENT_ORDER = ["BUNDLE_CREATED", "DOCUMENT_UPLOADED", "ANALYSIS_STARTED", "ASSESSMENT_COMPLETED"]
TERMINAL = ("COMPLETE", "ERROR")


class JourneyError(Exception):
    """A step failed in a way that makes the rest of the run meaningless."""


@dataclass
class RunReport:
    index: int
    bundle_id: str | None = None
    steps: dict[str, float] = field(default_factory=dict)       # step name -> seconds
    stages: dict[str, dict[str, float]] = field(default_factory=dict)  # per analysis: stage -> seconds it was current
    statuses: dict[str, str] = field(default_factory=dict)      # "analyze"/"reassess" -> final status
    failures: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failures


def expect(report: RunReport, condition: bool, message: str) -> bool:
    if not condition:
        report.failures.append(message)
    return condition


def describe(response: httpx.Response) -> str:
    try:
        body = response.json()
        return f"{body.get('code', response.status_code)}: {body.get('message', response.reason_phrase)}"
    except ValueError:
        return f"HTTP {response.status_code}"


class Api:
    """The few calls the journey makes, with one error type and timing."""

    def __init__(self, client: httpx.AsyncClient, prefix: str) -> None:
        self.client, self.prefix = client, prefix.rstrip("/")

    def url(self, path: str) -> str:
        return f"{self.prefix}{path}"

    async def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.client.request(method, self.url(path), **kwargs)
        except httpx.HTTPError as exc:
            raise JourneyError(f"{method} {path}: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            raise JourneyError(f"{method} {path} -> {response.status_code} {describe(response)}")
        return response

    async def upload(self, bundle_id: str, filename: str, directory: Path | None = None) -> dict[str, Any]:
        data = ((directory or CASE_C_DIR) / filename).read_bytes()
        response = await self.call(
            "POST", f"/bundles/{bundle_id}/documents", files={"file": (filename, data, "application/pdf")}
        )
        return response.json()


async def iter_sse(response: httpx.Response):
    """Yield (event name, parsed JSON data) from an SSE response."""
    event, data = "message", []
    async for line in response.aiter_lines():
        if line == "":
            if data:
                try:
                    yield event, json.loads("\n".join(data))
                except ValueError:
                    pass
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
        # ": ping" comments and anything else are ignored


async def watch_run(api: Api, bundle_id: str, run_id: str, timeout: float) -> tuple[dict[str, Any], dict[str, float]]:
    """Follow the SSE stream until THIS run is COMPLETE or ERROR.

    Returns (the terminal status event, {stage: seconds the stage was current}). Reconnects if the stream drops (the UI
    proxy closes long streams at the request timeout, and the browser would reconnect too).
    """
    started = time.monotonic()
    deadline = started + timeout
    seen: list[tuple[float, str | None]] = []  # (time, stage) per status event of this run
    last: dict[str, Any] = {}

    while time.monotonic() < deadline:
        try:
            async with api.client.stream("GET", api.url(f"/bundles/{bundle_id}/stream"), timeout=None) as response:
                if response.status_code >= 400:
                    raise JourneyError(f"GET /bundles/{bundle_id}/stream -> {response.status_code}")
                async for event, data in iter_sse(response):
                    if time.monotonic() > deadline:
                        break
                    if event == "error":
                        raise JourneyError(f"the stream reported an error: {data.get('message')}")
                    if event != "status" or data.get("run_id") != run_id:
                        continue  # a replay of an older run, or an iteration event
                    last = data
                    now = time.monotonic() - started
                    if not seen or seen[-1][1] != data.get("stage"):
                        seen.append((now, data.get("stage")))
                    if data.get("state") in TERMINAL:
                        seen.append((now, None))
                        return last, _stage_seconds(seen)
        except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError):
            pass  # reconnect below
        await asyncio.sleep(1.0)

    raise JourneyError(f"run {run_id} did not finish within {timeout:.0f}s (last status: {last or 'none'})")


def _stage_seconds(seen: list[tuple[float, str | None]]) -> dict[str, float]:
    stages: dict[str, float] = {}
    for (start, stage), (end, _next) in zip(seen, seen[1:], strict=False):  # pairs of neighbours: one fewer than seen
        if stage:
            stages[stage] = round(stages.get(stage, 0.0) + (end - start), 2)
    return stages


async def timed(report: RunReport, name: str, work):
    started = time.monotonic()
    try:
        return await work
    finally:
        report.steps[name] = round(time.monotonic() - started, 3)


async def analyse(api: Api, report: RunReport, bundle_id: str, kind: str, timeout: float, label: str | None = None) -> dict[str, Any]:
    """POST /analyze, /reassess or /recompute, follow the run, return the resulting assessment.

    ``label`` names the measurement when one journey makes the same call twice (the recompute and the recompute after the
    undo): without it the second would silently replace the first one's time, stages and status in the report.
    """
    name = label or kind
    started = time.monotonic()
    run = (await api.call("POST", f"/bundles/{bundle_id}/{kind}", json={"mode": "full"})).json()
    final, stages = await watch_run(api, bundle_id, run["run_id"], timeout)
    report.steps[name] = round(time.monotonic() - started, 3)
    report.stages[name] = stages
    if final.get("state") != "COMPLETE":
        raise JourneyError(f"{name} ended in {final.get('state')}: {final.get('message')}")
    assessment = (await api.call("GET", f"/bundles/{bundle_id}/assessment")).json()
    report.statuses[name] = assessment["status"]
    return assessment


async def run_journey(api: Api, index: int, args: argparse.Namespace, meta: dict[str, Any]) -> RunReport:
    report = RunReport(index=index)
    try:
        bundle = await timed(report, "create_bundle", api.call(
            "POST", "/bundles", json={"reference": f"E2E-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{index}", "destination_country": "SG"}))
        report.bundle_id = bundle.json()["id"]

        for filename in PRELOADED:
            await timed(report, f"upload:{filename}", api.upload(report.bundle_id, filename))

        first = await analyse(api, report, report.bundle_id, "analyze", args.timeout)
        expect(report, first["status"] == "MISSING_EVIDENCE", f"first status is {first['status']}, expected MISSING_EVIDENCE")
        missing = [item["id"] for item in first.get("missing_evidence", [])]
        expect(report, MTC_REQUIREMENT in missing, f"{MTC_REQUIREMENT} is not among the missing evidence: {missing}")
        expected_source = "live" if meta.get("app_mode") == "live" else "fixture"
        expect(report, first.get("data_source") == expected_source,
               f"data_source is {first.get('data_source')!r}, expected {expected_source!r}")
        report.notes["first_checks"] = {c["check_id"]: c["severity"] for c in first.get("checks", [])}
        report.notes["first_confidence"] = (first.get("confidence") or {}).get("action")

        await timed(report, f"upload:{MTC}", api.upload(report.bundle_id, MTC))
        second = await analyse(api, report, report.bundle_id, "reassess", args.timeout)
        expect(report, second["status"] == "COMPLIANT_FOR_SUBMISSION",
               f"second status is {second['status']}, expected COMPLIANT_FOR_SUBMISSION")
        delta = second.get("reasoning_delta") or {}
        expect(report, delta.get("kind") == "REASSESSMENT", f"reasoning delta kind is {delta.get('kind')!r}")
        expect(report, MTC in (delta.get("narrative") or ""), "the Reasoning Delta narrative does not name the uploaded certificate")
        expect(report, second.get("iteration") == first.get("iteration", 0) + 1,
               f"iteration numbers are {first.get('iteration')} then {second.get('iteration')}")
        report.notes["second_checks"] = {c["check_id"]: c["severity"] for c in second.get("checks", [])}
        report.notes["second_confidence"] = (second.get("confidence") or {}).get("action")

        audit = (await timed(report, "audit", api.call("GET", f"/bundles/{report.bundle_id}/audit"))).json()
        expect(report, audit.get("verified") is True, f"the audit chain did not verify: {audit.get('error')}")
        types = [event["event_type"] for event in audit.get("events", [])]
        report.notes["audit_events"] = types
        cursor = 0
        for wanted in EXPECTED_EVENT_ORDER:
            try:
                cursor = types.index(wanted, cursor) + 1
            except ValueError:
                expect(report, False, f"audit event {wanted} is missing or out of order: {types}")
                break
        expect(report, "ANALYSIS_FAILED" not in types, "an ANALYSIS_FAILED event is in the audit chain")
        check_signature(report, args, audit)
    except JourneyError as exc:
        report.failures.append(str(exc))
    return report


def check_signature(report: RunReport, args: argparse.Namespace, audit: dict[str, Any]) -> None:
    """The audit head must be signed when signing is configured, and (--expect-signer) by the signer the operator expects.

    A KMS signature is verified BY THE API against the key's public half fetched from KMS: status SIGNED means that
    verification held, so the check here is on what the API reports, not a second verification.
    """
    signature = audit.get("signature") or {}
    report.notes["audit_signature"] = {k: signature.get(k) for k in ("status", "signer", "key", "signed_seq", "unsigned_events", "failures")}
    wanted = getattr(args, "expect_signer", None)
    if wanted:
        expect(report, signature.get("signer") == wanted, f"the audit head is signed by {signature.get('signer')!r}, expected {wanted!r}")
        expect(report, signature.get("status") == "SIGNED", f"the audit signature status is {signature.get('status')}, expected SIGNED")
    elif signature.get("configured"):
        expect(report, signature.get("status") == "SIGNED", f"signing is configured but the audit signature status is {signature.get('status')}")
    expect(report, not signature.get("failures"), f"{signature.get('failures')} audit signing failure(s) are recorded in the chain")


def _normalised_heat(raw: Any) -> str:
    return "".join(ch for ch in str(raw or "").upper() if ch.isalnum())


async def correct_and_recompute(api: Api, report: RunReport, args: argparse.Namespace) -> None:
    """Phase 2: the agent corrects the chromium cell, the checks re-run on the stored extraction, the pre-fill pack follows.

    Expects the first analysis to have been Case D's MATERIAL_CONTRADICTION (heat TH-77121, Cr 0.35). Corrects that cell to
    0.28, recomputes (no document is read, no model is called: the recompute time is reported), checks that M-001 now passes,
    that the pack (JSON and PDF) carries the correction and its integrity hash can be recomputed from the file alone, then
    undoes the correction and expects the contradiction back.
    """
    bundle_id = report.bundle_id
    assert bundle_id is not None
    docs = (await api.call("GET", f"/bundles/{bundle_id}/extractions")).json()
    cell = next(
        ((d["document_id"], i, row) for d in docs for i, row in enumerate(d.get("test_results", []))
         if _normalised_heat(row.get("heat_number")) == "TH77121" and str(row.get("parameter", "")).casefold() in ("cr", "chromium")),
        None,
    )
    if not expect(report, cell is not None, "the extraction has no Cr cell for heat TH-77121 to correct"):
        return
    document_id, row_index, row = cell
    report.notes["corrected_cell"] = {"path": f"test_results[{row_index}]", "model_read": row.get("value")}

    created = await timed(report, "correction", api.call(
        "POST", f"/bundles/{bundle_id}/corrections",
        json={"document_id": document_id, "path": f"test_results[{row_index}]", "value": "0.28", "reason": "live E2E: certificate prints 0.28"}))
    entry = created.json()
    expect(report, entry.get("kind") == "correction" and entry.get("value") == "0.28", f"the correction was recorded as {entry.get('kind')}/{entry.get('value')}")
    state = (await api.call("GET", f"/bundles/{bundle_id}/corrections")).json()
    expect(report, state.get("pending") == 1, f"pending is {state.get('pending')}, expected 1 before the recompute")

    second = await analyse(api, report, bundle_id, "recompute", args.timeout)
    report.notes["recompute_seconds"] = report.steps.get("recompute")
    checks = {c["check_id"]: c for c in second.get("checks", [])}
    expect(report, second.get("run_mode") == "recompute", f"run_mode is {second.get('run_mode')}, expected recompute")
    expect(report, (checks.get("M-001") or {}).get("severity") == "PASS", f"M-001 is {(checks.get('M-001') or {}).get('severity')} after the correction")
    expect(report, second["status"] != "MATERIAL_CONTRADICTION", "the verdict did not follow the corrected value")
    expect(report, [c.get("status") for c in second.get("corrections", [])] == ["applied"], f"corrections used: {second.get('corrections')}")
    delta = (second.get("reasoning_delta") or {}).get("narrative", "")
    expect(report, "authorised agent" in delta and "0.28" in delta, f"the Reasoning Delta does not name the correction: {delta[:200]}")

    pack = (await timed(report, "prefill_json", api.call("GET", f"/bundles/{bundle_id}/prefill"))).json()
    body = {k: v for k, v in pack.items() if k != "integrity"}
    recomputed = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    expect(report, pack.get("schema_id") == "cargoclear.declaration-prefill", f"schema_id is {pack.get('schema_id')}")
    expect(report, recomputed == (pack.get("integrity") or {}).get("content_sha256"), "the pack's integrity hash cannot be recomputed from the file")
    expect(report, [c.get("path") for c in pack.get("corrections", [])] == [f"test_results[{row_index}]"], "the pack does not list the correction")
    expect(report, (pack.get("provenance") or {}).get("audit_chain_verified") is True, "the pack says the audit chain did not verify")
    pdf = await timed(report, "prefill_pdf", api.call("GET", f"/bundles/{bundle_id}/prefill.pdf"))
    expect(report, pdf.content.startswith(b"%PDF-") and len(pdf.content) > 2000, "the PDF summary is not a PDF")

    await api.call("POST", f"/bundles/{bundle_id}/corrections/{entry['correction_id']}/revert", json={"reason": "live E2E: undo"})
    third = await analyse(api, report, bundle_id, "recompute", args.timeout, label="recompute_after_undo")
    expect(report, third["status"] == "MATERIAL_CONTRADICTION" and third.get("corrections") == [],
           f"after the undo the status is {third['status']} with corrections {third.get('corrections')}")


async def run_case_d(api: Api, index: int, args: argparse.Namespace, meta: dict[str, Any]) -> RunReport:
    """Case D: an India import. One analysis of four documents; the product must find the contradiction."""
    report = RunReport(index=index)
    try:
        bundle = await timed(report, "create_bundle", api.call(
            "POST", "/bundles", json={"reference": f"E2E-D-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{index}", "destination_country": "IN"}))
        report.bundle_id = bundle.json()["id"]
        for filename in CASE_D_DOCUMENTS:
            await timed(report, f"upload:{filename}", api.upload(report.bundle_id, filename, CASE_D_DIR))

        result = await analyse(api, report, report.bundle_id, "analyze", args.timeout)
        checks = {c["check_id"]: c for c in result.get("checks", [])}
        severities = {check_id: c["severity"] for check_id, c in checks.items()}
        report.notes["checks"] = severities
        expect(report, result["status"] == "MATERIAL_CONTRADICTION", f"status is {result['status']}, expected MATERIAL_CONTRADICTION")
        expect(report, result.get("missing_evidence") == [], f"evidence is missing: {[m['id'] for m in result.get('missing_evidence', [])]}")
        expected_source = "live" if meta.get("app_mode") == "live" else "fixture"
        expect(report, result.get("data_source") == expected_source, f"data_source is {result.get('data_source')!r}, expected {expected_source!r}")

        m001 = checks.get("M-001")
        expect(report, m001 is not None and m001["severity"] == "MATERIAL", f"M-001 is {severities.get('M-001')}, expected MATERIAL")
        if m001 is not None:
            expect(report, "TH-77121" in m001["message"] and "0.35" in m001["message"],
                   f"M-001 does not name heat TH-77121 / chromium 0.35: {m001['message'][:160]}")
        for passing in ("I-001", "I-002", "I-003", "M-003", "M-004", "E-origin"):
            expect(report, severities.get(passing) == "PASS", f"{passing} is {severities.get(passing)}: "
                   f"{(checks.get(passing) or {}).get('message', 'missing')[:140]}")
        expect(report, severities.get("SEC-002") == "WARN", f"SEC-002 is {severities.get('SEC-002')}, expected WARN")

        valuation = result.get("valuation") or {}
        report.notes["valuation"] = {k: valuation.get(k) for k in ("status", "assessable_value", "total_duty", "implied_hs_code")}
        expect(report, valuation.get("status") == "ESTIMATED", f"valuation is {valuation.get('status')}: {valuation.get('reason')}")
        expect(report, bool(valuation.get("assumptions")), "the estimate lists no assumption")

        if getattr(args, "corrections", False):
            await correct_and_recompute(api, report, args)

        audit = (await timed(report, "audit", api.call("GET", f"/bundles/{report.bundle_id}/audit"))).json()
        expect(report, audit.get("verified") is True, f"the audit chain did not verify: {audit.get('error')}")
        check_signature(report, args, audit)
    except JourneyError as exc:
        report.failures.append(str(exc))
    return report


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))], 2)


def summarise(reports: list[RunReport]) -> dict[str, Any]:
    # Timings of the runs that met every expectation only, the same rule as scripts/measured_results.py: the page and the console
    # must give one median. A failed run is counted ("passed" below), never timed.
    analyses = [r.steps["analyze"] for r in reports if r.ok and "analyze" in r.steps]
    reassessments = [r.steps["reassess"] for r in reports if r.ok and "reassess" in r.steps]
    out: dict[str, Any] = {"runs": len(reports), "passed": sum(r.ok for r in reports)}
    for name, values in (("analyze_seconds", analyses), ("reassess_seconds", reassessments)):
        if values:
            out[name] = {"n": len(values), "min": min(values), "p50": round(statistics.median(values), 3), "max": max(values)}
            if len(values) >= MIN_RUNS_FOR_P95:  # below this a "p95" is the maximum under another name
                out[name]["p95"] = percentile(values, 0.95)
    return out


def print_report(report: RunReport) -> None:
    print(f"\nrun {report.index}: bundle {report.bundle_id or '-'}  {'PASS' if report.ok else 'FAIL'}")
    for name, seconds in report.steps.items():
        print(f"  {name:<34} {seconds:>8.3f}s")
    for kind, stages in report.stages.items():
        print(f"  {kind} stages: " + ", ".join(f"{stage} {seconds:.1f}s" for stage, seconds in stages.items()))
    for kind, status in report.statuses.items():
        print(f"  {kind} -> {status}")
    for failure in report.failures:
        print(f"  FAILED: {failure}")


async def main_async(args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None = None) -> int:
    headers = {}
    if args.token_env:
        token = os.environ.get(args.token_env, "")
        if not token:
            print(f"environment variable {args.token_env} is empty", file=sys.stderr)
            return 2
        headers["Authorization"] = f"Bearer {token}"

    timeout = httpx.Timeout(120.0, read=120.0)
    async with httpx.AsyncClient(
        base_url=args.base_url, headers=headers, timeout=timeout, follow_redirects=False, transport=transport
    ) as client:
        api = Api(client, args.prefix)
        try:
            meta = (await api.call("GET", "/meta")).json()
        except JourneyError as exc:
            print(f"cannot reach the stack: {exc}", file=sys.stderr)
            return 1
        print(f"stack: {args.base_url}  mode={meta.get('app_mode')}  engine={meta.get('pipeline_engine')}")
        if args.expect_mode and meta.get("app_mode") != args.expect_mode:
            print(f"EXPECTED mode {args.expect_mode}, the stack runs {meta.get('app_mode')}", file=sys.stderr)
            return 1

        reports: list[RunReport] = []
        for index in range(1, args.runs + 1):
            report = await (run_case_d if args.case == "d" else run_journey)(api, index, args, meta)
            print_report(report)
            reports.append(report)

    summary = summarise(reports)
    print("\nsummary:", json.dumps(summary))
    Path(args.out).write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "case": args.case,
        "options": {"corrections": bool(getattr(args, "corrections", False)), "expect_signer": getattr(args, "expect_signer", None)},
        "meta": meta,
        "summary": summary,
        "runs": [r.__dict__ for r in reports],
    }, indent=2, default=str), encoding="utf-8")
    print(f"report: {args.out}")
    return 0 if all(r.ok for r in reports) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="live_e2e_hosted.py", description="End-to-end Case C check against a running stack.",
                                     epilog="Synthetic documents only. See the module docstring.")
    parser.add_argument("--base-url", required=True, help="origin of the stack, e.g. https://cargoclear-ui-xxxx.a.run.app")
    parser.add_argument("--prefix", default="/api/proxy", help="path prefix of the API (UI proxy: /api/proxy; API itself: /api/v1)")
    parser.add_argument("--token-env", help="name of an environment variable that holds a bearer (ID) token")
    parser.add_argument("--case", choices=["c", "d"], default="c", help="c: India -> Singapore (default); d: the India import")
    parser.add_argument("--expect-signer", choices=["kms", "local-demo"],
                        help="fail unless the audit chain head is SIGNED by this signer (kms: the Cloud KMS key; local-demo: the demo key)")
    parser.add_argument("--corrections", action="store_true",
                        help="with --case d: also correct the chromium cell, recompute, download the pre-fill pack, undo (Phase 2)")
    parser.add_argument("--expect-mode", choices=["live", "demo"], help="fail if the stack runs in another mode")
    parser.add_argument("--runs", type=int, default=1, help="repeat the journey N times (default 1)")
    parser.add_argument("--timeout", type=float, default=900.0, help="seconds to wait for one analysis (default 900)")
    parser.add_argument("--out", type=Path, default=Path("live-e2e-report.json"), help="JSON report path")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.corrections and args.case != "d":
        parser.error("--corrections needs --case d")
    if not args.prefix.startswith("/"):
        parser.error("--prefix must start with /")
    return args


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
