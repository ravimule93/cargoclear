"""A3: GET /bundles/{id}/iterations answers 404 for an unknown bundle, like every other bundle route."""

from __future__ import annotations

import pytest

from tests.helpers import api_client, asgi_call, create_bundle_with_documents, wait_for_run

BUNDLE_ROUTES = ["", "/audit", "/extractions", "/assessment", "/iterations"]


@pytest.mark.asyncio
async def test_an_unknown_bundle_has_no_iterations_route() -> None:
    async with api_client() as client:
        response = await client.get("/api/v1/bundles/bnd-0123456789ab/iterations")

    assert response.status_code == 404, response.text
    body = response.json()
    assert body["code"] == "NOT_FOUND" and set(body) == {"code", "message", "detail", "request_id"}
    assert body["message"] == "Bundle 'bnd-0123456789ab' not found."
    assert body["detail"] == {"bundle_id": "bnd-0123456789ab"}


@pytest.mark.asyncio
@pytest.mark.parametrize("route", BUNDLE_ROUTES, ids=lambda r: r or "bundle")
async def test_every_bundle_route_answers_the_same_404_for_an_unknown_id(route) -> None:
    result = await asgi_call("GET", f"/api/v1/bundles/bnd-0123456789ab{route}")

    assert result.status == 404 and result.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_a_known_bundle_without_runs_still_answers_an_empty_list() -> None:
    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={})).json()["id"]
        response = await client.get(f"/api/v1/bundles/{bundle_id}/iterations")

    assert response.status_code == 200 and response.json() == []


@pytest.mark.asyncio
async def test_a_known_bundle_lists_its_iterations_in_order() -> None:
    from app.services import orchestrator

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, {"commercial_invoice.pdf": b"%PDF-1.4 iterations"})
        for _ in range(2):
            assert (await wait_for_run(bundle_id, await orchestrator.start_run(bundle_id)))["state"] == "COMPLETE"
        response = await client.get(f"/api/v1/bundles/{bundle_id}/iterations")

    assert response.status_code == 200 and [i["iteration"] for i in response.json()] == [1, 2]
