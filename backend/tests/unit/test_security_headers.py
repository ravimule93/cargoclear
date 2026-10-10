"""B3: security headers on every response, added by a pure ASGI middleware (streaming responses are untouched)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.gateway.middleware import SecurityHeadersMiddleware
from tests.helpers import api_client, asgi_call

BASE = {"x-content-type-options": "nosniff", "referrer-policy": "no-referrer"}


def app_with(content_type: str, extra: list[tuple[bytes, bytes]] | None = None, body: bytes = b"{}"):
    async def inner(scope, receive, send) -> None:
        headers = [(b"content-type", content_type.encode()), *(extra or [])]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    return SecurityHeadersMiddleware(inner)


async def fetch(wrapped):
    async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
        return await client.get("/x")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/healthz", "/api/v1/meta", "/api/v1/bundles/bnd-nope", "/api/v1/does-not-exist"])
async def test_json_responses_carry_all_three_headers(path) -> None:
    async with api_client() as client:
        response = await client.get(path)

    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_a_validation_error_and_a_server_error_carry_them_too(monkeypatch) -> None:
    from app.repo import firestore

    async def broken(_bundle_id: str):
        raise RuntimeError("boom")

    async with api_client() as client:
        invalid = await client.post("/api/v1/bundles", content=b"{", headers={"content-type": "application/json"})
        monkeypatch.setattr(firestore, "get_bundle", broken)
        failed = await client.get("/api/v1/bundles/bnd-x")

    for response in (invalid, failed):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_a_cors_preflight_carries_the_base_headers() -> None:
    async with api_client() as client:
        response = await client.options(
            "/api/v1/bundles", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}
        )

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_an_existing_cache_control_is_kept() -> None:
    response = await fetch(app_with("application/json", [(b"cache-control", b"private, max-age=60")]))

    assert response.headers["cache-control"] == "private, max-age=60"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["text/event-stream", "application/pdf", "text/html; charset=utf-8", "image/png"])
async def test_cache_control_is_not_added_to_other_content_types(content_type) -> None:
    response = await fetch(app_with(content_type))

    assert "cache-control" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_a_json_response_with_a_charset_still_gets_no_store() -> None:
    response = await fetch(app_with("application/json; charset=utf-8"))

    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_the_headers_are_set_once_even_if_the_response_already_had_them() -> None:
    response = await fetch(app_with("application/json", [(b"x-content-type-options", b"nosniff")]))

    assert response.headers.get_list("x-content-type-options") == ["nosniff"]


@pytest.mark.asyncio
async def test_the_sse_response_keeps_its_own_headers_and_gains_only_the_base_two() -> None:
    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={})).json()["id"]

    result = await asgi_call("GET", f"/api/v1/bundles/{bundle_id}/stream", until=b"event: status")

    assert result.status == 200
    assert result.headers["content-type"].startswith("text/event-stream")
    assert result.headers["x-content-type-options"] == "nosniff" and result.headers["referrer-policy"] == "no-referrer"
    assert result.headers.get("cache-control") != "no-store" or "no-store" in result.headers["cache-control"]
    assert result.headers.get("x-accel-buffering") == "no", "sse-starlette's own header is untouched"
    assert result.streaming_open is True


@pytest.mark.asyncio
async def test_non_http_scopes_pass_straight_through() -> None:
    seen: list[str] = []

    async def inner(scope, receive, send) -> None:
        seen.append(scope["type"])

    await SecurityHeadersMiddleware(inner)({"type": "lifespan"}, None, None)

    assert seen == ["lifespan"]


@pytest.mark.asyncio
async def test_messages_other_than_the_response_start_are_passed_on_untouched() -> None:
    sent: list[dict] = []

    async def inner(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"chunk-1", "more_body": True})
        await send({"type": "http.response.body", "body": b"chunk-2"})

    async def capture(message: dict) -> None:
        sent.append(message)

    await SecurityHeadersMiddleware(inner)({"type": "http"}, None, capture)

    assert [m.get("body") for m in sent[1:]] == [b"chunk-1", b"chunk-2"]
