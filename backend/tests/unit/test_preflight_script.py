"""scripts/preflight_gcp.py, tested with fake Google clients: no network, no credentials.

The real run is done by a person with credentials (docs/GCP_VERIFICATION.md). Here the script's own logic is verified:
what each check proves, which failure gets which hint, what gates the exit code, and that it cleans up its probes.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from google.api_core.exceptions import Forbidden, NotFound

from app.agents import extraction
from app.agents.tools import bq_tariff
from app.core.config import settings
from app.repo import firestore
from app.services import storage
from tests.helpers import load_script
from tests.unit.extraction_fakes import FakeGenai, good_doc, response, script as outcomes
from tests.unit.firestore_fakes import FakeFirestore

preflight = load_script("preflight_gcp.py")


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeBigQuery:
    """Answers by what the SQL asks for. ``dims`` = (stored vectors, query vectors)."""

    def __init__(self, *, sg_rows=4, dims=(768, 768), top_hs="73041900", distance=0.08, error: Exception | None = None):
        self.sg_rows, self.dims, self.top_hs, self.distance, self.error = sg_rows, dims, top_hs, distance, error
        self.queries: list[str] = []

    def query(self, sql: str, job_config: Any = None):
        self.queries.append(sql)
        if self.error is not None:
            raise self.error
        if "COUNT(*)" in sql:
            rows = [{"n": self.sg_rows}]
        elif "ARRAY_LENGTH(description_embedding)" in sql:
            rows = [{"d": self.dims[0]}]
        elif "ML.GENERATE_EMBEDDING" in sql and "VECTOR_SEARCH" not in sql:
            rows = [{"d": self.dims[1], "status": ""}]
        else:  # the API's own VECTOR_SEARCH
            rows = [
                {"hs_code": self.top_hs, "description": "Line pipe", "required_documents": ["MILL_TEST_CERTIFICATE"],
                 "rule_set": "demo-curated", "regulation_ref": "Demo rule set (prototype)", "distance": self.distance},
            ]
        return SimpleNamespace(result=lambda timeout=None: rows)


class FakeGcs:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.error = error

    def bucket(self, _name: str):
        outer = self

        class Blob:
            def __init__(self, path: str) -> None:
                self.path = path

            def upload_from_string(self, data: Any, content_type: str | None = None) -> None:
                if outer.error is not None:
                    raise outer.error
                outer.objects[self.path] = data

            def download_as_bytes(self) -> bytes:
                return outer.objects[self.path]

            def delete(self) -> None:
                outer.deleted.append(self.path)
                outer.objects.pop(self.path, None)

        return SimpleNamespace(blob=Blob)


def plain_answer() -> SimpleNamespace:
    return SimpleNamespace(text="OK")


@pytest.fixture
def stack(monkeypatch):
    """A fully working fake project; tests replace one part to break it."""
    parts = SimpleNamespace(
        genai=FakeGenai(outcomes(plain_answer(), response(good_doc()))),
        bq=FakeBigQuery(),
        fs=FakeFirestore(),
        gcs=FakeGcs(),
    )
    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(preflight.mode, "use_live_gcp", lambda: True)
    monkeypatch.setattr(preflight.mode, "credential_source", lambda: "test credentials")
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: parts.genai)
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: parts.bq)
    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: parts.fs)
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: parts.gcs)
    return parts


async def run_all(**kwargs: Any):
    results = await preflight.run_preflight(kwargs.get("names") or ["gemini", "bigquery", "firestore", "gcs"])
    return {r.name: r for r in results}


# ---------------------------------------------------------------------------
# the happy path and the exit code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_working_project_passes_every_check(stack) -> None:
    results = await run_all()

    assert {name: r.status for name, r in results.items()} == {
        "credentials": "PASS", "gemini": "PASS", "bigquery": "PASS", "firestore": "PASS", "gcs": "PASS",
    }
    assert results["gemini"].data["doc_type"] == "COMMERCIAL_INVOICE"
    assert results["bigquery"].data["top_hs"] == "73041900"
    assert results["bigquery"].data["query_dimensions"] == 768


@pytest.mark.asyncio
async def test_gemini_is_sent_the_real_extraction_request_shape(stack) -> None:
    await run_all(names=["gemini"])

    plain, real = stack.genai.calls
    assert plain["model"] == settings.gemini_live_model
    config = real["config"]
    assert real["model"] == settings.gemini_live_model
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None and config.system_instruction == extraction.SYSTEM_INSTRUCTION
    assert config.temperature == 0.0 and config.max_output_tokens == settings.gemini_max_output_tokens


def test_main_writes_a_report_and_exits_zero(stack, tmp_path, capsys) -> None:
    out = tmp_path / "report.json"

    assert preflight.main(["--out", str(out)]) == 0

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["gemini_model"] == settings.gemini_live_model
    assert [r["name"] for r in report["results"]] == ["credentials", "gemini", "bigquery", "firestore", "gcs"]
    assert "RESULT: PASS" in capsys.readouterr().out


def test_main_exits_one_when_a_check_fails(stack, tmp_path, capsys) -> None:
    stack.bq = FakeBigQuery(sg_rows=0)

    assert preflight.main(["--out", str(tmp_path / "r.json")]) == 1
    assert "FAIL (bigquery)" in capsys.readouterr().out


def test_it_refuses_to_run_outside_live_mode(tmp_path, capsys) -> None:
    assert settings.app_mode == "demo"  # the hermetic test environment

    assert preflight.main(["--out", str(tmp_path / "r.json")]) == 2

    assert "REFUSING TO RUN" in capsys.readouterr().err
    assert not (tmp_path / "r.json").exists()


def test_it_refuses_to_run_without_credentials(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(preflight.mode, "use_live_gcp", lambda: False)

    assert preflight.main(["--out", str(tmp_path / "r.json")]) == 2
    assert "no GCP credentials" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_only_runs_the_named_checks_plus_credentials(stack) -> None:
    results = await run_all(names=["gcs"])

    assert list(results) == ["credentials", "gcs"]
    assert stack.genai.calls == [] and stack.bq.queries == []


# ---------------------------------------------------------------------------
# failures and their hints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_model_that_is_not_served_fails_with_the_lifecycle_hint(stack) -> None:
    stack.genai = FakeGenai(outcomes(NotFound("404 Publisher Model was not found")))
    results = await run_all(names=["gemini"])

    assert results["gemini"].status == "FAIL"
    assert "model lifecycle" in results["gemini"].detail


@pytest.mark.asyncio
async def test_an_answer_the_extractor_cannot_use_is_a_warning_not_a_failure(stack) -> None:
    stack.genai = FakeGenai(outcomes(plain_answer(), response("this is not json")))
    results = await run_all(names=["gemini"])

    assert results["gemini"].status == "WARN"
    assert "live_smoke_extraction.py" in results["gemini"].detail


@pytest.mark.asyncio
async def test_bigquery_permission_errors_name_the_missing_roles(stack) -> None:
    stack.bq = FakeBigQuery(error=Forbidden("403 Access Denied: User does not have bigquery.jobs.create permission"))
    results = await run_all(names=["bigquery"])

    assert results["bigquery"].status == "FAIL"
    assert "roles/bigquery.jobUser" in results["bigquery"].detail
    assert "connectionUser" in results["bigquery"].detail


@pytest.mark.asyncio
async def test_a_missing_tariff_table_points_at_the_setup_script(stack) -> None:
    stack.bq = FakeBigQuery(error=NotFound("404 Not found: Table ahtn.master_tariff"))
    results = await run_all(names=["bigquery"])

    assert "setup_tariff.sh" in results["bigquery"].detail


@pytest.mark.asyncio
async def test_an_empty_destination_fails(stack) -> None:
    stack.bq = FakeBigQuery(sg_rows=0)
    results = await run_all(names=["bigquery"])

    assert results["bigquery"].status == "FAIL" and "no rows for SG" in results["bigquery"].detail


@pytest.mark.asyncio
async def test_vectors_from_two_different_embedding_models_fail(stack) -> None:
    """The silent killer: a table embedded with one model, queried with another. Every distance would be meaningless."""
    stack.bq = FakeBigQuery(dims=(768, 3072))
    results = await run_all(names=["bigquery"])

    assert results["bigquery"].status == "FAIL"
    assert "768 dimensions" in results["bigquery"].detail and "3072" in results["bigquery"].detail
    assert "setup_tariff.sh" in results["bigquery"].detail


@pytest.mark.asyncio
async def test_a_wrong_top_hit_or_a_distance_above_the_threshold_warns(stack) -> None:
    stack.bq = FakeBigQuery(top_hs="73043100", distance=0.5)
    results = await run_all(names=["bigquery"])

    detail = results["bigquery"].detail
    assert results["bigquery"].status == "WARN"
    assert "expected 73041900" in detail and "recalibrate" in detail


@pytest.mark.asyncio
async def test_the_probe_document_is_written_read_and_deleted(stack) -> None:
    results = await run_all(names=["firestore"])

    assert results["firestore"].status == "PASS"
    assert [kind for kind, _ in stack.fs.calls] == ["set", "get", "delete"]
    assert stack.fs.docs == {}  # nothing left behind


@pytest.mark.asyncio
async def test_the_probe_object_is_written_read_and_deleted(stack) -> None:
    results = await run_all(names=["gcs"])

    assert results["gcs"].status == "PASS"
    assert len(stack.gcs.deleted) == 1 and stack.gcs.deleted[0].startswith("_preflight/")
    assert stack.gcs.objects == {}


@pytest.mark.asyncio
async def test_storage_permission_errors_name_the_missing_role(stack) -> None:
    stack.gcs = FakeGcs(error=Forbidden("403 caller does not have storage.objects.create access"))
    results = await run_all(names=["gcs"])

    assert results["gcs"].status == "FAIL" and "roles/storage.objectAdmin" in results["gcs"].detail


@pytest.mark.parametrize(
    ("check", "error", "expected"),
    [
        ("firestore", Forbidden("403 Missing or insufficient permissions"), "roles/datastore.user"),
        ("gemini", Forbidden("403 Permission denied"), "roles/aiplatform.user"),
        ("gcs", NotFound("404 bucket does not exist"), "RAW_BUCKET"),
        ("bigquery", RuntimeError("boom"), ""),
    ],
)
def test_hint_for(check, error, expected) -> None:
    hint = preflight.hint_for(check, error)

    assert expected in hint
    if not expected:
        assert hint == ""
