#!/usr/bin/env python3
"""Preflight for the live GCP path. Run by a PERSON with Google Cloud credentials (or as the runtime service account),
never by CI. It answers one question before anything else is tried: "will the live API work in this project?"

    cd backend
    APP_MODE=live .venv/bin/python ../scripts/preflight_gcp.py [options]

Checks, in order (each prints PASS / WARN / FAIL / SKIP, how long it took, and for a failure the likely missing role):

  credentials   a credential source is present (service-account key, `gcloud auth application-default login`, Cloud Run)
  gemini        the configured GEMINI_LIVE_MODEL answers in GEMINI_LIVE_LOCATION, AND accepts the REAL extraction request
                shape (structured-output schema, temperature, thinking config) on a tiny text-only invoice. This is what
                catches a retired model, a model that is not served in the region, or a config knob the model rejects.
  bigquery      the tariff table has rows for the destination, the remote embedding model answers, the stored vectors and
                the query vectors have the SAME dimension, and the API's own lookup (bq_tariff.lookup_tariff_with_source,
                the real VECTOR_SEARCH with the destination pre-filter) returns HS 73041900 with MILL_TEST_CERTIFICATE
  firestore     write, read and delete a probe document (roles/datastore.user)
  gcs           write, read and delete a probe object in RAW_BUCKET (roles/storage.objectAdmin)

Everything it writes is a probe under a `_preflight` prefix that it deletes again. It sends only a synthetic invoice
sentence to Gemini. Cost: a fraction of a cent.

Model lifecycle is NOT visible through the API. Before relying on a model, read Google's lifecycle pages (the report
prints the model and embedding endpoint it tested, and docs/GCP_VERIFICATION.md lists the links to check).

Options:
  --only NAME [NAME ...]  run just these checks (credentials always runs)
  --out FILE              JSON report (default ./preflight-report.json, git-ignored)
Exit code: 0 = no FAIL; 1 = at least one FAIL; 2 = refused to run (APP_MODE is not live, or no credentials).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents import extraction  # noqa: E402
from app.agents.tools import bq_tariff  # noqa: E402
from app.core import mode  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.repo import firestore  # noqa: E402
from app.services import storage  # noqa: E402

PROBE_COLLECTION = "_preflight"
SAMPLE_DESCRIPTION = "Seamless carbon steel pipes API 5L Grade B"
EXPECTED_HS = "73041900"
EXPECTED_DOCUMENT = "MILL_TEST_CERTIFICATE"
SAMPLE_INVOICE = (
    "COMMERCIAL INVOICE No. INV-PREFLIGHT-1. Seller: BHARAT SEAMLESS PIPES LTD. Buyer: SINGAPORE PRECISION PIPING PTE LTD. "
    "Item: Seamless carbon steel pipes API 5L Grade B, 120 lengths, net weight 14000 KGS, gross weight 14280 KGS, "
    "HS code 73041900, unit price USD 700.00, total USD 84000.00."
)

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
CHECK_ORDER = ("credentials", "gemini", "bigquery", "firestore", "gcs")


class Skipped(Exception):
    """A check that cannot run (its precondition is missing)."""


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str
    seconds: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)


def hint_for(name: str, exc: BaseException) -> str:
    """Likely cause of a failure, from the exception type and text. A pointer, not a diagnosis."""
    text = f"{type(exc).__name__} {exc}".lower()
    denied = "permission" in text or "403" in text or "forbidden" in text
    missing = "notfound" in text or "not found" in text or "404" in text
    if name == "gemini":
        if denied:
            return "grant roles/aiplatform.user to the runtime identity, and enable the Vertex AI API"
        if missing:
            return ("the model is not served to this project/location (retired, or not available in this region): "
                    "check GEMINI_LIVE_MODEL / GEMINI_LIVE_LOCATION against Google's model lifecycle page")
        if "400" in text or "invalid" in text:
            return "the model rejected the request shape (schema, temperature or thinking config): see the message"
    if name == "bigquery":
        if denied:
            return ("the identity needs roles/bigquery.dataViewer AND roles/bigquery.jobUser (to start the query), "
                    "and roles/bigquery.connectionUser on the connection for the remote embedding model")
        if missing:
            return "run infra/bigquery/setup_tariff.sh: the dataset, table or embedding model does not exist"
    if name == "firestore" and denied:
        return "grant roles/datastore.user to the runtime identity; check FIRESTORE_DATABASE exists in this project"
    if name == "gcs":
        if denied:
            return "grant roles/storage.objectAdmin to the runtime identity"
        if missing:
            return "RAW_BUCKET does not exist (infra/bootstrap.sh creates it)"
    return ""


async def run_check(name: str, work: Callable[[], Awaitable[tuple[str, str, dict[str, Any]]]]) -> CheckResult:
    started = time.perf_counter()
    try:
        status, detail, data = await work()
    except Skipped as exc:
        status, detail, data = SKIP, str(exc), {}
    except Exception as exc:  # noqa: BLE001 - every failure becomes a line in the report
        hint = hint_for(name, exc)
        message = f"{type(exc).__name__}: {str(exc)[:400]}"
        status, detail, data = FAIL, message + (f"  -> {hint}" if hint else ""), {"error_type": type(exc).__name__}
    return CheckResult(name, status, detail, round(time.perf_counter() - started, 2), data)


# ---------------------------------------------------------------------------
# the checks
# ---------------------------------------------------------------------------


def refusal_reason() -> str | None:
    if settings.app_mode != "live":
        return "APP_MODE is not 'live'. This script calls real Google Cloud services: run it as  APP_MODE=live ..."
    if not mode.use_live_gcp():
        return mode.no_credentials_message()
    return None


async def check_credentials() -> tuple[str, str, dict[str, Any]]:
    source = mode.credential_source()
    data = {"credential_source": source, "project": settings.project_id, "region": settings.region}
    return PASS, f"{source}; project {settings.project_id}, region {settings.region}", data


async def check_gemini() -> tuple[str, str, dict[str, Any]]:
    from google.genai import types

    client = extraction._get_genai_client()
    if client is None:
        raise RuntimeError("no Gemini client (credentials missing)")
    model = settings.gemini_live_model
    timeout = settings.gemini_timeout_seconds
    data: dict[str, Any] = {"model": model, "location": settings.gemini_live_location}

    # 1. the model answers at all
    plain = await asyncio.wait_for(
        client.aio.models.generate_content(model=model, contents="Reply with the single word OK."), timeout=timeout
    )
    data["plain_answer"] = (getattr(plain, "text", "") or "").strip()[:40]

    # 2. it accepts the REAL extraction request: same system prompt, schema, temperature and thinking config
    parts = [types.Part.from_text(text=SAMPLE_INVOICE), types.Part.from_text(text=extraction.EXTRACT_INSTRUCTION)]
    started = time.perf_counter()
    response = await asyncio.wait_for(
        client.aio.models.generate_content(model=model, contents=parts, config=extraction._request_config(types)),
        timeout=timeout,
    )
    data["extraction_request_seconds"] = round(time.perf_counter() - started, 2)
    prompt_tokens, output_tokens = extraction._usage(response)
    data.update(prompt_tokens=prompt_tokens, output_tokens=output_tokens, finish_reason=extraction._finish_reason(response))

    try:
        document, _warnings = extraction._read_response(response, "preflight-doc", None)
    except extraction._AttemptFailure as failure:
        return (WARN, f"{model} accepted the extraction request but the answer was not usable ({failure.summary}); "
                      "run scripts/live_smoke_extraction.py to judge extraction quality", data)
    data["doc_type"] = document.doc_type
    return (PASS, f"{model} @ {settings.gemini_live_location}: extraction request accepted in "
                  f"{data['extraction_request_seconds']}s, read as {document.doc_type}", data)


async def _query(client: Any, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Run one BigQuery job in a worker thread (the client blocks); rows as dicts."""
    from google.cloud import bigquery

    def run() -> list[dict[str, Any]]:
        job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params or []))
        return [dict(row) for row in job.result(timeout=settings.bq_query_timeout_seconds)]

    return await asyncio.to_thread(run)


async def check_bigquery() -> tuple[str, str, dict[str, Any]]:
    from google.cloud import bigquery

    client = bq_tariff._get_bq_client()
    if client is None:
        raise RuntimeError("no BigQuery client (credentials missing)")
    table, model = settings.tariff_table_fqn, settings.embedding_model_fqn
    data: dict[str, Any] = {"table": table, "embedding_model": model}

    rows = await _query(client, f"SELECT COUNT(*) AS n FROM `{table}` WHERE destination_country = @dest",
                        [bigquery.ScalarQueryParameter("dest", "STRING", "SG")])
    data["rows_for_SG"] = int(rows[0]["n"])
    if data["rows_for_SG"] == 0:
        return FAIL, f"{table} has no rows for SG: run infra/bigquery/setup_tariff.sh", data

    stored = await _query(client, f"SELECT ARRAY_LENGTH(description_embedding) AS d FROM `{table}` LIMIT 1")
    embedded = await _query(
        client,
        f"SELECT ARRAY_LENGTH(ml_generate_embedding_result) AS d, ml_generate_embedding_status AS status "
        f"FROM ML.GENERATE_EMBEDDING(MODEL `{model}`, (SELECT @q AS content))",
        [bigquery.ScalarQueryParameter("q", "STRING", SAMPLE_DESCRIPTION)],
    )
    data["stored_dimensions"], data["query_dimensions"] = stored[0]["d"], embedded[0]["d"]
    status = embedded[0].get("status")
    if not embedded[0]["d"]:
        return FAIL, f"the embedding model returned no vector (status: {status or 'empty'}): check its endpoint and the connection's roles/aiplatform.user", data
    if data["stored_dimensions"] != data["query_dimensions"]:
        return (FAIL, f"stored vectors have {data['stored_dimensions']} dimensions but the query model returns "
                      f"{data['query_dimensions']}: the table was embedded with a different model. Re-run setup_tariff.sh", data)

    # the API's own lookup, end to end (the real VECTOR_SEARCH with the destination pre-filter)
    hits, source = await asyncio.to_thread(bq_tariff.lookup_tariff_with_source, SAMPLE_DESCRIPTION, "SG")
    data["lookup_source"] = source
    if source != "bigquery":
        return FAIL, f"the lookup was answered by '{source}', not BigQuery", data
    if not hits:
        return FAIL, "VECTOR_SEARCH returned no candidates for SG", data
    top = hits[0]
    data.update(top_hs=top["hs_code"], top_distance=round(float(top["distance"]), 4), top_required=list(top["required_documents"]))
    problems = []
    if str(top["hs_code"]) != EXPECTED_HS:
        problems.append(f"top candidate is {top['hs_code']}, expected {EXPECTED_HS}")
    if EXPECTED_DOCUMENT not in top["required_documents"]:
        problems.append(f"top candidate does not require {EXPECTED_DOCUMENT}")
    if float(top["distance"]) > bq_tariff.AMBIGUITY_THRESHOLD:
        problems.append(f"distance {top['distance']:.3f} is above the ambiguity threshold {bq_tariff.AMBIGUITY_THRESHOLD} "
                        "(the threshold was tuned on another embedding model: recalibrate it)")
    if problems:
        return WARN, "; ".join(problems), data
    return (PASS, f"{data['rows_for_SG']} SG rows; {data['query_dimensions']}-dim vectors match; lookup -> {top['hs_code']} "
                  f"({', '.join(top['required_documents'])}) at distance {data['top_distance']}", data)


async def check_firestore() -> tuple[str, str, dict[str, Any]]:
    client = firestore._get_firestore_client()
    if client is None:
        raise RuntimeError("no Firestore client (credentials missing)")
    ref = client.collection(PROBE_COLLECTION).document(f"probe-{uuid.uuid4().hex[:12]}")
    payload = {"probe": True, "at": datetime.now(timezone.utc).isoformat()}
    await ref.set(payload)
    try:
        snapshot = await ref.get()
        if not snapshot.exists or snapshot.to_dict().get("probe") is not True:
            return FAIL, "wrote a probe document but could not read it back", {}
    finally:
        await ref.delete()
    return PASS, f"write/read/delete on database {settings.firestore_database}", {"database": settings.firestore_database}


async def check_gcs() -> tuple[str, str, dict[str, Any]]:
    client = storage._get_gcs_client()
    if client is None:
        raise RuntimeError("no Cloud Storage client (credentials missing)")
    name = f"{PROBE_COLLECTION}/probe-{uuid.uuid4().hex[:12]}.txt"
    body = b"cargoclear preflight"

    def roundtrip() -> bool:
        blob = client.bucket(settings.raw_bucket).blob(name)
        blob.upload_from_string(body, content_type="text/plain")
        try:
            return bool(blob.download_as_bytes() == body)
        finally:
            blob.delete()

    ok = await asyncio.to_thread(roundtrip)
    if not ok:
        return FAIL, "wrote a probe object but read back different bytes", {}
    return PASS, f"write/read/delete in gs://{settings.raw_bucket}", {"bucket": settings.raw_bucket}


CHECKS: dict[str, Callable[[], Awaitable[tuple[str, str, dict[str, Any]]]]] = {
    "credentials": check_credentials,
    "gemini": check_gemini,
    "bigquery": check_bigquery,
    "firestore": check_firestore,
    "gcs": check_gcs,
}


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def print_result(result: CheckResult) -> None:
    print(f"[{result.status:<4}] {result.name:<12} {result.seconds:>6.2f}s  {result.detail}")


async def run_preflight(names: list[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in CHECK_ORDER:
        if name != "credentials" and name not in names:
            continue
        result = await run_check(name, CHECKS[name])
        print_result(result)
        results.append(result)
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="preflight_gcp.py", description="Preflight for the live GCP path.",
                                     epilog="Run from backend/ with APP_MODE=live. See the module docstring.")
    parser.add_argument("--only", nargs="+", choices=[n for n in CHECK_ORDER if n != "credentials"],
                        default=[n for n in CHECK_ORDER if n != "credentials"], help="run just these checks")
    parser.add_argument("--out", type=Path, default=Path("preflight-report.json"), help="JSON report path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    reason = refusal_reason()
    if reason is not None:
        print(f"REFUSING TO RUN: {reason}", file=sys.stderr)
        return 2
    print(f"CargoClear GCP preflight: project {settings.project_id}, region {settings.region}\n")
    results = asyncio.run(run_preflight(list(args.only)))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": settings.project_id,
        "gemini_model": settings.gemini_live_model,
        "gemini_location": settings.gemini_live_location,
        "embedding_model": settings.embedding_model_fqn,
        "results": [asdict(r) for r in results],
    }
    args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    failed = [r.name for r in results if r.status == FAIL]
    warned = [r.name for r in results if r.status == WARN]
    print(f"\nreport: {args.out}")
    print("RESULT:", "FAIL (" + ", ".join(failed) + ")" if failed else ("PASS with warnings (" + ", ".join(warned) + ")" if warned else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
