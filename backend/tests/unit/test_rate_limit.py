"""D1 through the real app: writes and runs are rate limited per client address; reads and the stream are not."""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from tests.helpers import api_client, asgi_call, create_bundle_with_documents

FILES = {"commercial_invoice.pdf": b"%PDF-1.4 rate invoice"}
PEER = ("10.0.0.1", 40000)


async def post_bundle(client=None, *, peer=PEER, headers=None):
    return await asgi_call("POST", "/api/v1/bundles", body=b"{}", headers={"content-type": "application/json", **(headers or {})}, client=peer)


@pytest.mark.asyncio
async def test_the_61st_write_in_a_minute_is_refused_with_retry_after() -> None:
    assert settings.rate_limit_writes_per_minute == 60
    results = [await post_bundle() for _ in range(60)]
    assert {r.status for r in results} == {201}

    refused = await post_bundle()

    assert refused.status == 429
    body = refused.json()
    assert set(body) == {"code", "message", "detail", "request_id"}
    assert body["code"] == "RATE_LIMITED"
    retry_after = int(refused.headers["retry-after"])
    assert 1 <= retry_after <= 60
    assert body["message"] == f"Too many requests. Try again in {retry_after} seconds."
    assert body["request_id"] == refused.headers["x-request-id"]
    assert refused.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_a_refused_request_never_reaches_the_application() -> None:
    from app.repo import firestore

    for _ in range(60):
        await post_bundle()
    before = len(firestore._IN_MEMORY_BUNDLES)

    await post_bundle()

    assert len(firestore._IN_MEMORY_BUNDLES) == before == 60


@pytest.mark.asyncio
async def test_another_client_address_has_its_own_budget() -> None:
    for _ in range(61):
        await post_bundle(peer=("10.0.0.1", 1))

    other = await post_bundle(peer=("10.0.0.2", 1))

    assert other.status == 201


@pytest.mark.asyncio
async def test_the_peer_port_does_not_matter() -> None:
    for port in range(61):
        await post_bundle(peer=("10.0.0.1", 1000 + port))

    assert (await post_bundle(peer=("10.0.0.1", 9))).status == 429


@pytest.mark.asyncio
async def test_documents_and_the_demo_route_spend_the_same_write_budget(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 3)
    bundle = (await post_bundle()).json()["id"]  # write 1
    upload_body = b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4 x\r\n--b--\r\n'
    upload = await asgi_call(
        "POST", f"/api/v1/bundles/{bundle}/documents", body=upload_body,
        headers={"content-type": "multipart/form-data; boundary=b"}, client=PEER,
    )  # write 2
    demo = await asgi_call("POST", "/api/v1/demo/case-c", client=PEER)  # write 3

    refused = await post_bundle()  # write 4

    assert (upload.status, demo.status, refused.status) == (201, 201, 429)


@pytest.mark.asyncio
async def test_runs_have_their_own_smaller_budget_shared_by_analyze_and_reassess(monkeypatch) -> None:
    assert settings.rate_limit_runs_per_minute == 10
    monkeypatch.setattr(settings, "rate_limit_runs_per_minute", 4)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)

    statuses = []
    for index in range(6):
        verb = "analyze" if index % 2 == 0 else "reassess"
        statuses.append((await asgi_call("POST", f"/api/v1/bundles/{bundle_id}/{verb}", client=PEER)).status)
        await asyncio.sleep(0.05)  # let each run finish so a 409 does not hide the limit

    assert statuses[:4] == [202, 202, 202, 202] and statuses[4:] == [429, 429]


@pytest.mark.asyncio
async def test_writes_and_runs_are_separate_buckets(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)  # spends writes of the test client's address
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 1)
    await post_bundle()  # PEER's single write

    assert (await post_bundle()).status == 429
    assert (await asgi_call("POST", f"/api/v1/bundles/{bundle_id}/analyze", client=PEER)).status == 202


@pytest.mark.asyncio
async def test_reads_and_the_stream_are_never_limited(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_runs_per_minute", 1)
    bundle = (await post_bundle()).json()["id"]
    assert (await post_bundle()).status == 429

    statuses = [(await asgi_call("GET", f"/api/v1/bundles/{bundle}", client=PEER)).status for _ in range(150)]
    statuses += [(await asgi_call("GET", "/healthz", client=PEER)).status for _ in range(50)]
    stream = await asgi_call("GET", f"/api/v1/bundles/{bundle}/stream", client=PEER, until=b"event: status")

    assert set(statuses) == {200}
    assert stream.status == 200


@pytest.mark.asyncio
async def test_a_setting_of_zero_switches_a_class_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 0)
    monkeypatch.setattr(settings, "rate_limit_runs_per_minute", 0)

    statuses = [(await post_bundle()).status for _ in range(80)]

    assert set(statuses) == {201}


@pytest.mark.asyncio
async def test_a_refused_upload_is_refused_before_its_body_is_read(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 1)
    bundle = (await post_bundle()).json()["id"]

    refused = await asgi_call(
        "POST", f"/api/v1/bundles/{bundle}/documents", body=b"x" * 5000,
        headers={"content-type": "multipart/form-data; boundary=b"}, client=PEER,
    )

    assert refused.status == 429 and refused.receive_calls == 0


@pytest.mark.asyncio
async def test_forwarded_for_is_ignored_by_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 2)
    await post_bundle(headers={"x-forwarded-for": "1.1.1.1"})
    await post_bundle(headers={"x-forwarded-for": "2.2.2.2"})

    assert (await post_bundle(headers={"x-forwarded-for": "3.3.3.3"})).status == 429


@pytest.mark.asyncio
async def test_forwarded_for_keys_the_bucket_when_trusted(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 1)

    first = await post_bundle(headers={"x-forwarded-for": "1.1.1.1, 10.9.9.9"})
    again = await post_bundle(headers={"x-forwarded-for": "1.1.1.1, 10.8.8.8"})  # same first address
    other = await post_bundle(headers={"x-forwarded-for": "2.2.2.2"})

    assert (first.status, again.status, other.status) == (201, 429, 201)


@pytest.mark.asyncio
@pytest.mark.parametrize("forwarded", ["not-an-ip", "", "999.1.1.1", "1.1.1.1:8080", "<script>", ",,,", "unknown"])
async def test_a_malformed_forwarded_for_falls_back_to_the_peer(monkeypatch, forwarded) -> None:
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 1)
    await post_bundle(peer=("10.0.0.1", 1), headers={"x-forwarded-for": forwarded})

    same_peer = await post_bundle(peer=("10.0.0.1", 2), headers={"x-forwarded-for": forwarded})
    other_peer = await post_bundle(peer=("10.0.0.2", 2), headers={"x-forwarded-for": forwarded})

    assert (same_peer.status, other_peer.status) == (429, 201)


@pytest.mark.asyncio
async def test_a_request_without_a_peer_address_is_still_limited_as_one_client(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 1)
    await post_bundle(peer=None)

    assert (await post_bundle(peer=None)).status == 429
