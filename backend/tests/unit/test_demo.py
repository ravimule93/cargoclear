"""Tests for the Case C demo endpoints (POST /demo/case-c, GET /demo/case-c/mtc)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import demo
from app.core.config import settings
from app.main import app
from tests.helpers import CASE_C_DIR

EXPECTED_PRELOADED = {"commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf"}
CASE_C_FILENAMES = (*EXPECTED_PRELOADED, "mtc_pipe_test_cert.pdf")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_fixture_dir_uses_repository_fixtures_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CASE_C_FIXTURE_DIR", raising=False)

    assert demo._fixture_dir() == CASE_C_DIR


def test_fixture_dir_falls_back_to_packaged_fixtures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CASE_C_FIXTURE_DIR", raising=False)
    monkeypatch.setattr(demo, "_REPOSITORY_FIXTURE_DIR", tmp_path / "missing-repository-fixtures")

    assert demo._fixture_dir() == demo._PACKAGED_FIXTURE_DIR
    for name in CASE_C_FILENAMES:
        assert (demo._PACKAGED_FIXTURE_DIR / name).read_bytes() == (CASE_C_DIR / name).read_bytes()


@pytest.mark.asyncio
async def test_case_c_creates_bundle_with_three_distinct_documents() -> None:
    async with _client() as client:
        resp = await client.post("/api/v1/demo/case-c")
        assert resp.status_code == 201
        body = resp.json()

        assert body["id"].startswith("bnd-")
        assert body["reference"] == "CASE-C-7304-DEMO"
        assert body["destination_country"] == "SG"
        assert body["current_iteration"] == 0
        docs = body["documents"]
        assert {d["filename"] for d in docs} == EXPECTED_PRELOADED
        assert "mtc_pipe_test_cert.pdf" not in {d["filename"] for d in docs}
        assert len({d["document_id"] for d in docs}) == 3

        # The registered documents are retrievable as real PDFs through the bundle-scoped route.
        file_resp = await client.get(f"/api/v1/bundles/{body['id']}/documents/{docs[0]['document_id']}/file")
        assert file_resp.status_code == 200
        assert file_resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_case_c_records_upload_audit_events() -> None:
    async with _client() as client:
        bundle_id = (await client.post("/api/v1/demo/case-c")).json()["id"]
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        types = [e["event_type"] for e in audit["events"]]
        assert types == ["BUNDLE_CREATED", "DOCUMENT_UPLOADED", "DOCUMENT_UPLOADED", "DOCUMENT_UPLOADED"]
        assert audit["verified"] is True


@pytest.mark.asyncio
async def test_second_call_creates_a_different_bundle() -> None:
    async with _client() as client:
        first = (await client.post("/api/v1/demo/case-c")).json()
        second = (await client.post("/api/v1/demo/case-c")).json()
        assert first["id"] != second["id"]
        assert len(first["documents"]) == len(second["documents"]) == 3


@pytest.mark.asyncio
async def test_404_when_app_mode_is_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")  # monkeypatch restores the original on teardown
    async with _client() as client:
        post = await client.post("/api/v1/demo/case-c")
        get = await client.get("/api/v1/demo/case-c/mtc")
    assert post.status_code == 404
    assert post.json()["code"] == "NOT_FOUND"
    assert get.status_code == 404
    assert get.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_mtc_endpoint_returns_pdf_bytes() -> None:
    async with _client() as client:
        resp = await client.get("/api/v1/demo/case-c/mtc")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_missing_fixture_dir_gives_a_fixed_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "nope"
    monkeypatch.setenv("CASE_C_FIXTURE_DIR", str(empty))
    async with _client() as client:
        resp = await client.post("/api/v1/demo/case-c")
        mtc = await client.get("/api/v1/demo/case-c/mtc")
    for r in (resp, mtc):
        assert r.status_code == 500
        assert r.json()["message"] == "The Case C sample documents are not installed on this server."


@pytest.mark.asyncio
async def test_fixture_dir_override_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf", "mtc_pipe_test_cert.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4 custom " + name.encode())
    monkeypatch.setenv("CASE_C_FIXTURE_DIR", str(tmp_path))
    async with _client() as client:
        resp = await client.get("/api/v1/demo/case-c/mtc")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 custom mtc_pipe_test_cert.pdf"


@pytest.mark.asyncio
async def test_upload_route_still_registers_documents() -> None:
    """The shared register_document() keeps the original upload behaviour."""
    async with _client() as client:
        bundle_id = (await client.post("/api/v1/bundles", json={"reference": "UP-1"})).json()["id"]
        resp = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files={"file": ("packing_list.pdf", b"%PDF-1.4 x", "application/pdf")},
        )
        assert resp.status_code == 201
        assert resp.json()["doc_type"] == "UNKNOWN"
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()
        assert [d["filename"] for d in bundle["documents"]] == ["packing_list.pdf"]
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        assert [e["event_type"] for e in audit["events"]] == ["BUNDLE_CREATED", "DOCUMENT_UPLOADED"]
        assert audit["verified"] is True


@pytest.mark.asyncio
async def test_a_missing_fixture_leaks_no_filesystem_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from structlog.testing import capture_logs

    missing_dir = tmp_path / "private-dir-name" / "nope"
    monkeypatch.setenv("CASE_C_FIXTURE_DIR", str(missing_dir))
    async with _client() as client:
        with capture_logs() as logs:
            post = await client.post("/api/v1/demo/case-c")
            mtc = await client.get("/api/v1/demo/case-c/mtc")

    for response in (post, mtc):
        assert response.status_code == 500
        body = response.json()
        assert body["message"] == "The Case C sample documents are not installed on this server."
        assert "private-dir-name" not in response.text and str(tmp_path) not in response.text and "/" not in body["message"]
        assert body["detail"] is None or "path" not in body["detail"]
    assert any(str(missing_dir) in str(entry.get("path", "")) for entry in logs), "the operator's log keeps the path"


@pytest.mark.asyncio
async def test_the_mtc_download_has_the_safe_download_headers() -> None:
    async with _client() as client:
        resp = await client.get("/api/v1/demo/case-c/mtc")

    assert resp.headers["content-disposition"] == "inline; filename=\"mtc_pipe_test_cert.pdf\"; filename*=UTF-8''mtc_pipe_test_cert.pdf"
    assert resp.headers["cache-control"] == "private, max-age=3600"
    assert resp.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# Case D: the India import (POST /demo/case-d)
# ---------------------------------------------------------------------------

CASE_D_DIR = CASE_C_DIR.parent / "case_d"
CASE_D_FILENAMES = {
    "case_d_commercial_invoice.pdf", "case_d_bill_of_lading.pdf", "case_d_packing_list.pdf", "case_d_mtc_test_cert.pdf",
}


@pytest.mark.asyncio
async def test_case_d_creates_an_india_bundle_with_all_four_distinct_documents() -> None:
    async with _client() as client:
        resp = await client.post("/api/v1/demo/case-d")

        assert resp.status_code == 201
        body = resp.json()
        assert body["reference"] == "CASE-D-7304-IN-DEMO" and body["destination_country"] == "IN"
        assert body["current_iteration"] == 0
        assert {d["filename"] for d in body["documents"]} == CASE_D_FILENAMES
        assert len({d["document_id"] for d in body["documents"]}) == 4
        file_resp = await client.get(f"/api/v1/bundles/{body['id']}/documents/{body['documents'][0]['document_id']}/file")
        assert file_resp.status_code == 200 and file_resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_case_d_records_one_upload_event_per_document() -> None:
    async with _client() as client:
        bundle_id = (await client.post("/api/v1/demo/case-d")).json()["id"]
        events = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()

    assert [e["event_type"] for e in events["events"]] == ["BUNDLE_CREATED"] + ["DOCUMENT_UPLOADED"] * 4
    assert events["verified"] is True


@pytest.mark.asyncio
async def test_case_d_is_demo_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")

    async with _client() as client:
        resp = await client.post("/api/v1/demo/case-d")

    assert resp.status_code == 404 and resp.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_a_missing_case_d_fixture_names_its_own_override_variable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CASE_D_FIXTURE_DIR", str(tmp_path))  # an empty directory

    async with _client() as client:
        resp = await client.post("/api/v1/demo/case-d")

    assert resp.status_code == 500 and "not installed" in resp.json()["message"]
    assert demo._fixture_dir("case_d") == tmp_path and demo._fixture_dir("case_c") != tmp_path


def test_the_case_d_directory_sits_next_to_case_c(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CASE_D_FIXTURE_DIR", raising=False)

    assert demo._fixture_dir("case_d") == CASE_D_DIR
    for name in CASE_D_FILENAMES:
        assert (demo._PACKAGED_FIXTURE_DIR.parent / "case_d" / name).read_bytes() == (CASE_D_DIR / name).read_bytes()
