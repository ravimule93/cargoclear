"""Phase 0: blocking Google Cloud calls must not run on the event loop.

The API is one process. The event loop carries the run heartbeat (a silent heartbeat makes the reaper declare a live run
dead), every SSE stream and every other request. A blocking BigQuery or Cloud Storage call made directly in an ``async
def`` freezes all of that for as long as the call takes, so each such call runs in a worker thread.

The proof used throughout: a "ticker" task wakes every 10 ms while the slow call is in progress. If the call blocked the
loop the ticker would not have run; offloaded, it ticks about every 10 ms.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents import grounding
from app.agents.tools import bq_tariff
from app.core.concurrency import gather_in_order
from app.core.config import settings
from app.domain.schemas import ExtractedDocument, FieldRef, LineItem
from app.gateway.errors import UpstreamError
from app.services import storage

SLOW = 0.3
MIN_TICKS = 5  # 0.3 s at 10 ms; a blocked loop gives 0 or 1 (Windows sleep resolution is ~15.6ms)


async def ticks_during(work: Awaitable[Any], interval: float = 0.01) -> tuple[Any, int]:
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(interval)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await work
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return result, ticks


# ---------------------------------------------------------------------------
# tariff lookups (grounding)
# ---------------------------------------------------------------------------


def ref(value: str) -> FieldRef:
    return FieldRef(value=value, confidence=0.98)


def invoice(*descriptions: str, document_id: str = "inv-1", doc_type: str = "COMMERCIAL_INVOICE") -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id,
        doc_type=doc_type,
        doc_type_confidence=0.99,
        line_items=[
            LineItem(
                description=ref(text), quantity=ref("1"), net_weight_kg=ref("1"), gross_weight_kg=ref("1"),
                hs_code_declared=ref("73041900"),
            )
            for text in descriptions
        ],
    )


def candidate(hs: str = "73041900", distance: float = 0.08) -> dict[str, Any]:
    return {
        "hs_code": hs, "description": "Line pipe", "required_documents": ["MILL_TEST_CERTIFICATE"],
        "distance": distance, "rule_set": "demo-curated", "regulation_ref": "Demo rule set (prototype)",
    }


@pytest.mark.asyncio
async def test_a_slow_tariff_lookup_does_not_freeze_the_event_loop(monkeypatch) -> None:
    def slow_lookup(description: str, destination_country: str = "SG"):
        time.sleep(SLOW)  # a BLOCKING call, like the real BigQuery job
        return [candidate()], "bigquery"

    monkeypatch.setattr(grounding, "lookup_tariff_with_source", slow_lookup)

    ctx, ticks = await ticks_during(grounding.run_grounding_agent({"extracted": [invoice("Seamless pipes")]}))

    assert ticks >= MIN_TICKS, f"the loop ran only {ticks} ticks during a {SLOW}s lookup: it was blocked"
    assert ctx["grounding_source"] == "bigquery"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 2, 4])
async def test_lookups_run_concurrently_up_to_the_configured_cap(monkeypatch, limit) -> None:
    monkeypatch.setattr(settings, "tariff_lookup_concurrency", limit)
    lock, state = threading.Lock(), {"active": 0, "peak": 0}

    def lookup(description: str, destination_country: str = "SG"):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.1)
        with lock:
            state["active"] -= 1
        return [candidate()], "seed"

    monkeypatch.setattr(grounding, "lookup_tariff_with_source", lookup)
    docs = [invoice("pipes A", "pipes B", "pipes C", "pipes D")]

    started = time.perf_counter()
    await grounding.run_grounding_agent({"extracted": docs})
    elapsed = time.perf_counter() - started

    assert state["peak"] == limit
    assert elapsed < 0.1 * 4 / limit + 0.25  # four 0.1 s lookups, `limit` at a time


@pytest.mark.asyncio
async def test_an_identical_description_is_looked_up_once(monkeypatch) -> None:
    seen: list[str] = []

    def lookup(description: str, destination_country: str = "SG"):
        seen.append(description)
        return [candidate()], "seed"

    monkeypatch.setattr(grounding, "lookup_tariff_with_source", lookup)
    docs = [invoice("Seamless pipes", "Seamless pipes", document_id="inv-1"), invoice("Seamless pipes", document_id="pl-1", doc_type="PACKING_LIST")]

    ctx = await grounding.run_grounding_agent({"extracted": docs})

    assert seen == ["Seamless pipes"]
    assert len(ctx["grounding"]) == 3  # every line is still judged


@pytest.mark.asyncio
async def test_results_follow_the_input_order_whatever_finishes_first(monkeypatch) -> None:
    def lookup(description: str, destination_country: str = "SG"):
        time.sleep(0.25 if description == "slow pipes" else 0.0)
        return [candidate("73041900" if description == "slow pipes" else "73043100")], "seed"

    monkeypatch.setattr(grounding, "lookup_tariff_with_source", lookup)
    ctx = await grounding.run_grounding_agent({"extracted": [invoice("slow pipes", "quick pipes")]})

    assert [f["declared_hs"] for f in ctx["grounding"]] == ["73041900", "73041900"]
    assert [f["top_candidate_hs"] for f in ctx["grounding"]] == ["73041900", "73043100"]


@pytest.mark.asyncio
async def test_a_failed_lookup_surfaces_as_its_own_error_not_an_exception_group(monkeypatch) -> None:
    def lookup(description: str, destination_country: str = "SG"):
        if description == "boom":
            raise UpstreamError("BigQuery vector query failed: Forbidden")
        time.sleep(0.05)
        return [candidate()], "bigquery"

    monkeypatch.setattr(grounding, "lookup_tariff_with_source", lookup)

    with pytest.raises(UpstreamError, match="BigQuery vector query failed"):
        await grounding.run_grounding_agent({"extracted": [invoice("fine pipes", "boom", "other pipes")]})


@pytest.mark.asyncio
async def test_the_bigquery_wait_is_bounded(monkeypatch) -> None:
    waits: list[Any] = []

    class Job:
        def result(self, timeout=None):
            waits.append(timeout)
            return [{"hs_code": "73041900", "description": "d", "required_documents": [], "distance": 0.05}]

    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: SimpleNamespace(query=lambda *_a, **_k: Job()))
    monkeypatch.setattr(settings, "bq_query_timeout_seconds", 7.5)

    _hits, source = bq_tariff.lookup_tariff_with_source("pipes", "SG")

    assert source == "bigquery"
    assert waits == [7.5]


# ---------------------------------------------------------------------------
# Cloud Storage
# ---------------------------------------------------------------------------


class SlowBlob:
    def __init__(self, store: dict[str, bytes], path: str) -> None:
        self.store, self.path, self.metadata = store, path, None

    def upload_from_string(self, data: Any, content_type: str | None = None) -> None:
        time.sleep(SLOW / 2)
        self.store[self.path] = data if isinstance(data, bytes) else str(data).encode()

    def exists(self) -> bool:
        time.sleep(SLOW / 2)
        return self.path in self.store

    def download_as_bytes(self) -> bytes:
        time.sleep(SLOW / 2)
        return self.store[self.path]


def slow_gcs(store: dict[str, bytes]) -> SimpleNamespace:
    bucket = SimpleNamespace(blob=lambda path: SlowBlob(store, path))
    return SimpleNamespace(bucket=lambda _name: bucket)


PDF = b"%PDF-1.4 slow"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["upload_raw", "download_raw", "upload_transform_meta", "download_transform_meta", "upload_processed_artifacts"],
)
async def test_no_cloud_storage_call_freezes_the_event_loop(monkeypatch, operation) -> None:
    store = {
        "bundles/b1/raw/doc-1/original.pdf": PDF,
        "bundles/b1/processed/doc-1/transform.json": json.dumps([{"page": 1}]).encode(),
    }
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: slow_gcs(store))
    calls = {
        "upload_raw": lambda: storage.upload_raw("b1", PDF, filename="a.pdf"),
        "download_raw": lambda: storage.download_raw("b1", "doc-1"),
        "upload_transform_meta": lambda: storage.upload_transform_meta("b1", "doc-1", [{"page": 1}]),
        "download_transform_meta": lambda: storage.download_transform_meta("b1", "doc-1"),
        "upload_processed_artifacts": lambda: storage.upload_processed_artifacts(
            "b1", "doc-1", [{"artifact_id": "part-001", "payload": b"%PDF part"}]
        ),
    }

    _result, ticks = await ticks_during(calls[operation]())

    assert ticks >= MIN_TICKS, f"{operation}: the loop ran only {ticks} ticks: it was blocked"


@pytest.mark.asyncio
async def test_storage_results_are_unchanged_by_the_offload(monkeypatch) -> None:
    store: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: slow_gcs(store))

    meta = await storage.upload_raw("b1", PDF, filename="a.pdf")
    assert await storage.download_raw("b1", meta["document_id"]) == PDF
    assert json.loads(store[f"bundles/b1/raw/{meta['document_id']}/meta.json"])["filename"] == "a.pdf"

    uri = await storage.upload_transform_meta("b1", "doc-1", [{"page": 2}])
    assert uri.endswith("bundles/b1/processed/doc-1/transform.json")
    assert await storage.download_transform_meta("b1", "doc-1") == [{"page": 2}]

    with pytest.raises(Exception, match="not found"):
        await storage.download_raw("b1", "doc-missing")


# ---------------------------------------------------------------------------
# client creation under threads
# ---------------------------------------------------------------------------


def test_concurrent_lookups_build_the_bigquery_client_once(monkeypatch) -> None:
    from google.cloud import bigquery

    built: list[object] = []

    class Client:
        def __init__(self, **_kwargs: Any) -> None:
            time.sleep(0.05)  # long enough for every thread to be inside the constructor window
            built.append(self)

    monkeypatch.setattr(bigquery, "Client", Client)
    monkeypatch.setattr(bq_tariff, "use_live_gcp", lambda: True)
    monkeypatch.setattr(bq_tariff, "_bq_client", None)

    results: list[object] = []
    threads = [threading.Thread(target=lambda: results.append(bq_tariff._get_bq_client())) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(built) == 1
    assert len({id(r) for r in results}) == 1


def test_concurrent_calls_build_the_cloud_storage_client_once(monkeypatch) -> None:
    from google.cloud import storage as gcs_lib

    built: list[object] = []

    class Client:
        def __init__(self, **_kwargs: Any) -> None:
            time.sleep(0.05)
            built.append(self)

    monkeypatch.setattr(gcs_lib, "Client", Client)
    monkeypatch.setattr(storage, "use_live_gcp", lambda: True)
    monkeypatch.setattr(storage, "_gcs_client", None)

    results: list[object] = []
    threads = [threading.Thread(target=lambda: results.append(storage._get_gcs_client())) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(built) == 1
    assert len({id(r) for r in results}) == 1


# ---------------------------------------------------------------------------
# gather_in_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_in_order_returns_results_in_input_order_and_accepts_nothing() -> None:
    async def after(delay: float, value: str) -> str:
        await asyncio.sleep(delay)
        return value

    assert await gather_in_order([after(0.05, "a"), after(0.0, "b")]) == ["a", "b"]
    assert await gather_in_order([]) == []


@pytest.mark.asyncio
async def test_gather_in_order_cancels_the_siblings_and_raises_the_failure_itself() -> None:
    cancelled: list[str] = []

    async def hang(name: str) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    async def fail() -> None:
        await asyncio.sleep(0.01)
        raise UpstreamError("down")

    with pytest.raises(UpstreamError, match="down"):
        await gather_in_order([hang("a"), fail(), hang("b")])

    assert sorted(cancelled) == ["a", "b"]
