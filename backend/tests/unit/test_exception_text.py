"""No raw exception text in a raised CargoClearError message.

The text of an exception from a client library can carry file paths, bucket and project names, URLs or document
content, and a CargoClearError message is shown to clients and stored in the audit log. These tests make every
such site fail with a secret-bearing exception and require the class name instead (the original exception is
still chained with ``from exc`` for the operator, and the log keeps the full text).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agents import extraction
from app.agents.tools import bq_tariff
from app.core.config import settings
from app.gateway.errors import UpstreamError
from app.repo import firestore
from app.services import audit, storage
from tests.unit.firestore_fakes import FakeFirestore

SECRET = "TOP-SECRET /Users/someone/key.json gs://private-bucket"


def boom(*_a: Any, **_k: Any):
    raise RuntimeError(SECRET)


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")
    for module in (firestore, audit, storage, bq_tariff, extraction):
        monkeypatch.setattr(module, "use_live_gcp", lambda: True)


def check(error: UpstreamError, expected: str) -> None:
    assert error.message == f"{expected}: RuntimeError", error.message
    assert "SECRET" not in error.message and "/Users/" not in error.message and "gs://" not in error.message
    assert isinstance(error.__cause__, RuntimeError), "the original exception stays chained for the operator"


# ---------------------------------------------------------------------------
# client initialisation
# ---------------------------------------------------------------------------


def test_firestore_client_init_failure(live, monkeypatch) -> None:
    monkeypatch.setattr("google.cloud.firestore_v1.async_client.AsyncClient", boom)
    with pytest.raises(UpstreamError) as raised:
        firestore._get_firestore_client()
    check(raised.value, "Firestore client init failed in live mode")


def test_audit_firestore_client_init_failure(live, monkeypatch) -> None:
    monkeypatch.setattr("google.cloud.firestore_v1.async_client.AsyncClient", boom)
    with pytest.raises(UpstreamError) as raised:
        audit._get_firestore_client()
    check(raised.value, "Audit Firestore client init failed in live mode")


def test_gcs_client_init_failure(live, monkeypatch) -> None:
    monkeypatch.setattr("google.cloud.storage.Client", boom)
    with pytest.raises(UpstreamError) as raised:
        storage._get_gcs_client()
    check(raised.value, "GCS client init failed in live mode")


def test_bigquery_client_init_failure(live, monkeypatch) -> None:
    monkeypatch.setattr("google.cloud.bigquery.Client", boom)
    with pytest.raises(UpstreamError) as raised:
        bq_tariff._get_bq_client()
    check(raised.value, "BigQuery client init failed in live mode")


def test_gemini_client_init_failure(live, monkeypatch) -> None:
    monkeypatch.setattr("google.genai.Client", boom)
    with pytest.raises(UpstreamError) as raised:
        extraction._get_genai_client()
    check(raised.value, "Gemini client init failed in live mode")


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------


class ExplodingFirestore(FakeFirestore):
    """A Firestore whose queries (``fail_query``) or creates (``fail_create``) raise a secret-bearing exception."""

    def __init__(self, *, fail_query: bool = False, fail_create: bool = False) -> None:
        super().__init__()
        self.fail_query, self.fail_create = fail_query, fail_create
        self.before_create = self._maybe_fail

    def _maybe_fail(self, path, data) -> None:
        if self.fail_create:
            raise RuntimeError(SECRET)

    def collection(self, name: str):
        collection = super().collection(name)
        if self.fail_query:
            collection.order_by = boom
        return collection


@pytest.mark.asyncio
async def test_audit_chain_query_failure(live, monkeypatch) -> None:
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: _ExplodingQueryClient())
    with pytest.raises(UpstreamError) as raised:
        await audit.record({"bundle_id": "bnd-x", "audit_event_type": "X", "audit_payload": {}})
    check(raised.value, "Audit chain query failed in live mode")


class _ExplodingQueryClient:
    def collection(self, name: str):
        return SimpleNamespace(document=lambda _id: SimpleNamespace(collection=lambda _n: SimpleNamespace(order_by=boom)))


@pytest.mark.asyncio
async def test_audit_event_persist_failure(live, monkeypatch) -> None:
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: ExplodingFirestore(fail_create=True))
    with pytest.raises(UpstreamError) as raised:
        await audit.record({"bundle_id": "bnd-x", "audit_event_type": "X", "audit_payload": {}})
    check(raised.value, "Audit event persist failed in live mode")


@pytest.mark.asyncio
async def test_audit_list_failure(live, monkeypatch) -> None:
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: _ExplodingQueryClient())
    with pytest.raises(UpstreamError) as raised:
        await audit.list_audit_events("bnd-x")
    check(raised.value, "List audit events failed in live mode")


@pytest.mark.asyncio
async def test_gcs_upload_failure(monkeypatch) -> None:
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: SimpleNamespace(bucket=boom))
    with pytest.raises(UpstreamError) as raised:
        await storage.upload_raw("bnd-x", b"%PDF-1.4 x", "application/pdf", "a.pdf")
    check(raised.value, "Failed to upload PDF to Cloud Storage")


@pytest.mark.asyncio
async def test_gcs_download_failure(monkeypatch) -> None:
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: SimpleNamespace(bucket=boom))
    with pytest.raises(UpstreamError) as raised:
        await storage.download_raw("bnd-x", "doc-1")
    check(raised.value, "Failed to retrieve PDF from Cloud Storage")


def test_bigquery_query_failure(live, monkeypatch) -> None:
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: SimpleNamespace(query=boom))
    with pytest.raises(UpstreamError) as raised:
        bq_tariff.lookup_tariff_with_source("seamless pipes", "SG")
    check(raised.value, "BigQuery vector query failed")


# ---------------------------------------------------------------------------
# the demo-mode fallbacks still log the full text (for the operator) and still fall back
# ---------------------------------------------------------------------------


def test_demo_mode_fallbacks_are_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: SimpleNamespace(query=boom))
    hits, source = bq_tariff.lookup_tariff_with_source("Seamless steel pipes for gas pipelines", "SG")
    assert source == "seed" and hits


# ---------------------------------------------------------------------------
# a regression net: nothing in app/ interpolates an exception into a message again
# ---------------------------------------------------------------------------


def test_no_app_module_interpolates_exception_text_into_a_raised_error() -> None:
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[2] / "app"
    offenders = []
    pattern = re.compile(r"(Error|Exception)\(\s*f?[\"'][^\"']*\{(exc|e|error|err)(!s|!r)?\}")
    for path in sorted(app_dir.rglob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if pattern.search(line) or re.search(r"Error\([^)]*str\((exc|e|err|error)\)", line):
                offenders.append(f"{path.relative_to(app_dir)}:{number}: {line.strip()}")
    assert offenders == [], "exception text interpolated into a raised error:\n" + "\n".join(offenders)
