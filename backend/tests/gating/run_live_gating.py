#!/usr/bin/env python3
"""The input-gating audit, live half: every fixture through the product's real routes and pipeline, with the real Gemini endpoint,
and the tokens each request cost. Run by a PERSON with Google Cloud credentials, never by CI. Real money: a few cents.

    cd backend
    .venv/bin/python -I tests/gating/run_live_gating.py --live [--only F2 F5 ...] [--skip-baselines] [--out DIR]

What is real: the FastAPI app (upload route, middleware, orchestrator, preprocessing, extraction, engines) and Vertex AI
(``GEMINI_LIVE_MODEL`` in ``GEMINI_LIVE_LOCATION``, the settings the product ships with). What is local, as in demo mode: file
storage, the Firestore stand-in and the tariff lookup, so nothing is written to a Google Cloud project. The request limits are
switched off for this run only (the runner makes more than 60 uploads a minute by design); the offline tests cover the limits.

Every fixture is put in a bundle the way a user would: the Case C bundle (SG) with its invoice swapped for the fixture, or the
Case D bundle (IN) for the injection fixtures, whose clean run is the control. Tokens come from Gemini's ``usage_metadata`` for each
request, attributed to the document it was made for. Nothing here is estimated.

    synthetic documents only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core import mode  # noqa: E402
from app.core.config import settings  # noqa: E402
from tests.gating import harness  # noqa: E402
from tests.helpers import api_client  # noqa: E402

DEFAULT_OUT = BACKEND_DIR / "data" / "live_gating"


def configure(storage: Path) -> None:
    settings.app_mode = "demo"
    settings.local_storage_path = str(storage)
    settings.rate_limit_writes_per_minute = 0
    settings.rate_limit_runs_per_minute = 0
    settings.audit_signing = False


def findings(assessment: dict[str, Any] | None) -> list[dict[str, str]]:
    return [{"check_id": c.get("check_id"), "severity": c.get("severity"), "message": (c.get("message") or "")[:160]}
            for c in (assessment or {}).get("checks", []) if c.get("severity") != "PASS"]


def summarise(run: harness.BundleRun, calls: list[dict[str, Any]], own: str | None) -> dict[str, Any]:
    per_doc = harness.calls_by_document(calls)
    own_row = per_doc.get(own) if own else None
    extraction = next((e for e in run.extractions if e.get("document_id") == own), None)
    return {
        "uploads": [vars(u) for u in run.uploads],
        "run": run.run,
        "status": (run.assessment or {}).get("status"),
        "data_source": (run.assessment or {}).get("data_source"),
        "findings": findings(run.assessment),
        "own_document": own,
        "own_tokens": own_row,
        "own_doc_type": (extraction or {}).get("doc_type"),
        "own_doc_type_confidence": (extraction or {}).get("doc_type_confidence"),
        "all_documents_tokens": {str(k): v for k, v in per_doc.items()},
        "requests": len(calls),
        "seconds": run.seconds,
        "_own_flat": harness.flatten(extraction) if extraction else None,
    }


async def run_case(client: Any, meter: Any, name: str, entry: dict[str, Any]) -> dict[str, Any]:
    """One fixture: upload it first (a refusal stops the case: nothing else is sent), then the rest of its bundle, then analyze."""
    from tests.helpers import wait_for_run

    data = harness.fixture(name)
    destination = "IN" if entry["bundle"] == "case_d" else "SG"
    files = harness.swap_bundle(entry["bundle"], entry["upload_as"], data, entry["replaces"])
    ours = next(f for f in files if f[1] == data)
    rest = [f for f in files if f is not ours]
    started_calls = len(meter.calls)
    run = harness.BundleRun()
    started = time.perf_counter()
    created = await client.post("/api/v1/bundles", json={"reference": "GATING-AUDIT", "destination_country": destination})
    run.bundle_id = created.json()["id"]
    first = await harness.upload(client, run.bundle_id, *ours)
    run.uploads.append(first)
    if first.status == 201:
        for filename, content in rest:
            run.uploads.append(await harness.upload(client, run.bundle_id, filename, content))
        started_run = await client.post(f"/api/v1/bundles/{run.bundle_id}/analyze")
        run.run = {"http_status": started_run.status_code}
        if started_run.status_code == 202:
            state = await wait_for_run(run.bundle_id, started_run.json()["run_id"], timeout=900.0, interval=0.5)
            run.run.update(run_id=state.get("run_id"), state=state.get("state"), error=state.get("error"), stage=state.get("stage"))
            if state.get("state") == "COMPLETE":
                run.assessment = (await client.get(f"/api/v1/bundles/{run.bundle_id}/assessment")).json()
                run.extractions = (await client.get(f"/api/v1/bundles/{run.bundle_id}/extractions")).json()
    run.seconds = round(time.perf_counter() - started, 2)
    return {"fixture": entry["fixture"], "file": name, "what": entry["what"], "bundle": entry["bundle"],
            **summarise(run, meter.calls[started_calls:], first.document_id)}


async def run_baselines(client: Any, meter: Any) -> dict[str, Any]:
    """F1 (the four clean Case C documents, then a reassess of the unchanged bundle) and the Case D control."""
    out: dict[str, Any] = {}
    case_c = [(n, (harness.CASE_C / n).read_bytes()) for n in harness.CASE_C_FILES]
    mark = len(meter.calls)
    first = await harness.run_bundle(client, case_c, destination="SG")
    out["F1_analyze"] = summarise(first, meter.calls[mark:], None)
    mark = len(meter.calls)
    again = await harness.run_bundle(client, [], bundle_id=first.bundle_id, mode="reassess")
    out["F1_reassess_unchanged"] = summarise(again, meter.calls[mark:], None)
    case_d = [(n, (harness.CASE_D / n).read_bytes()) for n in harness.CASE_D_FILES]
    mark = len(meter.calls)
    control = await harness.run_bundle(client, case_d, destination="IN")
    out["D0_case_d_control"] = summarise(control, meter.calls[mark:], None)
    invoice_id = next((u.document_id for u in control.uploads if u.filename == "case_d_commercial_invoice.pdf"), None)
    out["D0_case_d_control"]["invoice_document"] = invoice_id
    out["D0_case_d_control"]["invoice_flat"] = next(
        (harness.flatten(e) for e in control.extractions if e.get("document_id") == invoice_id), None)
    return out


def _thinking() -> str:
    from google.genai import types

    from app.agents import extraction

    return extraction.describe_thinking(types, settings.gemini_live_model)


def environment() -> dict[str, Any]:
    import google.genai as genai

    return {
        "started_utc": datetime.now(timezone.utc).isoformat(), "project": settings.project_id, "location": settings.gemini_live_location,
        "model": settings.gemini_live_model, "sdk": getattr(genai, "__version__", "?"), "credential_source": mode.credential_source(),
        "thinking_budget": settings.gemini_thinking_budget, "thinking": _thinking(), "max_output_tokens": settings.gemini_max_output_tokens,
        "max_attempts": settings.gemini_max_attempts, "gemini_max_pages": settings.gemini_max_pages,
        "page_image_mode": settings.page_image_mode, "demo_mode_local_storage": True,
    }


async def main_async(args: argparse.Namespace) -> int:
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    configure(out_dir / f"storage-{stamp}")
    meter = harness.install_meter(harness.real_vertex_client())
    report: dict[str, Any] = {"environment": environment(), "baselines": {}, "cases": {}}
    selected = set(args.only or [])
    manifest = harness.manifest()
    async with api_client() as client:
        if not args.skip_baselines:
            report["baselines"] = await run_baselines(client, meter)
            _print_baselines(report["baselines"])
        for name, entry in manifest.items():
            if entry["fixture"] == "F1" or (selected and entry["fixture"] not in selected and Path(name).stem.split("_")[0].upper() not in selected):
                continue
            result = await run_case(client, meter, name, entry)
            report["cases"][name] = result
            _print_case(name, result)
    report["environment"]["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report["calls"] = meter.calls
    path = out_dir / f"gating-report-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport: {path}")
    return 0


def _tokens(row: dict[str, Any] | None) -> str:
    if not row:
        return "no request"
    return (f"requests={row['requests']} in={row['prompt']} out={row['candidates']} thoughts={row['thoughts']} total={row['total']} "
            f"images={row['image_parts']} pdfs={row['pdf_parts']} finish={row['finish_reasons']}")


def _print_baselines(baselines: dict[str, Any]) -> None:
    for key, value in baselines.items():
        print(f"{key}: status={value['status']} run={value['run'].get('state')} requests={value['requests']} seconds={value['seconds']}")
        for doc, row in value["all_documents_tokens"].items():
            print(f"    {doc}: {_tokens(row)}")


def _print_case(name: str, result: dict[str, Any]) -> None:
    upload = result["uploads"][0]
    print(f"\n{result['fixture']} {name}\n  upload: {upload['status']} {upload['message'] or ''}")
    if result["run"]:
        print(f"  run: {result['run'].get('state')} {result['run'].get('error') or ''}  status={result['status']}  "
              f"doc_type={result['own_doc_type']} ({result['own_doc_type_confidence']})")
        print(f"  own tokens: {_tokens(result['own_tokens'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="required: this calls the real Gemini endpoint and costs money")
    parser.add_argument("--only", nargs="+", help="fixture ids (F2, F5, ...) or file prefixes (f06a)")
    parser.add_argument("--skip-baselines", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not args.live:
        print("refusing to run: pass --live to call the real Gemini endpoint (real money, a few cents).")
        return 2
    if mode.credential_source() is None:
        print(mode.no_credentials_message())
        return 2
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
