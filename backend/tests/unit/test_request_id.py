"""B1: one request id per request, in the response header, the error envelope and the log context.

A client-supplied X-Request-ID is kept only if it is 1-64 characters of [A-Za-z0-9._-]; anything else is replaced by
a fresh uuid4, so a hostile header can neither be reflected nor smuggle anything into logs or headers.
"""

from __future__ import annotations

import re

import pytest
import structlog
from httpx import ASGITransport, AsyncClient

from app.gateway.middleware import RequestContextMiddleware
from app.repo import firestore
from tests.helpers import api_client, asgi_call

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


@pytest.mark.asyncio
async def test_without_a_header_a_uuid4_is_generated_and_the_envelope_carries_it() -> None:
    async with api_client() as client:
        response = await client.get("/api/v1/bundles/bnd-nope")

    request_id = response.headers["x-request-id"]
    assert UUID4.match(request_id), request_id
    assert response.status_code == 404
    assert response.json()["request_id"] == request_id != "unknown"


@pytest.mark.asyncio
async def test_a_valid_header_is_kept_in_the_header_and_the_envelope() -> None:
    async with api_client() as client:
        response = await client.get("/api/v1/bundles/bnd-nope", headers={"X-Request-ID": "Trace.7_ab-CD"})

    assert response.headers["x-request-id"] == "Trace.7_ab-CD"
    assert response.json()["request_id"] == "Trace.7_ab-CD"


@pytest.mark.asyncio
async def test_a_64_character_id_is_accepted() -> None:
    async with api_client() as client:
        response = await client.get("/api/v1/bundles/bnd-nope", headers={"X-Request-ID": "a" * 64})

    assert response.headers["x-request-id"] == "a" * 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile",
    [
        "x" * 5000,
        "a" * 65,
        "has spaces",
        "semi;colon",
        "slash/slash",
        "unicode-é",
        "abc\r\nSet-Cookie: pwn=1",
        "abc\nX-Injected: 1",
        "trailing-newline\n",
        "<script>",
    ],
    ids=["5kB", "65-chars", "spaces", "semicolon", "slash", "unicode", "crlf-cookie", "lf-header", "trailing-lf", "html"],
)
async def test_a_hostile_header_is_replaced_by_a_uuid4_and_never_reflected(hostile) -> None:
    result = await asgi_call("GET", "/api/v1/bundles/bnd-nope", headers={"X-Request-ID": hostile})

    request_id = result.headers["x-request-id"]
    assert UUID4.match(request_id), request_id
    assert result.json()["request_id"] == request_id
    assert hostile not in result.body.decode() and "set-cookie" not in result.headers and "x-injected" not in result.headers


@pytest.mark.asyncio
async def test_an_empty_header_is_replaced() -> None:
    result = await asgi_call("GET", "/api/v1/bundles/bnd-nope", headers={"X-Request-ID": ""})

    assert UUID4.match(result.headers["x-request-id"])


@pytest.mark.asyncio
async def test_every_response_has_exactly_one_request_id_header() -> None:
    result = await asgi_call("GET", "/api/v1/bundles/bnd-nope", headers={"X-Request-ID": "mine-1"})
    start = next(m for m in result.messages if m["type"] == "http.response.start")

    assert [v for k, v in start["headers"] if k == b"x-request-id"] == [b"mine-1"]


@pytest.mark.asyncio
async def test_each_request_gets_its_own_generated_id() -> None:
    async with api_client() as client:
        first = await client.get("/healthz")
        second = await client.get("/healthz")

    assert first.headers["x-request-id"] != second.headers["x-request-id"]


@pytest.mark.asyncio
async def test_the_unhandled_error_envelope_uses_the_same_id(monkeypatch) -> None:
    async def broken(_bundle_id: str):
        raise RuntimeError("TOP-SECRET")

    monkeypatch.setattr(firestore, "get_bundle", broken)
    async with api_client() as client:
        none_sent = await client.get("/api/v1/bundles/bnd-x")
        sent = await client.get("/api/v1/bundles/bnd-x", headers={"X-Request-ID": "mine-2"})

    assert none_sent.status_code == sent.status_code == 500
    assert none_sent.json()["request_id"] == none_sent.headers["x-request-id"] != "unknown"
    assert sent.json()["request_id"] == sent.headers["x-request-id"] == "mine-2"
    assert "TOP-SECRET" not in none_sent.text


@pytest.mark.asyncio
async def test_a_conflict_envelope_uses_the_same_id() -> None:
    from app.services import orchestrator

    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={})).json()["id"]
        response = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")  # empty bundle: 422 domain error

    assert response.status_code == 422
    assert response.json()["request_id"] == response.headers["x-request-id"] != "unknown"
    assert orchestrator is not None


async def _echo_context(scope, receive, send) -> None:
    """A minimal ASGI app that reports the structlog context it runs in."""
    import json

    body = json.dumps(structlog.contextvars.get_contextvars()).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


@pytest.mark.asyncio
async def test_the_same_id_is_bound_into_the_log_context() -> None:
    wrapped = RequestContextMiddleware(_echo_context)
    async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
        explicit = await client.get("/x", headers={"X-Request-ID": "trace-9"})
        generated = await client.get("/y")

    assert explicit.headers["x-request-id"] == "trace-9"
    assert explicit.json() == {"request_id": "trace-9", "method": "GET", "path": "/x"}
    assert generated.json()["request_id"] == generated.headers["x-request-id"]
    assert UUID4.match(generated.json()["request_id"]) and generated.json()["path"] == "/y"


@pytest.mark.asyncio
async def test_the_log_context_does_not_outlive_the_request() -> None:
    wrapped = RequestContextMiddleware(_echo_context)
    async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
        await client.get("/x", headers={"X-Request-ID": "trace-9"})

    assert structlog.contextvars.get_contextvars() == {}


@pytest.mark.asyncio
async def test_the_request_completed_log_line_carries_status_and_timing() -> None:
    from structlog.testing import capture_logs

    wrapped = RequestContextMiddleware(_echo_context)
    with capture_logs() as logs:
        async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
            await client.get("/x")

    [line] = [entry for entry in logs if entry["event"] == "request_completed"]
    assert line["status"] == 200 and line["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_non_http_scopes_pass_straight_through() -> None:
    seen: list[str] = []

    async def inner(scope, receive, send) -> None:
        seen.append(scope["type"])

    await RequestContextMiddleware(inner)({"type": "lifespan"}, None, None)

    assert seen == ["lifespan"]
