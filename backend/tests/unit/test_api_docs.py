"""E1: /docs, /redoc and /openapi.json are served only when ENABLE_API_DOCS says so (default: demo on, live off)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, settings
from app.main import app as module_app
from app.main import create_app

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


def client_for(application) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


def configure(monkeypatch: pytest.MonkeyPatch, mode: str, enable: bool | None) -> None:
    monkeypatch.setattr(settings, "app_mode", mode)
    monkeypatch.setattr(settings, "enable_api_docs", enable)


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "enable", "served"), [
    ("demo", None, True),
    ("live", None, False),
    ("live", True, True),
    ("demo", False, False),
    ("demo", True, True),
    ("live", False, False),
], ids=["demo-default", "live-default", "live-forced-on", "demo-forced-off", "demo-on", "live-off"])
async def test_the_docs_follow_the_mode_and_the_explicit_setting(monkeypatch, mode, enable, served) -> None:
    configure(monkeypatch, mode, enable)
    application = create_app()

    async with client_for(application) as client:
        responses = {path: await client.get(path) for path in DOC_PATHS}

    for path, response in responses.items():
        if served:
            assert response.status_code == 200, (path, response.status_code)
        else:
            assert response.status_code == 404, (path, response.status_code)
            assert response.json()["code"] == "NOT_FOUND" and response.json()["message"] == "Resource not found."
            assert set(response.json()) == {"code", "message", "detail", "request_id"}


@pytest.mark.asyncio
async def test_the_served_openapi_document_is_the_api_schema(monkeypatch) -> None:
    configure(monkeypatch, "demo", None)

    async with client_for(create_app()) as client:
        schema = (await client.get("/openapi.json")).json()
        docs = await client.get("/docs")

    assert schema["info"]["title"] == "CargoClear-JAPAC API" and "/api/v1/bundles" in schema["paths"]
    assert docs.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["demo", "live"])
async def test_health_and_meta_are_unchanged_whether_or_not_the_docs_are_served(monkeypatch, mode) -> None:
    configure(monkeypatch, mode, None)

    async with client_for(create_app()) as client:
        health, ready, meta = await client.get("/healthz"), await client.get("/readyz"), await client.get("/api/v1/meta")

    assert health.json() == ready.json() == {"status": "ok"}
    assert meta.json() == {
        "app_mode": mode, "data_source_policy": "live" if mode == "live" else "fixture_with_offline_fallbacks",
        "pipeline_engine": settings.pipeline_engine,  # additive since the engine seam: "native" unless PIPELINE_ENGINE says adk
    }


@pytest.mark.asyncio
async def test_the_module_level_app_serves_the_docs_in_demo_mode() -> None:
    async with client_for(module_app) as client:
        assert (await client.get("/openapi.json")).status_code == 200


def test_the_setting_resolves_like_the_brief_says() -> None:
    assert Settings(_env_file=None).enable_api_docs is None
    assert Settings(_env_file=None).api_docs_enabled is True
    assert Settings(_env_file=None, APP_MODE="live").api_docs_enabled is False
    assert Settings(_env_file=None, APP_MODE="live", ENABLE_API_DOCS="true").api_docs_enabled is True
    assert Settings(_env_file=None, APP_MODE="demo", ENABLE_API_DOCS="false").api_docs_enabled is False


@pytest.mark.asyncio
async def test_two_apps_can_be_built_in_one_process(monkeypatch) -> None:
    configure(monkeypatch, "demo", True)
    on = create_app()
    configure(monkeypatch, "live", None)
    off = create_app()

    async with client_for(on) as a, client_for(off) as b:
        assert (await a.get("/docs")).status_code == 200
        assert (await b.get("/docs")).status_code == 404
