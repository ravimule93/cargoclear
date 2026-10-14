"""scripts/live_e2e_hosted.py against a fake stack (an httpx MockTransport): no network, no credentials.

The real run is done by a person against Cloud Run (docs/GCP_VERIFICATION.md). Here the script's own logic is verified:
what it expects, what it reports as a failure, how it follows the SSE stream, and what it measures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import settings

from tests.helpers import load_script

REAL_SLEEP = asyncio.sleep  # the autouse fixture below replaces asyncio.sleep for the whole process

e2e = load_script("live_e2e_hosted.py")


def sse(*events: tuple[str, dict[str, Any]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def status(run_id: str, state: str, stage: str | None = None, message: str | None = None) -> tuple[str, dict[str, Any]]:
    return "status", {"kind": "status", "run_id": run_id, "state": state, "stage": stage, "message": message}


class FakeStack:
    """The API surface the journey uses. Each knob breaks one promise the product makes."""

    def __init__(self, *, mode: str = "demo", **overrides: Any) -> None:
        self.mode = mode
        self.first_status = "MISSING_EVIDENCE"
        self.second_status = "COMPLIANT_FOR_SUBMISSION"
        self.missing = ["ME-MILL_TEST_CERTIFICATE"]
        self.data_source = "live" if mode == "live" else "fixture"
        self.audit_verified = True
        self.audit_events = ["BUNDLE_CREATED", "DOCUMENT_UPLOADED", "ANALYSIS_STARTED", "ASSESSMENT_COMPLETED"]
        self.run_error: str | None = None
        self.narrative = "Uploaded mtc_pipe_test_cert.pdf (MILL_TEST_CERTIFICATE) satisfies the requirement."
        self.stream_drops = 0          # this many stream connections end before the run does
        self.fail_path: tuple[str, int] | None = None
        self.__dict__.update(overrides)
        self.runs = 0
        self.stream_calls = 0
        self.uploads: list[str] = []
        self.auth_headers: set[str | None] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/proxy")
        self.auth_headers.add(request.headers.get("authorization"))
        if self.fail_path and path == self.fail_path[0]:
            return httpx.Response(self.fail_path[1], json={"code": "UPSTREAM_ERROR", "message": "storage is down"})

        if path == "/meta":
            return httpx.Response(200, json={"app_mode": self.mode, "pipeline_engine": "native"})
        if path == "/bundles" and request.method == "POST":
            self.runs, self.stream_calls = 0, 0  # a new bundle starts from nothing
            return httpx.Response(201, json={"id": "bnd-1"})
        if path == "/bundles/bnd-1/documents":
            for name in (*e2e.PRELOADED, e2e.MTC):
                if f'filename="{name}"'.encode() in request.content:
                    self.uploads.append(name)
            return httpx.Response(201, json={"document_id": f"doc-{len(self.uploads)}"})
        if path in ("/bundles/bnd-1/analyze", "/bundles/bnd-1/reassess"):
            self.runs += 1
            return httpx.Response(202, json={"run_id": f"run-{self.runs}"})
        if path == "/bundles/bnd-1/stream":
            self.stream_calls += 1
            run = f"run-{self.runs}"
            replay = status(f"run-{self.runs - 1}", "COMPLETE") if self.runs > 1 else status("run-0", "COMPLETE")
            if self.stream_calls <= self.stream_drops:
                return httpx.Response(200, content=sse(replay, status(run, "RUNNING", "extract")))
            if self.run_error:
                return httpx.Response(200, content=sse(replay, status(run, "RUNNING", "extract"), status(run, "ERROR", None, self.run_error)))
            return httpx.Response(200, content=sse(
                replay, status(run, "RUNNING", "initializing"), status(run, "RUNNING", "extract"),
                status(run, "RUNNING", "discrepancy"), status(run, "COMPLETE"),
            ))
        if path == "/bundles/bnd-1/assessment":
            first = self.runs <= 1
            return httpx.Response(200, json={
                "iteration": 1 if first else 2,
                "status": self.first_status if first else self.second_status,
                "missing_evidence": [{"id": m} for m in self.missing] if first else [],
                "data_source": self.data_source,
                "checks": [{"check_id": "W-001", "severity": "PASS"}],
                "confidence": {"action": "AUTO_ACCEPT"},
                "reasoning_delta": None if first else {"kind": "REASSESSMENT", "narrative": self.narrative},
            })
        if path == "/bundles/bnd-1/audit":
            return httpx.Response(200, json={
                "verified": self.audit_verified, "error": None if self.audit_verified else "Tampered event payload at seq=3",
                "events": [{"event_type": t} for t in self.audit_events],
            })
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": f"no route {path}"})


def args_for(**overrides: Any) -> argparse.Namespace:
    values = dict(base_url="http://stack", prefix="/api/proxy", token_env=None, expect_mode=None, runs=1, case="c",
                  timeout=30.0, out=Path("unused.json"), corrections=False, expect_signer=None)
    values.update(overrides)
    return argparse.Namespace(**values)


async def journey(stack: FakeStack, **arg_overrides: Any):
    async with httpx.AsyncClient(base_url="http://stack", transport=httpx.MockTransport(stack.handler)) as client:
        api = e2e.Api(client, "/api/proxy")
        meta = (await api.call("GET", "/meta")).json()
        return await e2e.run_journey(api, 1, args_for(**arg_overrides), meta)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(e2e.asyncio, "sleep", instant)


# ---------------------------------------------------------------------------
# the journey
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stack_that_keeps_its_promises_passes_and_is_measured() -> None:
    stack = FakeStack()
    report = await journey(stack)

    assert report.ok, report.failures
    assert report.statuses == {"analyze": "MISSING_EVIDENCE", "reassess": "COMPLIANT_FOR_SUBMISSION"}
    assert stack.uploads == [*e2e.PRELOADED, e2e.MTC]  # the three first, the certificate only after the first analysis
    assert {"create_bundle", "analyze", "reassess", "audit"} <= set(report.steps)
    assert set(report.stages["analyze"]) == {"initializing", "extract", "discrepancy"}
    assert report.notes["audit_events"] == stack.audit_events


@pytest.mark.asyncio
async def test_each_broken_promise_is_reported() -> None:
    cases = [
        (dict(first_status="COMPLIANT_FOR_SUBMISSION"), "first status is COMPLIANT_FOR_SUBMISSION"),
        (dict(missing=[]), "ME-MILL_TEST_CERTIFICATE is not among the missing evidence"),
        (dict(second_status="MISSING_EVIDENCE"), "second status is MISSING_EVIDENCE"),
        (dict(data_source="fixture", mode="live"), "data_source is 'fixture', expected 'live'"),
        (dict(narrative="Nothing relevant happened."), "does not name the uploaded certificate"),
        (dict(audit_verified=False), "audit chain did not verify: Tampered event payload"),
        (dict(audit_events=["BUNDLE_CREATED", "ANALYSIS_STARTED", "DOCUMENT_UPLOADED", "ASSESSMENT_COMPLETED"]), "audit event"),
        (dict(audit_events=["BUNDLE_CREATED", "DOCUMENT_UPLOADED", "ANALYSIS_STARTED", "ANALYSIS_FAILED", "ASSESSMENT_COMPLETED"]), "ANALYSIS_FAILED"),
    ]
    for overrides, expected in cases:
        report = await journey(FakeStack(**overrides))
        assert not report.ok, overrides
        assert any(expected in failure for failure in report.failures), (overrides, report.failures)


@pytest.mark.asyncio
async def test_a_run_that_ends_in_error_fails_the_journey_with_the_runs_message() -> None:
    report = await journey(FakeStack(run_error="Extraction failed for document doc-1 after 3 attempts"))

    assert not report.ok
    assert "analyze ended in ERROR: Extraction failed for document doc-1" in report.failures[0]
    assert "reassess" not in report.statuses  # nothing after the failed step ran


@pytest.mark.asyncio
async def test_an_http_error_is_described_by_its_envelope() -> None:
    report = await journey(FakeStack(fail_path=("/bundles/bnd-1/documents", 502)))

    assert report.failures == ["POST /bundles/bnd-1/documents -> 502 UPSTREAM_ERROR: storage is down"]


@pytest.mark.asyncio
async def test_a_stream_that_drops_is_reopened_and_replays_of_older_runs_are_ignored() -> None:
    stack = FakeStack(stream_drops=2)  # the first two connections end mid-run (the UI proxy closes long streams)
    report = await journey(stack)

    assert report.ok, report.failures
    assert stack.stream_calls >= 4  # two drops on the first analysis, then a clean connection each time


@pytest.mark.asyncio
async def test_a_run_that_never_finishes_times_out_with_the_last_status() -> None:
    stack = FakeStack(stream_drops=10_000)
    stack.runs = 1  # run-1 has been started and keeps running
    async with httpx.AsyncClient(base_url="http://stack", transport=httpx.MockTransport(stack.handler)) as client:
        api = e2e.Api(client, "/api/proxy")
        with pytest.raises(e2e.JourneyError, match=r"did not finish within \d+s .*extract"):
            await e2e.watch_run(api, "bnd-1", "run-1", timeout=0.3)


# ---------------------------------------------------------------------------
# measurements and entry point
# ---------------------------------------------------------------------------


def test_stage_seconds_attribute_time_to_the_stage_that_was_current() -> None:
    seen = [(0.0, "initializing"), (1.0, "extract"), (11.5, "discrepancy"), (12.0, None)]

    assert e2e._stage_seconds(seen) == {"initializing": 1.0, "extract": 10.5, "discrepancy": 0.5}


def test_summary_statistics() -> None:
    def run(index: int, analyze: float) -> Any:
        report = e2e.RunReport(index=index)
        report.steps.update(analyze=analyze, reassess=analyze / 2)
        return report

    failing = e2e.RunReport(index=4, failures=["x"])
    failing.steps.update(analyze=1.0, reassess=0.5)  # a fast failure: counted as a failure, never timed
    summary = e2e.summarise([run(1, 10.0), run(2, 20.0), run(3, 30.0), failing])

    assert summary["runs"] == 4 and summary["passed"] == 3
    assert summary["analyze_seconds"] == {"n": 3, "min": 10.0, "p50": 20.0, "max": 30.0}, "no p95 below 20 runs: it would be the maximum"
    assert e2e.percentile([1.0], 0.95) == 1.0

    many = e2e.summarise([run(i, float(i)) for i in range(1, 21)])
    assert many["analyze_seconds"]["p95"] == 19.0 and many["analyze_seconds"]["max"] == 20.0


@pytest.mark.asyncio
async def test_main_writes_the_report_and_exit_code(tmp_path, capsys) -> None:
    stack = FakeStack()
    out = tmp_path / "report.json"

    code = await e2e.main_async(args_for(out=out, runs=2), transport=httpx.MockTransport(stack.handler))

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["meta"]["app_mode"] == "demo"
    assert report["summary"]["runs"] == 2 and report["summary"]["passed"] == 2
    assert "summary:" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_main_exits_one_when_any_run_fails(tmp_path) -> None:
    stack = FakeStack(second_status="SPECIALIST_REVIEW_REQUIRED")

    code = await e2e.main_async(args_for(out=tmp_path / "r.json"), transport=httpx.MockTransport(stack.handler))

    assert code == 1


@pytest.mark.asyncio
async def test_main_refuses_a_stack_in_the_wrong_mode(tmp_path, capsys) -> None:
    code = await e2e.main_async(args_for(out=tmp_path / "r.json", expect_mode="live"),
                                transport=httpx.MockTransport(FakeStack(mode="demo").handler))

    assert code == 1
    assert "EXPECTED mode live" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_a_bearer_token_is_read_from_the_named_variable_and_sent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("E2E_TOKEN", "id-token-value")
    stack = FakeStack()

    code = await e2e.main_async(args_for(out=tmp_path / "r.json", token_env="E2E_TOKEN"),
                                transport=httpx.MockTransport(stack.handler))

    assert code == 0
    assert stack.auth_headers == {"Bearer id-token-value"}


@pytest.mark.asyncio
async def test_an_empty_token_variable_is_a_usage_error(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.delenv("E2E_TOKEN", raising=False)

    code = await e2e.main_async(args_for(out=tmp_path / "r.json", token_env="E2E_TOKEN"),
                                transport=httpx.MockTransport(FakeStack().handler))

    assert code == 2
    assert "E2E_TOKEN is empty" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_an_unreachable_stack_exits_one(tmp_path, capsys) -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    code = await e2e.main_async(args_for(out=tmp_path / "r.json"), transport=httpx.MockTransport(refuse))

    assert code == 1
    assert "cannot reach the stack" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --case d: the India import
# ---------------------------------------------------------------------------


class CaseDStack(FakeStack):
    """Answers like the product does for Case D, unless a knob breaks one promise."""

    def __init__(self, **overrides: Any) -> None:
        self.destination = None
        self.checks = {c: "PASS" for c in ("I-001", "I-002", "I-003", "M-003", "M-004", "E-origin", "H-002")}
        self.checks.update({"M-001": "MATERIAL", "SEC-002": "WARN"})
        self.d_status = "MATERIAL_CONTRADICTION"
        self.m001_message = "HS 7304.31.00 is declared non-alloy, but heat TH-77121 reports Cr 0.35%, at or above the 0.3 % threshold"
        self.valuation = {"status": "ESTIMATED", "assessable_value": 5443559.38, "total_duty": 2280579.21, "implied_hs_code": "730451",
                          "assumptions": ["insurance is not stated"]}
        super().__init__(**overrides)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/proxy")
        if path == "/bundles" and request.method == "POST":
            self.destination = json.loads(request.content)["destination_country"]
        if path == "/bundles/bnd-1/assessment":
            return httpx.Response(200, json={
                "iteration": 1, "status": self.d_status, "missing_evidence": [], "data_source": self.data_source,
                "checks": [{"check_id": i, "severity": s, "message": self.m001_message if i == "M-001" else "ok"} for i, s in self.checks.items()],
                "valuation": self.valuation, "confidence": {"action": "AUTO_FLAG"}, "reasoning_delta": None,
            })
        return super().handler(request)


def case_d_args(**overrides: Any) -> argparse.Namespace:
    return args_for(case="d", **overrides)


async def case_d(stack: CaseDStack):
    async with httpx.AsyncClient(base_url="http://stack", transport=httpx.MockTransport(stack.handler)) as client:
        api = e2e.Api(client, "/api/proxy")
        meta = (await api.call("GET", "/meta")).json()
        return await e2e.run_case_d(api, 1, case_d_args(), meta)


@pytest.mark.asyncio
async def test_case_d_against_a_stack_that_finds_the_contradiction_passes() -> None:
    stack = CaseDStack()

    report = await case_d(stack)

    assert report.ok, report.failures
    assert stack.destination == "IN"
    assert set(report.steps) >= {"create_bundle", "analyze", "audit"} and "reassess" not in report.steps
    assert report.statuses == {"analyze": "MATERIAL_CONTRADICTION"}
    assert report.notes["checks"]["M-001"] == "MATERIAL" and report.notes["valuation"]["total_duty"] == 2280579.21


@pytest.mark.asyncio
async def test_case_d_fails_when_the_contradiction_is_missed() -> None:
    cases = [
        (dict(d_status="COMPLIANT_FOR_SUBMISSION"), "status is COMPLIANT_FOR_SUBMISSION"),
        (dict(checks={**CaseDStack().checks, "M-001": "PASS"}), "M-001 is PASS, expected MATERIAL"),
        (dict(m001_message="HS 7304.31.00 is declared non-alloy but something else"), "does not name heat TH-77121"),
        (dict(checks={**CaseDStack().checks, "M-003": "MATERIAL"}), "M-003 is MATERIAL"),
        (dict(checks={**CaseDStack().checks, "SEC-002": "PASS"}), "SEC-002 is PASS, expected WARN"),
        (dict(valuation={"status": "PARTIAL", "reason": "no rate", "assumptions": []}), "valuation is PARTIAL"),
        (dict(valuation={"status": "ESTIMATED", "assumptions": []}), "lists no assumption"),
        (dict(audit_verified=False), "audit chain did not verify"),
    ]
    for overrides, expected in cases:
        report = await case_d(CaseDStack(**overrides))
        assert not report.ok, overrides
        assert any(expected in failure for failure in report.failures), (overrides, report.failures)


@pytest.mark.asyncio
async def test_main_runs_case_d_when_asked(tmp_path) -> None:
    stack = CaseDStack()

    code = await e2e.main_async(case_d_args(out=tmp_path / "r.json"), transport=httpx.MockTransport(stack.handler))

    assert code == 0 and stack.destination == "IN"
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["runs"][0]["statuses"] == {"analyze": "MATERIAL_CONTRADICTION"}


def test_the_case_option_is_validated() -> None:
    assert e2e.parse_args(["--base-url", "http://x", "--case", "d"]).case == "d"
    assert e2e.parse_args(["--base-url", "http://x"]).case == "c"
    with pytest.raises(SystemExit):
        e2e.parse_args(["--base-url", "http://x", "--case", "e"])


# ---------------------------------------------------------------------------
# --corrections: the Phase 2 journey, against the REAL app (not a fake): the script and the API must agree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_corrections_journey_passes_against_the_real_app(tmp_path, monkeypatch) -> None:
    from app.main import app
    from tests.helpers import wait_for_run

    async def poll_the_run(api, bundle_id, run_id, timeout):  # httpx's in-process transport buffers SSE bodies: follow the run by polling
        return await wait_for_run(bundle_id, run_id, timeout=timeout, interval=0.01), {}

    monkeypatch.setattr(e2e, "watch_run", poll_the_run)
    monkeypatch.setattr(asyncio, "sleep", REAL_SLEEP)  # this test runs the real app: it needs a loop that really yields
    out = tmp_path / "report.json"
    args = args_for(case="d", corrections=True, prefix="/api/v1", out=out, timeout=30.0)
    code = await e2e.main_async(args, transport=httpx.ASGITransport(app=app))

    report = json.loads(out.read_text())
    run = report["runs"][0]
    assert code == 0 and run["failures"] == [], run["failures"]
    assert run["notes"]["corrected_cell"]["model_read"] == "0.35" and run["notes"]["recompute_seconds"] is not None
    assert {"correction", "recompute", "recompute_after_undo", "prefill_json", "prefill_pdf"} <= set(run["steps"])
    # the two recomputes are two measurements: the undo must not replace the first one's time, stages or status
    assert run["statuses"]["recompute"] == "SPECIALIST_REVIEW_REQUIRED", run["statuses"]
    assert run["statuses"]["recompute_after_undo"] == "MATERIAL_CONTRADICTION", run["statuses"]
    assert run["notes"]["recompute_seconds"] == run["steps"]["recompute"]
    assert report["case"] == "d" and report["options"]["corrections"] is True


@pytest.mark.asyncio
async def test_the_journey_demands_a_signed_audit_head_when_asked(tmp_path, monkeypatch) -> None:
    """Signing ON in the real app: the corrections journey ends with the head signed (by the demo key) after the LAST recompute."""
    from app.main import app
    from tests.helpers import wait_for_run

    async def poll_the_run(api, bundle_id, run_id, timeout):
        return await wait_for_run(bundle_id, run_id, timeout=timeout), {}

    monkeypatch.setattr(e2e, "watch_run", poll_the_run)
    monkeypatch.setattr(asyncio, "sleep", REAL_SLEEP)
    monkeypatch.setattr(settings, "audit_signing", True)
    out = tmp_path / "report.json"
    code = await e2e.main_async(
        args_for(case="d", corrections=True, prefix="/api/v1", out=out, timeout=30.0, expect_signer="local-demo"),
        transport=httpx.ASGITransport(app=app),
    )
    run = json.loads(out.read_text())["runs"][0]
    assert code == 0 and run["failures"] == [], run["failures"]
    signature = run["notes"]["audit_signature"]
    assert (signature["status"], signature["signer"], signature["unsigned_events"], signature["failures"]) == ("SIGNED", "local-demo", 0, 0)

    wrong = tmp_path / "wrong.json"
    code = await e2e.main_async(
        args_for(case="d", prefix="/api/v1", out=wrong, timeout=30.0, expect_signer="kms"), transport=httpx.ASGITransport(app=app)
    )
    assert code == 1 and "expected 'kms'" in " ".join(json.loads(wrong.read_text())["runs"][0]["failures"])


def test_corrections_need_case_d() -> None:
    with pytest.raises(SystemExit):
        e2e.parse_args(["--base-url", "http://x", "--corrections"])
    assert e2e.parse_args(["--base-url", "http://x", "--case", "d", "--corrections"]).corrections is True


# ---------------------------------------------------------------------------
# the audit signature check
# ---------------------------------------------------------------------------


def signature_report(signature: dict | None, **overrides):
    report = e2e.RunReport(index=1)
    e2e.check_signature(report, args_for(**overrides), {"signature": signature} if signature is not None else {})
    return report


def test_a_chain_without_signing_information_is_not_a_failure() -> None:
    assert signature_report(None).failures == []
    assert signature_report({"configured": False, "status": "NOT_CONFIGURED"}).failures == []


def test_configured_signing_must_have_signed_the_head_and_recorded_no_failure() -> None:
    assert signature_report({"configured": True, "status": "SIGNED", "signer": "kms"}).failures == []
    unsigned = signature_report({"configured": True, "status": "PARTIAL", "signer": "kms"}).failures
    assert unsigned == ["signing is configured but the audit signature status is PARTIAL"]
    failed = signature_report({"configured": True, "status": "SIGNED", "signer": "kms", "failures": 2}).failures
    assert failed == ["2 audit signing failure(s) are recorded in the chain"]
    report = signature_report({"configured": True, "status": "SIGNED", "signer": "kms", "key": "k", "signed_seq": 9})
    assert report.notes["audit_signature"]["signed_seq"] == 9 and report.notes["audit_signature"]["key"] == "k"


def test_expect_signer_pins_who_signed_and_that_it_verified() -> None:
    assert signature_report({"configured": True, "status": "SIGNED", "signer": "kms"}, expect_signer="kms").failures == []
    wrong = signature_report({"configured": True, "status": "SIGNED", "signer": "local-demo"}, expect_signer="kms").failures
    assert wrong == ["the audit head is signed by 'local-demo', expected 'kms'"]
    invalid = signature_report({"configured": True, "status": "INVALID", "signer": "kms"}, expect_signer="kms").failures
    assert invalid == ["the audit signature status is INVALID, expected SIGNED"]
    none = signature_report({"configured": False, "status": "NOT_CONFIGURED", "signer": None}, expect_signer="kms").failures
    assert len(none) == 2


def test_the_expect_signer_option_is_validated() -> None:
    assert e2e.parse_args(["--base-url", "http://x", "--expect-signer", "kms"]).expect_signer == "kms"
    with pytest.raises(SystemExit):
        e2e.parse_args(["--base-url", "http://x", "--expect-signer", "hsm"])
