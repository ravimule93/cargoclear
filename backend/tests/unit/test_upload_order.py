"""POST /bundles/{id}/documents: the cheap refusals come before the paid check, and two uploads of the same new file pay for it once.

The relevance check is wrapped, not replaced: the real one runs (free for the real Case C PDFs, whose text names them) and the wrapper
counts the calls and can hold one back. Real poppler, real PDFs, no network."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.config import settings
from app.services import relevance
from tests.helpers import api_client, case_c_pdf


@pytest.fixture
def gate_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = relevance.check_document

    async def counting(data: bytes) -> Any:
        calls.append(len(data))
        await asyncio.sleep(0.05)  # long enough for a second upload to arrive while the first is being checked
        return await real(data)

    monkeypatch.setattr(relevance, "check_document", counting)
    return calls


async def new_bundle(client: Any) -> str:
    return (await client.post("/api/v1/bundles", json={"reference": "ORDER", "destination_country": "SG"})).json()["id"]


async def upload(client: Any, bundle_id: str, name: str) -> Any:
    return await client.post(f"/api/v1/bundles/{bundle_id}/documents", files={"file": (name, case_c_pdf(name), "application/pdf")})


@pytest.mark.asyncio
async def test_a_file_that_cannot_be_added_to_a_full_bundle_is_refused_before_the_model_is_asked(gate_calls, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_documents_per_bundle", 1)
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        assert (await upload(client, bundle_id, "commercial_invoice.pdf")).status_code == 201
        assert gate_calls == [len(case_c_pdf("commercial_invoice.pdf"))]

        refused = await upload(client, bundle_id, "bill_of_lading.pdf")

    assert refused.status_code == 422 and "at most 1 documents" in refused.json()["message"]
    assert len(gate_calls) == 1  # the second file never reached the check


@pytest.mark.asyncio
async def test_two_uploads_of_the_same_new_file_at_once_ask_the_model_once(gate_calls) -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        first, second = await asyncio.gather(
            upload(client, bundle_id, "commercial_invoice.pdf"), upload(client, bundle_id, "commercial_invoice.pdf")
        )
        listed = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]

    assert first.status_code == second.status_code == 201
    assert len(gate_calls) == 1 and len(listed) == 1  # the second found the document registered by the first


@pytest.mark.asyncio
async def test_two_different_files_are_checked_side_by_side_not_one_after_the_other(gate_calls, monkeypatch) -> None:
    active = 0
    most = 0
    real = relevance.check_document

    async def overlapping(data: bytes) -> Any:
        nonlocal active, most
        active += 1
        most = max(most, active)
        await asyncio.sleep(0.1)
        try:
            return await real(data)
        finally:
            active -= 1

    monkeypatch.setattr(relevance, "check_document", overlapping)
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        responses = await asyncio.gather(upload(client, bundle_id, "commercial_invoice.pdf"), upload(client, bundle_id, "bill_of_lading.pdf"))

    assert [r.status_code for r in responses] == [201, 201] and most == 2  # one file's model call does not hold up another file


@pytest.mark.asyncio
async def test_a_file_already_in_the_bundle_is_not_checked_again(gate_calls) -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        await upload(client, bundle_id, "commercial_invoice.pdf")

        again = await upload(client, bundle_id, "commercial_invoice.pdf")

    assert again.status_code == 201 and len(gate_calls) == 1
