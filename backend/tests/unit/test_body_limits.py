"""B4: a body-size guard in front of the app (pure ASGI).

POST/PUT bodies are limited to MAX_JSON_BODY_KB, except POST .../documents (MAX_UPLOAD_MB + 1 MB for the multipart
envelope). With a Content-Length the request is refused with 413 PAYLOAD_TOO_LARGE before one byte of the body is read;
without one the bytes are counted while they stream and the request is refused as soon as the limit is crossed.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from tests.helpers import api_client, asgi_call, create_bundle_with_documents

KB = 1024
MB = 1024 * 1024


@pytest.fixture
def small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_json_body_kb", 1)  # 1 KB for JSON
    monkeypatch.setattr(settings, "max_upload_mb", 1)  # 1 MB + 1 MB overhead = 2 MB for uploads


def assert_payload_too_large(result, message: str) -> None:
    assert result.status == 413, (result.status, result.body[:200])
    body = result.json()
    assert set(body) == {"code", "message", "detail", "request_id"}
    assert body["code"] == "PAYLOAD_TOO_LARGE" and body["message"] == message
    assert body["request_id"] == result.headers["x-request-id"] != "unknown"
    assert result.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_a_json_body_over_the_limit_is_refused_by_its_content_length_before_it_is_read(small_limits) -> None:
    result = await asgi_call("POST", "/api/v1/bundles", body=b"x" * (2 * KB), headers={"content-type": "application/json"})

    assert_payload_too_large(result, "The request body is larger than 1 KB.")
    assert result.receive_calls == 0, "not one byte of the body was read"


@pytest.mark.asyncio
async def test_a_json_body_exactly_at_the_limit_is_accepted(small_limits) -> None:
    padding = " " * (KB - len(b'{"reference":"a"}'))
    body = b'{"reference":"a"}' + padding.encode()
    assert len(body) == KB

    result = await asgi_call("POST", "/api/v1/bundles", body=body, headers={"content-type": "application/json"})

    assert result.status == 201, result.body[:200]


@pytest.mark.asyncio
async def test_one_byte_over_the_limit_is_refused(small_limits) -> None:
    body = b'{"reference":"a"}' + b" " * (KB - len(b'{"reference":"a"}') + 1)

    result = await asgi_call("POST", "/api/v1/bundles", body=body, headers={"content-type": "application/json"})

    assert result.status == 413


@pytest.mark.asyncio
async def test_without_a_content_length_the_bytes_are_counted_and_the_stream_is_cut_as_soon_as_the_limit_is_crossed(small_limits) -> None:
    chunks = [b"x" * 600] * 50  # 600 B each: the second chunk crosses 1 KB

    result = await asgi_call(
        "POST", "/api/v1/bundles", chunks=chunks, content_length=False, headers={"content-type": "application/json"}
    )

    assert_payload_too_large(result, "The request body is larger than 1 KB.")
    assert result.receive_calls <= 3, f"the guard kept reading: {result.receive_calls} chunks"


@pytest.mark.asyncio
async def test_a_streamed_body_within_the_limit_passes(small_limits) -> None:
    chunks = [b'{"reference":', b'"streamed"', b"}"]

    result = await asgi_call(
        "POST", "/api/v1/bundles", chunks=chunks, content_length=False, headers={"content-type": "application/json"}
    )

    assert result.status == 201 and result.json()["reference"] == "streamed"


@pytest.mark.asyncio
async def test_a_malformed_content_length_falls_back_to_counting(small_limits) -> None:
    result = await asgi_call(
        "POST", "/api/v1/bundles", chunks=[b"x" * 700, b"x" * 700], content_length=False,
        headers={"content-type": "application/json", "content-length": "not-a-number"},
    )

    assert result.status == 413


@pytest.mark.asyncio
async def test_put_bodies_are_limited_too(small_limits) -> None:
    result = await asgi_call("PUT", "/api/v1/bundles/bnd-x", body=b"x" * (2 * KB))

    assert_payload_too_large(result, "The request body is larger than 1 KB.")


@pytest.mark.asyncio
async def test_get_requests_are_not_limited(small_limits) -> None:
    result = await asgi_call("GET", "/healthz", body=b"x" * (2 * KB))

    assert result.status == 200


@pytest.mark.asyncio
async def test_the_documents_route_has_the_upload_limit_plus_one_megabyte(small_limits) -> None:
    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={})).json()["id"]
    path = f"/api/v1/bundles/{bundle_id}/documents"

    over = await asgi_call("POST", path, body=b"x" * (2 * MB + 1), headers={"content-type": "multipart/form-data; boundary=b"})
    inside = await asgi_call("POST", path, body=b"x" * (1 * MB + 512 * KB), headers={"content-type": "multipart/form-data; boundary=b"})

    assert_payload_too_large(over, "The file is larger than 1 MB.")
    assert over.receive_calls == 0
    assert inside.status != 413, "1.5 MB is far above the JSON limit but inside the upload limit"


@pytest.mark.asyncio
async def test_the_documents_route_without_a_content_length_is_cut_at_the_upload_limit(small_limits) -> None:
    async with api_client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={})).json()["id"]
    opening = (
        b'--b\r\nContent-Disposition: form-data; name="file"; filename="big.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n%PDF-1.4 "
    )
    chunks = [opening + b"x" * (256 * KB)] + [b"x" * (256 * KB)] * 39  # a real multipart start, then 10 MB offered

    result = await asgi_call(
        "POST", f"/api/v1/bundles/{bundle_id}/documents", chunks=chunks, content_length=False,
        headers={"content-type": "multipart/form-data; boundary=b"},
    )

    assert_payload_too_large(result, "The file is larger than 1 MB.")
    assert result.receive_calls <= 10, f"read {result.receive_calls} chunks of 256 KB for a 2 MB limit"


@pytest.mark.asyncio
async def test_the_default_limits_are_256_kb_json_and_51_mb_upload() -> None:
    assert (settings.max_json_body_kb, settings.max_upload_mb) == (256, 50)

    json_over = await asgi_call("POST", "/api/v1/bundles", body=b"x" * (256 * KB + 1), headers={"content-type": "application/json"})
    assert_payload_too_large(json_over, "The request body is larger than 256 KB.")

    upload_over = await asgi_call(
        "POST", "/api/v1/bundles/bnd-x/documents", body=b"", headers={"content-type": "multipart/form-data; boundary=b", "content-length": str(51 * MB + 1)},
        content_length=False,
    )
    assert_payload_too_large(upload_over, "The file is larger than 50 MB.")


@pytest.mark.asyncio
async def test_a_real_multipart_upload_through_the_guard_still_works() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, {"invoice.pdf": b"%PDF-1.4 hello"})
        bundle = await client.get(f"/api/v1/bundles/{bundle_id}")

    assert [d["filename"] for d in bundle.json()["documents"]] == ["invoice.pdf"]


@pytest.mark.asyncio
async def test_the_413_for_an_unknown_path_is_still_the_guard_not_a_404(small_limits) -> None:
    result = await asgi_call("POST", "/api/v1/nothing-here", body=b"x" * (2 * KB))

    assert result.status == 413


@pytest.mark.asyncio
async def test_non_http_scopes_pass_straight_through() -> None:
    from app.gateway.limits import BodySizeLimitMiddleware

    seen: list[str] = []

    async def inner(scope, receive, send) -> None:
        seen.append(scope["type"])

    await BodySizeLimitMiddleware(inner)({"type": "lifespan"}, None, None)

    assert seen == ["lifespan"]


@pytest.mark.asyncio
async def test_an_application_that_lets_the_refusal_propagate_is_not_disturbed(small_limits) -> None:
    """A bare ASGI app that does not catch anything (FastAPI turns the failed read into a 400 of its own)."""
    from app.gateway.limits import BodySizeLimitMiddleware

    sent: list[dict] = []

    async def reads_everything(scope, receive, send) -> None:
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def capture(message: dict) -> None:
        sent.append(message)

    chunks = [{"type": "http.request", "body": b"x" * 700, "more_body": True}] * 3
    queue = list(chunks)

    async def receive() -> dict:
        return queue.pop(0)

    scope = {"type": "http", "method": "POST", "path": "/api/v1/bundles", "headers": [], "state": {"request_id": "r-1"}}
    await BodySizeLimitMiddleware(reads_everything)(scope, receive, capture)

    assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [413], "only the 413 was sent"
