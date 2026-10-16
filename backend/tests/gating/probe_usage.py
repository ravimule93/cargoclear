#!/usr/bin/env python3
"""The usage record against the real Gemini endpoint, cross-checked with an independent meter. Run by a PERSON with Google Cloud
credentials, never by CI. About 50,000 tokens.

    cd backend
    .venv/bin/python -I tests/gating/probe_usage.py

Three bundles through the real routes and pipeline: (1) the four Case C documents, analyzed and then reassessed; (2) a scanned
invoice, whose first page the vision gate has to decide; (3) the 30-page dense table, whose answer is cut off at the output cap, so
the run FAILS. For each, ``GET /bundles/{id}/usage`` is compared with the sum of the ``usage_metadata`` that the harness's meter saw on
every request (the meter is independent of the product's own recording). Storage and Firestore are the local stand-ins.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from app.core import mode  # noqa: E402
from app.core.config import settings  # noqa: E402
from tests.gating import harness  # noqa: E402
from tests.helpers import api_client  # noqa: E402


def metered(calls: list[dict]) -> dict:
    usage = [c.get("usage") or {} for c in calls]
    return {"requests": len(calls), "prompt": sum(u.get("prompt_token_count") or 0 for u in usage),
            "output": sum(u.get("candidates_token_count") or 0 for u in usage),
            "thinking": sum(u.get("thoughts_token_count") or 0 for u in usage),
            "total": sum(u.get("total_token_count") or 0 for u in usage)}


def recorded(usage: dict, *, gate: bool = False) -> dict:
    t = usage["totals"]
    return {"requests": t["requests"] + (len([r for r in usage["runs"]]) * 0), "prompt": t["prompt_tokens"], "output": t["output_tokens"],
            "thinking": t["thinking_tokens"], "total": t["total_tokens"] + (t["upload_gate_tokens"] if gate else 0)}


async def main_async() -> int:
    settings.app_mode = "demo"
    settings.local_storage_path = tempfile.mkdtemp(prefix="usage-probe-")
    settings.rate_limit_writes_per_minute = settings.rate_limit_runs_per_minute = 0
    meter = harness.install_meter(harness.real_vertex_client())
    case_c = [(n, (harness.CASE_C / n).read_bytes()) for n in harness.CASE_C_FILES]
    async with api_client() as client:
        mark = len(meter.calls)
        first = await harness.run_bundle(client, case_c, destination="SG")
        await harness.run_bundle(client, [], bundle_id=first.bundle_id, mode="reassess")
        usage = (await client.get(f"/api/v1/bundles/{first.bundle_id}/usage")).json()
        print("USAGE " + json.dumps({"bundle": "case C: analyze, then reassess", "meter": metered(meter.calls[mark:]), "recorded": recorded(usage),
                                     "runs": [(r["mode"], r["state"], r["token_usage"]["requests"], r["token_usage"]["cached_documents"],
                                               r["token_usage"]["total_tokens"], r["token_usage"]["saved_tokens"]) for r in usage["runs"]]}), flush=True)

        mark = len(meter.calls)
        scan = await harness.run_bundle(client, [("commercial_invoice.pdf", harness.fixture("f11_scanned_invoice.pdf"))], destination="SG")
        usage = (await client.get(f"/api/v1/bundles/{scan.bundle_id}/usage")).json()
        print("USAGE " + json.dumps({"bundle": "scanned invoice (vision gate + extraction)", "meter": metered(meter.calls[mark:]),
                                     "recorded": recorded(usage, gate=True), "gate_tokens": usage["totals"]["upload_gate_tokens"]}), flush=True)

        mark = len(meter.calls)
        bad = await harness.run_bundle(client, [("commercial_invoice.pdf", harness.fixture("f16_worst_case_30_dense_pages.pdf"))], destination="SG")
        usage = (await client.get(f"/api/v1/bundles/{bad.bundle_id}/usage")).json()
        [run] = usage["runs"]
        print("USAGE " + json.dumps({"bundle": "30 dense pages (fails at the output cap)", "run_state": bad.run.get("state"),
                                     "meter": metered(meter.calls[mark:]), "recorded": recorded(usage, gate=True),
                                     "record": [(run["state"], run["token_usage"]["failed_requests"],
                                                 [(a["outcome"][:48], a["finish_reason"], a["prompt_tokens"], a["output_tokens"], a["total_tokens"])
                                                  for d in run["token_usage"]["documents"] for a in d["attempts"]])]}), flush=True)
    return 0


def main() -> int:
    if mode.credential_source() is None:
        print(mode.no_credentials_message())
        return 2
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
