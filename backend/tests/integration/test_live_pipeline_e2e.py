"""A2: the LIVE path through the real orchestrator, end to end, with a fake Gemini.

The live pipeline used to be untested as a whole: the smoke script calls preprocess and extraction directly, and the
live-mode tests stub the pipeline. So nobody noticed that the pages were wiped between preprocessing and extraction, and
that live mode raised "no processable pages" on EVERY run.

Here APP_MODE=live, the Firestore / audit / storage / BigQuery clients are patched to None (so the stores are in-memory and
no credential is needed), and a fake async Gemini client answers each request with the extraction of the document it was
sent. The test passes with poppler (PNG pages, page-labelled parts) and without it (raw PDF passthrough, no labels).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents import extraction
from app.agents.tools import bq_tariff
from app.core.config import settings
from app.repo import firestore
from app.services import audit, orchestrator, storage
from tests.helpers import api_client, case_c_pdf, wait_for_run
from tests.unit.extraction_fakes import case_c_gemini, parts_of

PRELOADED = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf")
MTC = "mtc_pipe_test_cert.pdf"


@pytest.fixture
def offline_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_MODE=live with every GCP client getter patched to None: in-memory stores, no credentials, no network."""
    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: None)
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: None)
    monkeypatch.setattr(settings, "app_mode", "live")


async def journey(client: Any) -> dict[str, Any]:
    """Case C through the API: analyze the three preloaded PDFs, upload the MTC, reassess."""
    created = await client.post("/api/v1/bundles", json={"reference": "LIVE-E2E", "destination_country": "SG"})
    assert created.status_code == 201, created.text
    bundle_id = created.json()["id"]

    async def upload(name: str) -> None:
        response = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents", files={"file": (name, case_c_pdf(name), "application/pdf")}
        )
        assert response.status_code == 201, response.text

    async def run(action: str) -> dict[str, Any]:
        response = await client.post(f"/api/v1/bundles/{bundle_id}/{action}")
        assert response.status_code == 202, response.text
        state = await wait_for_run(bundle_id, response.json()["run_id"], timeout=30)
        assert state["state"] == "COMPLETE", state
        return (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()

    for name in PRELOADED:
        await upload(name)
    first = await run("analyze")
    await upload(MTC)
    second = await run("reassess")
    audit_log = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
    return {"bundle_id": bundle_id, "first": first, "second": second, "audit": audit_log}


def shape(iteration: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": iteration["status"],
        "checks": {c["check_id"]: c["severity"] for c in iteration["checks"]},
        "missing": sorted(m["id"] for m in iteration["missing_evidence"]),
        "action": iteration["confidence"]["action"],
    }


@pytest.mark.asyncio
async def test_case_c_through_the_live_pipeline(monkeypatch, offline_live) -> None:
    fake = await case_c_gemini(PRELOADED + (MTC,))
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
    sources: list[Any] = []
    real_dispatch = orchestrator.dispatch

    async def spy(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        result = await real_dispatch(stage, ctx)
        if stage == "extract":
            sources.append(result.get("extraction_source"))
        return result

    monkeypatch.setattr(orchestrator, "dispatch", spy)

    async with api_client() as client:
        live = await journey(client)
        # the same journey in demo mode (fixture extraction, no Gemini) is the reference for statuses and check ids
        monkeypatch.setattr(settings, "app_mode", "demo")
        monkeypatch.setattr(extraction, "_get_genai_client", lambda: None)
        demo = await journey(client)

    first, second = live["first"], live["second"]
    assert first["status"] == "MISSING_EVIDENCE" and first["iteration"] == 1
    assert second["status"] == "COMPLIANT_FOR_SUBMISSION" and second["iteration"] == 2
    assert second["confidence"]["action"] == "AUTO_ACCEPT"
    assert {c["check_id"] for c in first["checks"]} == {
        "W-001", "W-002", "H-002", "E-consignee", "E-consignor", "E-origin", "I-001", "I-002", "I-003", "G-001",
    }
    assert shape(first) == shape(demo["first"]) and shape(second) == shape(demo["second"]), "live == demo, check by check"
    assert live["audit"]["verified"] is True
    assert [e["event_type"] for e in live["audit"]["events"]] == [e["event_type"] for e in demo["audit"]["events"]]

    # Live extraction + the local seed for grounding (the BigQuery getter is patched to None): derive_data_source reports
    # "fixture" as soon as the tariff came from the seed, whatever the extraction was. With real BigQuery it would be "live".
    assert first["data_source"] == second["data_source"] == "fixture"
    assert sources[:2] == ["live", "live"] and set(sources[2:]) == {"fixture"}, "extraction_source: live, then demo's fixtures"

    # The fake saw one request per document that had not been read yet: 3 for the first analysis, and for the reassessment only the
    # certificate that was added (the other three are kept answers: agents/extraction.py::_extract_cached), 4 in all
    assert len(fake.calls) == 4, [len(parts_of(c)) for c in fake.calls]
    assert fake.unknown == [], "every request carried a page of a known Case C document"
    for call in fake.calls:
        parts = parts_of(call)
        pages = [p for p in parts if "data" in p]
        assert len(pages) == 1 and len(pages[0]["data"]) > 0, "one page per Case C PDF, and its payload is not empty"
        labels = [p["text"] for p in parts if p.get("text", "").startswith("Page ")]
        if pages[0]["mime"] == "image/png":  # poppler is installed: rendered pages carry a "Page N of M." label
            assert labels == ["Page 1 of 1."]
        else:  # no poppler: the raw PDF is passed through, which has an unknown page count and gets no label
            assert pages[0]["mime"] == "application/pdf" and labels == []
    assert all(call["model"] == settings.gemini_live_model for call in fake.calls)


@pytest.mark.asyncio
async def test_the_live_pipeline_reads_exactly_the_documents_of_the_bundle(monkeypatch, offline_live) -> None:
    fake = await case_c_gemini(PRELOADED + (MTC,))
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
    async with api_client() as client:
        result = await journey(client)

    ids_first = {d for d in result["first"]["documents"]}
    ids_second = {d for d in result["second"]["documents"]}
    assert len(ids_first) == 3 and len(ids_second) == 4 and ids_first < ids_second
    stats_calls_first, stats_calls_second = fake.calls[:3], fake.calls[3:]
    assert len(stats_calls_first) == 3 and len(stats_calls_second) == 1, "the reassessment reads only the document that is new"
