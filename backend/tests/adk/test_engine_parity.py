"""D3: a DIFFERENTIAL test. The whole orchestrator runs each scenario twice, PIPELINE_ENGINE native and adk, on identical
inputs, and everything observable must be identical (see tests/adk/parity.py for exactly what is compared)."""

from __future__ import annotations

import pytest

from tests.adk.conftest import require_adk

require_adk()

from app.gateway.errors import PipelineError  # noqa: E402
from tests.adk import parity  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", parity.SCENARIOS, ids=[s.name for s in parity.SCENARIOS])
async def test_native_and_adk_are_indistinguishable(scenario) -> None:
    difference, native, adk = await parity.compare(scenario)

    assert difference is None, f"native != adk, first difference at {difference}"
    # the comparison is only meaningful if the scenario really ran something
    assert native["runs"], "the scenario started no run"


@pytest.mark.asyncio
async def test_the_scenarios_really_exercise_what_they_claim_to() -> None:
    """Guard against a vacuous parity: each scenario must produce the outcome its name promises."""
    seen = {}
    for scenario in parity.SCENARIOS:
        seen[scenario.name] = await parity.collect(scenario, "native")

    def last_iteration(name: str) -> dict:
        return seen[name]["bundles"][0]["iterations"][-1]

    def check_ids(name: str) -> dict[str, str]:
        return {c["check_id"]: c["severity"] for c in last_iteration(name)["checks"]}

    assert [i["status"] for i in seen["case C iterations 1 and 2"]["bundles"][0]["iterations"]] == [
        "MISSING_EVIDENCE", "COMPLIANT_FOR_SUBMISSION"]
    assert last_iteration("case C iteration 1")["status"] == "MISSING_EVIDENCE"
    assert last_iteration("net/gross weight mismatch")["status"] == "MATERIAL_CONTRADICTION"
    assert check_ids("net/gross weight mismatch")["W-001"] == "MATERIAL" and check_ids("net/gross weight mismatch")["W-002"] == "MATERIAL"
    assert check_ids("HS mismatch invoice vs packing list")["H-002"] == "MATERIAL"
    assert check_ids("MTC declares a different HS")["H-003-MILL_TEST_CERTIFICATE"] == "MATERIAL"
    assert last_iteration("coffee described with the pipe code")["grounding"][0]["hs_mismatch"] is True
    assert any(c.startswith("D-DUP-") for c in check_ids("duplicate documents"))
    assert last_iteration("low-confidence field")["confidence"]["action"] == "INTERACTIVE_REVIEW"
    assert last_iteration("an UNKNOWN document")["documents"], "the unknown document is part of the bundle"

    for name in ("a stage raises (ground), unexpected error", "a stage raises (ground), domain error"):
        run = seen[name]["runs"][0]
        events = [e["event_type"] for e in seen[name]["bundles"][0]["audit"]]
        assert run["state"] == "ERROR" and events.count("ANALYSIS_FAILED") == 1 and "ASSESSMENT_COMPLETED" not in events
        assert seen[name]["bundles"][0]["iterations"] == []
    unexpected = seen["a stage raises (ground), unexpected error"]["runs"][0]["message"]
    assert unexpected == "The analysis failed unexpectedly (reference: <RUN-1>)." and "SECRET" not in str(seen)
    assert seen["a stage raises (ground), domain error"]["runs"][0]["message"] == str(
        PipelineError("the tariff lookup could not be completed")
    )

    deadline = seen["deadline expiry"]
    assert deadline["runs"][0]["message"] == "the analysis exceeded the time limit"
    assert deadline["bundles"][0]["audit"][-1]["payload"]["reason"] == "timeout"

    cancelled = seen["cancellation mid-run"]
    assert cancelled["runs"][0]["message"] == "cancelled: the server is shutting down"
    assert cancelled["bundles"][0]["audit"][-1]["payload"]["reason"] == "cancelled"
    assert ["task_cancelled", True] in cancelled["writes"], "the task itself ended cancelled"

    reaped = seen["reaped run (fencing)"]
    events = [e["event_type"] for e in reaped["bundles"][0]["audit"]]
    assert ["reaped", True] in reaped["writes"] and reaped["bundles"][0]["iterations"] == []
    assert events.count("ANALYSIS_FAILED") == 1 and "ASSESSMENT_COMPLETED" not in events
    assert reaped["runs"][0]["state"] == "ERROR"
