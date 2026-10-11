"""A1: the pages rendered by the "preprocess" stage must still be there when extraction starts.

Before the fix the loop ran ``dispatch("preprocess", ctx)`` with the PIPELINE ctx (no ``raw_bytes``) right after the
bundle had been rendered, and ``preprocess.run`` answered an empty page list: extract, discrepancy and ground all
started with 0 pages. Demo mode hid it (the fixture extractor only needs filenames); live mode raised "no processable
pages" on every run. The assertions hold with poppler (3 PNG pages) and without it (3 passthrough PDF pages).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import settings
from app.services import audit, orchestrator, storage
from tests.helpers import api_client, case_c_pdf, create_bundle_with_documents, wait_for_run

PRELOADED = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf")
STAGES_AFTER_PREPROCESS = ("extract", "discrepancy", "ground", "confidence", "synthesize")


def describe(pages: list[dict[str, Any]] | None) -> list[tuple[str, str, int]] | None:
    return None if pages is None else [(p["document_id"], p["mime"], len(p["payload"])) for p in pages]


async def run_case_c_with_a_spy(monkeypatch) -> tuple[list[str], dict[str, list[Any]], dict[str, Any]]:
    """Run the three preloaded Case C PDFs; return (document ids, what each dispatch call saw, final run state)."""
    seen: dict[str, list[Any]] = {}
    real = orchestrator.dispatch

    async def spy(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
        seen.setdefault(stage, []).append({"raw": bool(ctx.get("raw_bytes")), "pages": describe(ctx.get("processed_pages"))})
        return await real(stage, ctx)

    monkeypatch.setattr(orchestrator, "dispatch", spy)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, {name: case_c_pdf(name) for name in PRELOADED})
        documents = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]
        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)
    return [d["document_id"] for d in documents], seen, state


@pytest.mark.asyncio
async def test_extract_discrepancy_and_ground_start_with_the_pages_of_all_documents(monkeypatch) -> None:
    doc_ids, seen, state = await run_case_c_with_a_spy(monkeypatch)

    assert state["state"] == "COMPLETE", state
    [at_extract] = [call["pages"] for call in seen["extract"]]
    assert at_extract is not None and len(at_extract) == 3, f"extract started with {at_extract}"
    assert sorted(doc_id for doc_id, _mime, _size in at_extract) == sorted(doc_ids), "one page per document, all documents"
    mimes = {mime for _doc, mime, _size in at_extract}
    assert mimes in ({"image/png"}, {"application/pdf"}), f"all PNG (poppler) or all passthrough PDF (no poppler): {mimes}"
    assert all(size > 0 for _doc, _mime, size in at_extract), "no empty payload"

    for stage in STAGES_AFTER_PREPROCESS:
        [call] = seen[stage]
        assert call["pages"] == at_extract, f"{stage} saw different pages than extract: {call['pages']}"


@pytest.mark.asyncio
async def test_the_preprocess_stage_only_dispatches_per_document_calls_that_carry_the_document_bytes(monkeypatch) -> None:
    _ids, seen, _state = await run_case_c_with_a_spy(monkeypatch)

    assert len(seen["preprocess"]) == 3, "one call per document, and no call with the pipeline ctx (which has no raw_bytes)"
    assert all(call["raw"] for call in seen["preprocess"])


@pytest.mark.asyncio
async def test_the_preprocess_stage_reports_its_progress_before_the_work(monkeypatch) -> None:
    from app.repo import firestore

    events: list[str] = []
    real_stage, real_dispatch = firestore.set_run_stage, orchestrator.dispatch

    async def stage_spy(bundle_id, run_id, stage, progress):
        events.append(f"stage:{stage}")
        return await real_stage(bundle_id, run_id, stage=stage, progress=progress)

    async def dispatch_spy(stage, ctx):
        events.append(f"work:{stage}")
        return await real_dispatch(stage, ctx)

    monkeypatch.setattr(firestore, "set_run_stage", stage_spy)
    monkeypatch.setattr(orchestrator, "dispatch", dispatch_spy)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, {"commercial_invoice.pdf": case_c_pdf("commercial_invoice.pdf")})
        run_id = await orchestrator.start_run(bundle_id)
        await wait_for_run(bundle_id, run_id)

    assert events.index("stage:preprocess") < events.index("work:preprocess"), events
    assert events.index("work:preprocess") < events.index("stage:extract"), events


@pytest.mark.asyncio
async def test_a_live_mode_preprocess_failure_is_audited_at_the_preprocess_stage(monkeypatch) -> None:
    from app.agents.tools import bq_tariff
    from app.repo import firestore

    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: None)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, {"commercial_invoice.pdf": b"%PDF-1.4 invoice"})
        monkeypatch.setattr(settings, "app_mode", "live")

        async def broken_download(_bundle_id: str, document_id: str) -> bytes:
            raise FileNotFoundError(f"/Users/someone/secret/{document_id}")

        monkeypatch.setattr(storage, "download_raw", broken_download)
        run_id = await orchestrator.start_run(bundle_id)
        state = await wait_for_run(bundle_id, run_id)
        events = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["events"]

    failed = [e for e in events if e["event_type"] == "ANALYSIS_FAILED"]
    assert state["state"] == "ERROR" and state["message"].endswith(": FileNotFoundError")
    assert len(failed) == 1 and failed[0]["payload"]["stage"] == "preprocess"
    assert "secret" not in str(events) and "secret" not in state["message"]
