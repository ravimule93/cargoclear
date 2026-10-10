"""D2: MAX_CONCURRENT_RUNS. One more analysis than the cap is refused with 429 SERVICE_BUSY and Retry-After: 5."""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.repo import firestore
from app.services import orchestrator
from tests.helpers import api_client, create_bundle_with_documents, wait_for_run
from tests.unit.test_run_lifecycle import events_of, stall, wait_until, yielding

FILES = {"commercial_invoice.pdf": b"%PDF-1.4 cap invoice"}
BUSY = "The service is busy analysing other bundles. Try again shortly."


async def three_bundles(client) -> list[str]:
    return [await create_bundle_with_documents(client, FILES, reference=f"CAP-{i}") for i in range(3)]


async def release_all() -> None:
    await orchestrator.shutdown(timeout=5)


@pytest.mark.asyncio
async def test_the_default_cap_is_four() -> None:
    assert settings.max_concurrent_runs == 4


@pytest.mark.asyncio
async def test_the_run_over_the_cap_is_refused_and_writes_nothing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_runs", 2)
    async with api_client() as client:
        first, second, third = await three_bundles(client)
        stall(monkeypatch, "extract", 30)
        assert (await client.post(f"/api/v1/bundles/{first}/analyze")).status_code == 202
        assert (await client.post(f"/api/v1/bundles/{second}/reassess")).status_code == 202

        refused = await client.post(f"/api/v1/bundles/{third}/analyze")

        assert refused.status_code == 429
        body = refused.json()
        assert (body["code"], body["message"]) == ("SERVICE_BUSY", BUSY)
        assert refused.headers["retry-after"] == "5"
        assert body["request_id"] == refused.headers["x-request-id"]
        assert (await firestore.get_run_state(third))["message"] == "Ready", "no run record was written"
        assert await events_of(client, third, "ANALYSIS_STARTED") == []
        await release_all()


@pytest.mark.asyncio
async def test_a_slot_is_free_again_when_a_run_ends(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_runs", 1)
    async with api_client() as client:
        first, second, _ = await three_bundles(client)
        stall(monkeypatch, "extract", 0.3)
        run_id = (await client.post(f"/api/v1/bundles/{first}/analyze")).json()["run_id"]
        assert (await client.post(f"/api/v1/bundles/{second}/analyze")).status_code == 429

        assert (await wait_for_run(first, run_id))["state"] == "COMPLETE"
        await wait_until(lambda: _no_live_tasks())

        assert (await client.post(f"/api/v1/bundles/{second}/analyze")).status_code == 202
        await release_all()


async def _no_live_tasks() -> bool:
    return not [t for t in orchestrator._RUNNING_TASKS if not t.done()]


@pytest.mark.asyncio
async def test_a_failed_run_also_releases_its_slot(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_runs", 1)
    async with api_client() as client:
        first, second, _ = await three_bundles(client)
        real = orchestrator.dispatch

        async def broken(stage, ctx):
            if stage == "extract":
                raise RuntimeError("boom")
            return await real(stage, ctx)

        monkeypatch.setattr(orchestrator, "dispatch", broken)
        run_id = (await client.post(f"/api/v1/bundles/{first}/analyze")).json()["run_id"]
        assert (await wait_for_run(first, run_id))["state"] == "ERROR"
        await wait_until(lambda: _no_live_tasks())
        monkeypatch.setattr(orchestrator, "dispatch", real)

        assert (await client.post(f"/api/v1/bundles/{second}/analyze")).status_code == 202


@pytest.mark.asyncio
async def test_simultaneous_starts_on_different_bundles_cannot_overshoot_the_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_runs", 2)
    monkeypatch.setattr(settings, "rate_limit_runs_per_minute", 0)
    async with api_client() as client:
        bundles = [await create_bundle_with_documents(client, FILES, reference=f"S-{i}") for i in range(6)]
        monkeypatch.setattr(firestore, "get_run_state", yielding(firestore.get_run_state))
        monkeypatch.setattr(firestore, "latest_iteration", yielding(firestore.latest_iteration))
        stall(monkeypatch, "extract", 30)

        responses = await asyncio.gather(*[client.post(f"/api/v1/bundles/{b}/analyze") for b in bundles])

        assert sorted(r.status_code for r in responses) == [202, 202, 429, 429, 429, 429]
        await release_all()


@pytest.mark.asyncio
async def test_zero_switches_the_cap_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_runs", 0)
    monkeypatch.setattr(settings, "rate_limit_runs_per_minute", 0)
    async with api_client() as client:
        bundles = [await create_bundle_with_documents(client, FILES, reference=f"Z-{i}") for i in range(7)]
        stall(monkeypatch, "extract", 30)

        responses = await asyncio.gather(*[client.post(f"/api/v1/bundles/{b}/analyze") for b in bundles])

        assert {r.status_code for r in responses} == {202}
        await release_all()


@pytest.mark.asyncio
async def test_a_bundle_that_is_already_running_is_a_409_not_a_429(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_runs", 1)
    async with api_client() as client:
        first, _, _ = await three_bundles(client)
        stall(monkeypatch, "extract", 30)
        assert (await client.post(f"/api/v1/bundles/{first}/analyze")).status_code == 202

        again = await client.post(f"/api/v1/bundles/{first}/analyze")

        assert again.status_code == 409 and again.json()["code"] == "CONFLICT"
        await release_all()


@pytest.mark.asyncio
async def test_an_empty_bundle_is_a_422_even_when_the_service_is_busy(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_runs", 1)
    async with api_client() as client:
        first, _, _ = await three_bundles(client)
        empty = (await client.post("/api/v1/bundles", json={})).json()["id"]
        stall(monkeypatch, "extract", 30)
        await client.post(f"/api/v1/bundles/{first}/analyze")

        response = await client.post(f"/api/v1/bundles/{empty}/analyze")

        assert response.status_code == 422
        await release_all()


@pytest.mark.asyncio
async def test_a_refused_start_leaves_no_reservation_behind(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_runs", 1)
    async with api_client() as client:
        first, second, _ = await three_bundles(client)
        stall(monkeypatch, "extract", 30)
        await client.post(f"/api/v1/bundles/{first}/analyze")
        for _ in range(3):
            assert (await client.post(f"/api/v1/bundles/{second}/analyze")).status_code == 429

        assert orchestrator._starting_runs == 0
        await release_all()
