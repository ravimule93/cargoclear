"""The page images the model was shown are kept, and served through a scoped endpoint ("what did it see?")."""

from __future__ import annotations

import io
import shutil
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.config import settings
from app.gateway.errors import NotFoundError, UpstreamError
from app.repo import firestore
from app.services import orchestrator, storage
from tests.helpers import api_client, asgi_call, create_bundle_with_documents, wait_for_run
from tests.support import scans

needs_poppler = pytest.mark.skipif(
    shutil.which("pdftoppm") is None or shutil.which("pdftotext") is None, reason="poppler is not installed"
)


def page(n: int, payload: bytes = b"png-bytes", mime: str = "image/png") -> dict:
    return {"page": n, "source_page": n, "document_id": "doc-1", "payload": payload, "mime": mime}


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pages_are_stored_privately_and_come_back_byte_for_byte() -> None:
    uris = await storage.upload_processed_pages("bnd-1", "doc-1", [page(1, b"one"), page(2, b"two")])
    assert uris == {
        1: f"gs://{settings.raw_bucket}/bundles/bnd-1/pages/doc-1/page-001.png",
        2: f"gs://{settings.raw_bucket}/bundles/bnd-1/pages/doc-1/page-002.png",
    }
    assert await storage.download_processed_page("bnd-1", "doc-1", 1) == b"one"
    assert await storage.download_processed_page("bnd-1", "doc-1", 2) == b"two"
    with pytest.raises(NotFoundError, match="Processed page 3 of document 'doc-1' not found"):
        await storage.download_processed_page("bnd-1", "doc-1", 3)
    with pytest.raises(NotFoundError):
        await storage.download_processed_page("bnd-1", "doc-other", 1)


@pytest.mark.asyncio
async def test_only_png_pages_are_kept_a_passthrough_pdf_has_no_page_image() -> None:
    assert await storage.upload_processed_pages("bnd-1", "doc-1", []) == {}
    assert await storage.upload_processed_pages("bnd-1", "doc-1", [page(1, b"%PDF-", mime="application/pdf")]) == {}
    assert await storage.upload_processed_pages("bnd-1", "doc-1", [page(1, b"")]) == {}, "an empty payload is no page"
    with pytest.raises(NotFoundError):
        await storage.download_processed_page("bnd-1", "doc-1", 1)


@pytest.mark.asyncio
async def test_the_gcs_path_writes_one_blob_per_page_in_a_worker_thread_and_reads_it_back(monkeypatch) -> None:
    blobs: dict[str, bytes] = {}

    class Blob:
        def __init__(self, path: str) -> None:
            self.path = path

        def upload_from_string(self, data, content_type) -> None:
            assert content_type == "image/png"
            blobs[self.path] = data

        def exists(self) -> bool:
            return self.path in blobs

        def download_as_bytes(self) -> bytes:
            return blobs[self.path]

    bucket = SimpleNamespace(blob=Blob)
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: SimpleNamespace(bucket=lambda _name: bucket))

    uris = await storage.upload_processed_pages("bnd-1", "doc-1", [page(1, b"a"), page(2, b"b")])
    assert sorted(blobs) == ["bundles/bnd-1/pages/doc-1/page-001.png", "bundles/bnd-1/pages/doc-1/page-002.png"]
    assert set(uris) == {1, 2}
    assert await storage.download_processed_page("bnd-1", "doc-1", 2) == b"b"
    with pytest.raises(NotFoundError):
        await storage.download_processed_page("bnd-1", "doc-1", 9)


@pytest.mark.asyncio
async def test_a_storage_failure_is_an_upstream_error_that_does_not_echo_the_cause(monkeypatch) -> None:
    class Broken:
        def blob(self, path):
            raise PermissionError("secret: gs://bucket/path denied for sa@project")

    monkeypatch.setattr(storage, "_get_gcs_client", lambda: SimpleNamespace(bucket=lambda _name: Broken()))
    for call in (
        storage.upload_processed_pages("bnd-1", "doc-1", [page(1)]),
        storage.download_processed_page("bnd-1", "doc-1", 1),
    ):
        with pytest.raises(UpstreamError) as raised:
            await call
        assert "secret" not in raised.value.message and "PermissionError" in raised.value.message


# ---------------------------------------------------------------------------
# through the pipeline and the API
# ---------------------------------------------------------------------------


def scan_files() -> dict[str, bytes]:
    return {
        "commercial_invoice.pdf": scans.pdf(scans.skew(scans.make_page(seed=1), 3.0)),
        "bill_of_lading.pdf": scans.pdf(scans.make_page(seed=2)),
        "packing_list.pdf": scans.pdf(scans.make_page(seed=3)),
    }


@needs_poppler
@pytest.mark.asyncio
async def test_a_run_keeps_what_the_model_was_shown_and_the_endpoint_serves_it() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, scan_files())
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id, timeout=60))["state"] == "COMPLETE"

        for doc in (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]:
            meta = (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{doc['document_id']}/transform-metadata")).json()["transform_meta"]
            [entry] = meta
            assert entry["processed_uri"] == f"gs://{settings.raw_bucket}/bundles/{bundle_id}/pages/it0001/{doc['document_id']}/page-001.png"

            shown = await client.get(f"/api/v1/bundles/{bundle_id}/documents/{doc['document_id']}/pages/1")
            assert shown.status_code == 200 and shown.headers["content-type"] == "image/png"
            assert shown.headers["cache-control"] == "private, max-age=3600"
            image = Image.open(io.BytesIO(shown.content))
            assert image.size == (entry["width"], entry["height"]), "the stored page is the one the transform metadata describes"
            assert image.mode == "1", "the default input is 1-bit"


@needs_poppler
@pytest.mark.asyncio
async def test_each_assessment_keeps_its_own_pages_and_a_recompute_serves_the_pages_it_copied(monkeypatch) -> None:
    """"What the model saw" is per assessment: a later run with another image mode must not replace the answer for an earlier one."""
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, scan_files())
        doc_id = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"][0]["document_id"]
        url = f"/api/v1/bundles/{bundle_id}/documents/{doc_id}/pages/1"

        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id, timeout=60))["state"] == "COMPLETE"
        monkeypatch.setattr(settings, "page_image_mode", "gray")
        run_id = await orchestrator.start_run(bundle_id, mode="reassess")
        assert (await wait_for_run(bundle_id, run_id, timeout=60))["state"] == "COMPLETE"

        def mode_of(response) -> str:
            assert response.status_code == 200, response.text
            return Image.open(io.BytesIO(response.content)).mode

        assert mode_of(await client.get(url + "?iteration=1")) == "1", "assessment 1 was shown the 1-bit page, still"
        assert mode_of(await client.get(url + "?iteration=2")) == "L", "assessment 2 was shown the grayscale page"
        assert mode_of(await client.get(url)) == "L", "no iteration: the latest assessment's"

        run_id = await orchestrator.start_run(bundle_id, mode="recompute")  # reads nothing: it copies assessment 2
        assert (await wait_for_run(bundle_id, run_id, timeout=60))["state"] == "COMPLETE"
        record = await firestore.get_extraction_record(bundle_id, 3)
        assert record["derived_from"] == 2 and record["pages_iteration"] == 2
        assert (await client.get(url + "?iteration=3")).content == (await client.get(url + "?iteration=2")).content

        assert (await client.get(url + "?iteration=9")).status_code == 404, "an assessment that does not exist has no pages"
        assert (await client.get(url + "?iteration=0")).status_code == 422


@pytest.mark.asyncio
async def test_persisting_pages_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "persist_processed_pages", False)
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, scan_files())
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id, timeout=60))["state"] == "COMPLETE"
        doc = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"][0]
        meta = (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{doc['document_id']}/transform-metadata")).json()["transform_meta"]
        assert "processed_uri" not in meta[0]
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{doc['document_id']}/pages/1")).status_code == 404


@pytest.mark.asyncio
async def test_the_pages_endpoint_is_scoped_and_validates_the_page() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, scan_files())
        run_id = await orchestrator.start_run(bundle_id)
        await wait_for_run(bundle_id, run_id, timeout=60)
        doc_id = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"][0]["document_id"]
        other_bundle = await create_bundle_with_documents(client, {"commercial_invoice.pdf": scans.pdf(scans.make_page(seed=9))})

        statuses = {
            "an unknown document": (await client.get(f"/api/v1/bundles/{bundle_id}/documents/doc-0123456789abcdef/pages/1")).status_code,
            "another bundle's document": (await client.get(f"/api/v1/bundles/{other_bundle}/documents/{doc_id}/pages/1")).status_code,
            "a page that does not exist": (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{doc_id}/pages/2")).status_code,
            "page zero": (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{doc_id}/pages/0")).status_code,
            "not a number": (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{doc_id}/pages/abc")).status_code,
            "absurdly large": (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{doc_id}/pages/99999999")).status_code,
        }
        hostile = await asgi_call("GET", f"/api/v1/bundles/{bundle_id}/documents/../pages/1")

    assert statuses == {
        "an unknown document": 404, "another bundle's document": 404, "a page that does not exist": 404,
        "page zero": 422, "not a number": 422, "absurdly large": 422,
    }
    assert hostile.status == 404


def test_the_page_path_is_per_assessment_and_the_old_layout_still_resolves() -> None:
    assert storage.processed_page_path("b", "d", 1, 3) == "bundles/b/pages/it0003/d/page-001.png"
    assert storage.processed_page_path("b", "d", 1) == "bundles/b/pages/d/page-001.png", "pages kept before they were kept per assessment"
    assert storage.processed_page_path("b", "d", 1, None) == storage.processed_page_path("b", "d", 1, 0)


@pytest.mark.asyncio
async def test_two_assessments_store_two_page_sets_that_do_not_overwrite_each_other() -> None:
    await storage.upload_processed_pages("bnd-9", "doc-1", [page(1, b"first")], 1)
    await storage.upload_processed_pages("bnd-9", "doc-1", [page(1, b"second")], 2)
    assert await storage.download_processed_page("bnd-9", "doc-1", 1, 1) == b"first"
    assert await storage.download_processed_page("bnd-9", "doc-1", 1, 2) == b"second"
    with pytest.raises(NotFoundError):
        await storage.download_processed_page("bnd-9", "doc-1", 1)  # nothing in the old layout
