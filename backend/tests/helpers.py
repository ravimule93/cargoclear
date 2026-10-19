"""Shared test helpers (importable as ``tests.helpers``)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.repo import firestore

REPO_ROOT = Path(__file__).resolve().parents[2]
CASE_C_DIR = REPO_ROOT / "samples" / "case_c" if (REPO_ROOT / "samples" / "case_c").is_dir() else (REPO_ROOT / "fixtures" / "case_c")

TERMINAL_STATES = ("COMPLETE", "ERROR")


def api_client() -> AsyncClient:
    """In-process client against the real FastAPI app."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def case_c_pdf(name: str) -> bytes:
    """Bytes of one committed Case C sample PDF."""
    return (CASE_C_DIR / name).read_bytes()


async def wait_for_run(
    bundle_id: str,
    run_id: str,
    *,
    timeout: float = 5.0,
    interval: float = 0.005,
) -> dict[str, Any]:
    """Poll the run state until it is COMPLETE or ERROR; no fixed sleeps.

    Returns the terminal run state (the caller asserts which one it expected). Fails with a
    readable message if the run does not finish within ``timeout`` seconds.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    state: dict[str, Any] = {}
    while loop.time() < deadline:
        state = await firestore.get_run_state(bundle_id, run_id)
        if state.get("run_id") == run_id and state.get("state") in TERMINAL_STATES:
            return state
        await asyncio.sleep(interval)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s; last state: {state}")


async def create_bundle_with_documents(
    client: AsyncClient,
    files: dict[str, bytes],
    *,
    reference: str = "TEST-BUNDLE",
) -> str:
    """Create a bundle and upload ``files`` (filename -> bytes) through the normal upload endpoint."""
    resp = await client.post("/api/v1/bundles", json={"reference": reference, "destination_country": "SG"})
    assert resp.status_code == 201, resp.text
    bundle_id = resp.json()["id"]
    for filename, data in files.items():
        up = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files={"file": (filename, data, "application/pdf")},
        )
        assert up.status_code == 201, up.text
    return bundle_id


async def audit_event_types(client: AsyncClient, bundle_id: str) -> list[str]:
    resp = await client.get(f"/api/v1/bundles/{bundle_id}/audit")
    assert resp.status_code == 200, resp.text
    return [e["event_type"] for e in resp.json()["events"]]


def load_script(filename: str):
    """Import ``scripts/<filename>`` as a module (the scripts directory is not a package)."""
    import importlib.util
    import sys

    path = REPO_ROOT / "scripts" / filename
    name = path.stem
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class AsgiResult:
    """What ``asgi_call`` saw: the response, and how much of the request body the app actually asked for."""

    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self.body = b""
        self.messages: list[dict[str, Any]] = []
        self.receive_calls = 0

    def json(self) -> Any:
        import json

        return json.loads(self.body)


def asgi_scope(
    method: str,
    path: str,
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    client: tuple[str, int] | None = ("127.0.0.1", 50000),
    query: bytes = b"",
) -> dict[str, Any]:
    """A bare HTTP scope for the real app. ``path`` is the already percent-decoded path, exactly what uvicorn passes."""
    from urllib.parse import quote

    return {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": quote(path, safe="/%").encode(), "query_string": query, "root_path": "",
        "headers": headers or [], "client": client, "server": ("testserver", 80),
    }


async def asgi_call(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    chunks: list[bytes] | None = None,
    content_length: bool = True,
    client: tuple[str, int] | None = ("127.0.0.1", 50000),
    app_under_test: Any = None,
    until: bytes | None = None,
) -> AsgiResult:
    """Call the app below httpx: no URL normalisation, a body that arrives as ``chunks``, and a count of ``receive`` calls.

    With ``until`` the call returns as soon as that byte string has been sent in a response body (for SSE, which never
    ends by itself); the request is then disconnected so that the app can finish.
    """
    target = app_under_test or app
    pieces = chunks if chunks is not None else [body]
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if content_length and any(pieces) and not any(k == b"content-length" for k, _ in raw_headers):
        raw_headers.append((b"content-length", str(sum(len(p) for p in pieces)).encode()))
    scope = asgi_scope(method, path, headers=raw_headers, client=client)

    result = AsgiResult()
    remaining = list(pieces)
    disconnect = asyncio.Event()
    seen = asyncio.Event()

    async def receive() -> dict[str, Any]:
        result.receive_calls += 1
        if remaining:
            chunk = remaining.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(remaining)}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        result.messages.append(message)
        if message["type"] == "http.response.start":
            result.status = message["status"]
            result.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            result.body += message.get("body", b"")
            if until is not None and until in result.body:
                seen.set()

    task = asyncio.ensure_future(target(scope, receive, send))
    try:
        if until is None:
            await asyncio.wait_for(task, 10)
        else:
            waiter = asyncio.ensure_future(seen.wait())
            done, _ = await asyncio.wait({task, waiter}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            result.streaming_open = task not in done  # type: ignore[attr-defined]
    finally:
        disconnect.set()
        if not task.done():
            try:
                await asyncio.wait_for(task, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return result
