"""B2: every error answers the same envelope {code, message, detail, request_id}.

Validation errors, unknown routes and wrong methods used to answer FastAPI's {"detail": ...}. The envelope never echoes
the offending input and never contains exception text.
"""

from __future__ import annotations

import json

import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.gateway import middleware
from tests.helpers import api_client, asgi_call

ENVELOPE_KEYS = {"code", "message", "detail", "request_id"}


def assert_envelope(result, status: int, code: str) -> dict:
    body = result.json() if hasattr(result, "json") and callable(result.json) else result
    assert result.status_code == status if hasattr(result, "status_code") else result.status == status
    assert set(body) == ENVELOPE_KEYS, body
    assert body["code"] == code
    assert body["request_id"] != "unknown"
    return body


@pytest.mark.asyncio
async def test_malformed_json_is_a_422_envelope() -> None:
    async with api_client() as client:
        response = await client.post("/api/v1/bundles", content=b"{not json", headers={"content-type": "application/json"})

    body = assert_envelope(response, 422, "VALIDATION_ERROR")
    assert body["message"] == "The request is not valid."
    assert body["detail"]["errors"] and all(set(e) == {"loc", "msg", "type"} for e in body["detail"]["errors"])
    assert body["request_id"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_a_validation_error_lists_loc_msg_and_type_and_never_the_input() -> None:
    secret = "SECRET-INPUT-VALUE-12345"
    async with api_client() as client:
        response = await client.post("/api/v1/bundles", json={"reference": [secret], "destination_country": {"a": secret}})

    body = assert_envelope(response, 422, "VALIDATION_ERROR")
    locs = [e["loc"] for e in body["detail"]["errors"]]
    assert ["body", "reference"] in locs and ["body", "destination_country"] in locs
    assert all(isinstance(e["loc"], list) and isinstance(e["msg"], str) and isinstance(e["type"], str) for e in body["detail"]["errors"])
    assert secret not in response.text, "the offending value must not be echoed"
    assert "input" not in json.dumps(body["detail"]) and "ctx" not in json.dumps(body["detail"])


@pytest.mark.asyncio
async def test_a_query_validation_error_is_the_same_envelope() -> None:
    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={})).json()["id"]
        response = await client.get(f"/api/v1/bundles/{bundle_id}/extractions", params={"iteration": "abc"})

    body = assert_envelope(response, 422, "VALIDATION_ERROR")
    assert ["query", "iteration"] in [e["loc"] for e in body["detail"]["errors"]]
    assert "abc" not in response.text


@pytest.mark.asyncio
async def test_an_unknown_route_is_a_404_envelope() -> None:
    async with api_client() as client:
        response = await client.get("/api/v1/does-not-exist")

    body = assert_envelope(response, 404, "NOT_FOUND")
    assert body["message"] == "Resource not found." and body["detail"] is None


@pytest.mark.asyncio
async def test_a_wrong_method_is_a_405_envelope_and_keeps_the_allow_header() -> None:
    async with api_client() as client:
        response = await client.delete("/api/v1/bundles")

    body = assert_envelope(response, 405, "METHOD_NOT_ALLOWED")
    assert body["message"] == "Method not allowed." and body["detail"] is None
    assert "POST" in response.headers["allow"]


@pytest.mark.asyncio
async def test_any_other_http_exception_is_http_status_with_a_fixed_message() -> None:
    # FastAPI answers a multipart body it cannot parse with HTTPException(400, "There was an error parsing the body")
    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={})).json()["id"]
        response = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents", content=b"garbage", headers={"content-type": "multipart/form-data"}
        )

    body = assert_envelope(response, 400, "HTTP_400")
    assert body["message"] == "The request could not be processed."
    assert "parsing the body" not in response.text


@pytest.mark.asyncio
async def test_the_http_exception_handler_never_echoes_the_exception_detail() -> None:
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": [], "query_string": b"", "state": {"request_id": "r-1"}}
    response = await middleware.http_exception_handler(
        Request(scope), StarletteHTTPException(418, detail="TOP-SECRET teapot", headers={"X-Teapot": "yes"})
    )

    assert response.status_code == 418 and response.headers["x-teapot"] == "yes"
    body = json.loads(response.body)
    assert body == {"code": "HTTP_418", "message": "The request could not be processed.", "detail": None, "request_id": "r-1"}


@pytest.mark.asyncio
async def test_domain_errors_keep_their_envelope() -> None:
    async with api_client() as client:
        response = await client.get("/api/v1/bundles/bnd-nope")

    body = assert_envelope(response, 404, "NOT_FOUND")
    assert body["message"] == "Bundle 'bnd-nope' not found." and body["detail"] == {"bundle_id": "bnd-nope"}


@pytest.mark.asyncio
async def test_an_unhandled_exception_is_still_a_generic_500_without_exception_text(monkeypatch) -> None:
    from app.repo import firestore

    async def broken(_bundle_id: str):
        raise RuntimeError("TOP-SECRET /Users/someone")

    monkeypatch.setattr(firestore, "get_bundle", broken)
    async with api_client() as client:
        response = await client.get("/api/v1/bundles/bnd-x")

    body = assert_envelope(response, 500, "INTERNAL_ERROR")
    assert body["message"] == "An unexpected error occurred. Please retry." and body["detail"] is None
    assert "TOP-SECRET" not in response.text


@pytest.mark.asyncio
async def test_the_envelope_is_json_with_the_right_content_type() -> None:
    result = await asgi_call("GET", "/api/v1/does-not-exist")

    assert result.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_an_error_after_the_response_started_is_not_wrapped() -> None:
    """A stream that breaks mid-way cannot be turned into an envelope: the exception must propagate, not be swallowed."""

    async def broken_stream(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("late failure")

    wrapped = middleware.ErrorEnvelopeMiddleware(broken_stream)
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    with pytest.raises(RuntimeError, match="late failure"):
        await wrapped({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}, None, send)

    assert [m["type"] for m in sent] == ["http.response.start"], "no second response was started"


@pytest.mark.asyncio
async def test_a_domain_error_after_the_response_started_is_not_wrapped_either() -> None:
    from app.gateway.errors import NotFoundError

    async def broken_stream(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise NotFoundError("late")

    wrapped = middleware.ErrorEnvelopeMiddleware(broken_stream)

    async def send(message: dict) -> None:
        return None

    with pytest.raises(NotFoundError):
        await wrapped({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}, None, send)


@pytest.mark.asyncio
async def test_non_http_scopes_pass_straight_through_the_envelope_middleware() -> None:
    seen: list[str] = []

    async def inner(scope, receive, send) -> None:
        seen.append(scope["type"])

    await middleware.ErrorEnvelopeMiddleware(inner)({"type": "websocket"}, None, None)

    assert seen == ["websocket"]


@pytest.mark.asyncio
async def test_the_sse_response_is_streamed_through_the_whole_stack_not_buffered() -> None:
    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={})).json()["id"]

    result = await asgi_call("GET", f"/api/v1/bundles/{bundle_id}/stream", until=b"event: status")

    assert result.status == 200 and result.headers["content-type"].startswith("text/event-stream")
    assert b"event: status" in result.body
    assert result.streaming_open is True, "the first event arrived while the response was still open: nothing buffers it"
