"""Live mode must never fall back to fixtures; demo mode may.

B1: extraction used to generate fixtures whenever it had no pages to send, even with APP_MODE=live and
a Gemini client present. A preprocess failure was also swallowed in every mode.
"""

from __future__ import annotations

import pytest

from app.agents import extraction
from app.agents.extraction import run_extraction_agent
from app.core.config import settings
from app.domain.schemas import ExtractedDocument
from app.gateway.errors import ExtractionError
from app.repo import firestore
from app.services import audit, orchestrator, storage
from tests.helpers import api_client, create_bundle_with_documents, wait_for_run


class StubGenaiClient:
    """Stands in for a configured Vertex client; any use of it would be a bug in these tests."""

    class aio:  # noqa: N801 - mimics client.aio (extraction awaits client.aio.models.generate_content)
        class models:  # noqa: N801 - mimics client.aio.models
            @staticmethod
            async def generate_content(*_args, **_kwargs):
                raise AssertionError("Gemini must not be called when there are no pages to send")


@pytest.fixture
def offline_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep live-mode runs in-process: no Firestore/GCS/BigQuery credentials are needed or used."""
    from app.agents.tools import bq_tariff

    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: None)


DOCS = [
    {"document_id": "doc-inv", "filename": "commercial_invoice.pdf"},
    {"document_id": "doc-bol", "filename": "bill_of_lading.pdf"},
]


@pytest.fixture
def stub_client(monkeypatch: pytest.MonkeyPatch) -> StubGenaiClient:
    client = StubGenaiClient()
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: client)
    return client


@pytest.mark.asyncio
async def test_live_mode_with_client_but_no_pages_raises_instead_of_using_fixtures(
    monkeypatch: pytest.MonkeyPatch, stub_client: StubGenaiClient, offline_backends: None
) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")
    ctx = {"bundle_id": "bnd-live", "documents": list(DOCS), "processed_pages": []}

    with pytest.raises(ExtractionError, match="no processable pages"):
        await run_extraction_agent(ctx)

    assert "extracted" not in ctx, "no fixture documents may be produced in live mode"


@pytest.mark.asyncio
async def test_demo_mode_with_client_but_no_pages_still_uses_fixtures(
    monkeypatch: pytest.MonkeyPatch, stub_client: StubGenaiClient
) -> None:
    monkeypatch.setattr(settings, "app_mode", "demo")
    ctx = {"bundle_id": "bnd-demo", "documents": list(DOCS), "processed_pages": []}

    result = await run_extraction_agent(ctx)

    assert [d.doc_type for d in result["extracted"]] == ["COMMERCIAL_INVOICE", "BILL_OF_LADING"]
    assert all(isinstance(d, ExtractedDocument) for d in result["extracted"])


@pytest.mark.asyncio
async def test_demo_mode_without_client_uses_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: None)
    ctx = {"bundle_id": "bnd-demo", "documents": list(DOCS), "processed_pages": []}

    result = await run_extraction_agent(ctx)

    assert len(result["extracted"]) == 2


# ---------------------------------------------------------------------------
# Orchestrator: a preprocess failure is fatal in live mode, tolerated in demo mode
# ---------------------------------------------------------------------------


async def _bundle_with_two_documents() -> str:
    async with api_client() as client:
        return await create_bundle_with_documents(
            client,
            {"commercial_invoice.pdf": b"%PDF-1.4 invoice", "bill_of_lading.pdf": b"%PDF-1.4 bol"},
        )


@pytest.mark.asyncio
async def test_live_mode_preprocess_failure_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, stub_client: StubGenaiClient, offline_backends: None
) -> None:
    bundle_id = await _bundle_with_two_documents()
    monkeypatch.setattr(settings, "app_mode", "live")

    async def broken_download(_bundle_id: str, document_id: str) -> bytes:
        raise RuntimeError(f"storage unavailable for {document_id}")

    monkeypatch.setattr(storage, "download_raw", broken_download)

    run_id = await orchestrator.start_run(bundle_id)
    state = await wait_for_run(bundle_id, run_id)

    assert state["state"] == "ERROR"
    # the class name, not the text of the exception (which can carry paths or content)
    assert state["message"].startswith("Preprocessing failed for document ")
    assert state["message"].endswith(": RuntimeError")
    assert "storage unavailable" not in state["message"]
    assert await firestore.latest_iteration(bundle_id) is None, "a failed run must not persist an iteration"


@pytest.mark.asyncio
async def test_demo_mode_preprocess_failure_warns_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_id = await _bundle_with_two_documents()

    async def broken_download(_bundle_id: str, document_id: str) -> bytes:
        raise RuntimeError(f"storage unavailable for {document_id}")

    monkeypatch.setattr(storage, "download_raw", broken_download)

    run_id = await orchestrator.start_run(bundle_id)
    state = await wait_for_run(bundle_id, run_id)

    assert state["state"] == "COMPLETE"
    iteration = await firestore.latest_iteration(bundle_id)
    assert iteration is not None
    assert iteration["iteration"] == 1
