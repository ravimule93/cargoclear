#!/usr/bin/env python3
"""The extraction cache against the real Gemini endpoint, through the real routes and pipeline. Run by a PERSON with Google Cloud
credentials, never by CI. About 33,000 tokens: the four Case C documents are read once, then not again.

    cd backend
    .venv/bin/python -I tests/gating/probe_cache.py

Steps, each with the requests Gemini received and their tokens (``usage_metadata``): analyze four documents; reassess with nothing
changed; add a fifth document and reassess; recompute. Storage and Firestore are the local stand-ins. Synthetic documents only.
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


def tokens(calls: list[dict]) -> dict:
    usage = [c.get("usage") or {} for c in calls]
    return {"requests": len(calls), "in": sum(u.get("prompt_token_count") or 0 for u in usage),
            "out": sum(u.get("candidates_token_count") or 0 for u in usage), "total": sum(u.get("total_token_count") or 0 for u in usage)}


async def main_async() -> int:
    settings.app_mode = "demo"
    settings.local_storage_path = tempfile.mkdtemp(prefix="cache-probe-")
    settings.rate_limit_writes_per_minute = settings.rate_limit_runs_per_minute = 0
    meter = harness.install_meter(harness.real_vertex_client())
    case_c = [(n, (harness.CASE_C / n).read_bytes()) for n in harness.CASE_C_FILES]
    async with api_client() as client:
        steps = [("analyze 4 documents", None), ("reassess, nothing changed", "reassess"), ("add a document, reassess", "add"),
                 ("recompute", "recompute")]
        bundle_id = None
        for label, action in steps:
            mark = len(meter.calls)
            if action is None:
                run = await harness.run_bundle(client, case_c, destination="SG")
                bundle_id = run.bundle_id
            elif action == "add":
                extra = ("extra_invoice.pdf", harness.fixture("f04c_invoice_terms_then_table.pdf"))
                run = await harness.run_bundle(client, [extra], bundle_id=bundle_id, mode="reassess")
            else:
                run = await harness.run_bundle(client, [], bundle_id=bundle_id, mode=action)
            print("CACHE " + json.dumps({"step": label, "state": run.run.get("state"), "status": (run.assessment or {}).get("status"),
                                         **tokens(meter.calls[mark:])}), flush=True)
    return 0


def main() -> int:
    if mode.credential_source() is None:
        print(mode.no_credentials_message())
        return 2
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
