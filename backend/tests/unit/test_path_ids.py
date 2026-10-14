"""B4: bundle_id / document_id path parameters must look like ids (^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$).

Anything else answers the SAME 404 NOT_FOUND an unknown id gets, on every route including the SSE one, so a hostile id
never reaches the stores (local storage builds file paths from these ids).
"""

from __future__ import annotations

import pytest

from app.gateway.ids import ID_PATTERN
from tests.helpers import api_client, asgi_call, create_bundle_with_documents

HOSTILE = {
    "dotdot": "..",
    "encoded-dotdot": "%2e%2e",  # httpx / curl would send this; the server decodes it to ".."
    "dot": ".",
    "3000-chars": "a" * 3000,
    "65-chars": "a" * 65,
    "nul": "bnd-\x00x",
    "unicode": "bnd-发票",
    "leading-dash": "-bnd",
    "leading-underscore": "_bnd",
    "space": "bnd x",
    "slash-free-traversal": "..%5c..",
    "colon": "bnd:1",
}

ROUTES = [
    ("GET", "/api/v1/bundles/{b}"),
    ("GET", "/api/v1/bundles/{b}/stream"),
    ("GET", "/api/v1/bundles/{b}/audit"),
    ("GET", "/api/v1/bundles/{b}/extractions"),
    ("GET", "/api/v1/bundles/{b}/assessment"),
    ("GET", "/api/v1/bundles/{b}/iterations"),
    ("POST", "/api/v1/bundles/{b}/analyze"),
    ("POST", "/api/v1/bundles/{b}/reassess"),
    ("POST", "/api/v1/bundles/{b}/recompute"),
    ("GET", "/api/v1/bundles/{b}/corrections"),
    ("GET", "/api/v1/bundles/{b}/prefill"),
    ("GET", "/api/v1/bundles/{b}/prefill.pdf"),
    ("POST", "/api/v1/bundles/{b}/corrections"),
    ("POST", "/api/v1/bundles/{b}/corrections/cor-1/revert"),
    ("GET", "/api/v1/bundles/{b}/documents/doc-0123456789abcdef/file"),
    ("GET", "/api/v1/bundles/{b}/documents/doc-0123456789abcdef/transform-metadata"),
]


JSON_BODY = b'{"document_id": "doc-0123456789abcdef", "path": "consignee", "value": "ACME"}'


def decoded(raw: str) -> str:
    from urllib.parse import unquote

    return unquote(raw)


@pytest.mark.parametrize("good", ["bnd-0123456789ab", "a", "A1", "doc-0123456789abcdef", "a_b-c", "9lives", "x" * 64])
def test_ids_that_look_like_ids_match(good) -> None:
    assert ID_PATTERN.fullmatch(good)


@pytest.mark.parametrize("bad", ["", "..", ".", "-a", "_a", "a b", "a/b", "a.b", "x" * 65, "é", "a\n", "a\x00"])
def test_ids_that_do_not_look_like_ids_do_not_match(bad) -> None:
    assert not ID_PATTERN.fullmatch(bad)


@pytest.mark.asyncio
@pytest.mark.parametrize("method_path", ROUTES, ids=[f"{m} {p.split('/', 4)[-1]}" for m, p in ROUTES])
@pytest.mark.parametrize("name", list(HOSTILE))
async def test_a_hostile_bundle_id_is_the_same_404_on_every_route(name, method_path) -> None:
    method, template = method_path
    hostile = decoded(HOSTILE[name])

    # a POST carries a valid JSON body, so that a route that takes one is judged by its id, not by a missing body
    send = {"body": JSON_BODY, "headers": {"content-type": "application/json"}} if method == "POST" else {}
    result = await asgi_call(method, template.replace("{b}", hostile), **send)

    assert result.status == 404, (result.status, result.body[:200])
    body = result.json()
    assert body["code"] == "NOT_FOUND"
    assert set(body) == {"code", "message", "detail", "request_id"}
    assert body["message"].startswith("Bundle '") and body["message"].endswith("' not found.")
    assert len(result.body) < 1000, "the id is not echoed back at full length"

    if not template.endswith("/iterations"):  # (an unknown bundle's /iterations has always been 200 [])
        reference = await asgi_call(method, template.replace("{b}", "bnd-0123456789ab"), **send)
        assert reference.status == 404 and reference.json()["code"] == "NOT_FOUND"
        assert set(reference.json()) == set(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["file", "transform-metadata"])
@pytest.mark.parametrize("name", list(HOSTILE))
async def test_a_hostile_document_id_is_the_same_404(name, endpoint) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, {"a.pdf": b"%PDF-1.4 a"})
    hostile = decoded(HOSTILE[name])

    result = await asgi_call("GET", f"/api/v1/bundles/{bundle_id}/documents/{hostile}/{endpoint}")
    reference = await asgi_call(
        "GET", f"/api/v1/bundles/{bundle_id}/documents/doc-0123456789abcdef/{endpoint}"
    )

    assert result.status == reference.status == 404
    assert result.json()["code"] == reference.json()["code"] == "NOT_FOUND"
    assert result.json()["message"].startswith("Document '") and "not found in bundle" in result.json()["message"]
    assert len(result.body) < 1000


@pytest.mark.asyncio
async def test_a_hostile_bundle_id_never_reaches_the_stores(monkeypatch) -> None:
    from app.repo import firestore

    reached: list[str] = []

    async def spy(bundle_id: str):
        reached.append(bundle_id)

    monkeypatch.setattr(firestore, "get_bundle", spy)
    for hostile in ("..", "a" * 3000, "-x"):
        await asgi_call("GET", f"/api/v1/bundles/{hostile}")
        await asgi_call("GET", f"/api/v1/bundles/{hostile}/stream")

    assert reached == []


@pytest.mark.asyncio
async def test_valid_ids_are_unaffected() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, {"a.pdf": b"%PDF-1.4 a"})
        bundle = await client.get(f"/api/v1/bundles/{bundle_id}")
        document_id = bundle.json()["documents"][0]["document_id"]
        file = await client.get(f"/api/v1/bundles/{bundle_id}/documents/{document_id}/file")

    assert bundle.status_code == 200 and file.status_code == 200


@pytest.mark.asyncio
async def test_the_echoed_id_is_bounded_and_printable() -> None:
    result = await asgi_call("GET", "/api/v1/bundles/" + "a" * 3000 + "\x00\x07")

    message = result.json()["message"]
    assert result.status == 404 and len(message) < 100
    assert "\x00" not in message and "\x07" not in message


@pytest.mark.asyncio
async def test_a_valid_but_unknown_id_keeps_its_exact_message() -> None:
    result = await asgi_call("GET", "/api/v1/bundles/bnd-nope")

    assert result.json()["message"] == "Bundle 'bnd-nope' not found."
    assert result.json()["detail"] == {"bundle_id": "bnd-nope"}


@pytest.mark.asyncio
@pytest.mark.parametrize("hostile", ["..", "cor-", "cor-x", "cor-12345678901", "COR-1", "1", "a" * 3000, "cor-1;drop", "cor-1/../x"])
async def test_a_correction_id_that_is_not_one_is_a_bounded_404(hostile) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, {"a.pdf": b"%PDF-1.4 a"})
    result = await asgi_call("POST", f"/api/v1/bundles/{bundle_id}/corrections/{hostile.replace('/', '%2F')}/revert")
    assert result.status == 404 and result.json()["code"] == "NOT_FOUND"
    assert len(result.body) < 1000
