"""Unit tests for storage service, hashing, document upload, and retrieval."""

import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import storage
from app.services.storage import compute_sha256, document_id_from_sha256, upload_raw, download_raw


def test_sha256_and_document_id():
    sample_bytes = b"%PDF-1.4 Mock Trade Bundle Invoice Payload"
    sha = compute_sha256(sample_bytes)
    assert len(sha) == 64
    doc_id = document_id_from_sha256(sha)
    assert doc_id.startswith("doc-")
    assert len(doc_id) == 20  # "doc-" + 16 chars


@pytest.mark.asyncio
async def test_storage_upload_and_download_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))

    bundle_id = "test-bnd-01"
    data = b"%PDF-1.4 Fake PDF content"
    meta = await upload_raw(bundle_id, data, filename="invoice.pdf")

    assert meta["bundle_id"] == bundle_id
    assert meta["bytes"] == len(data)
    assert meta["filename"] == "invoice.pdf"

    retrieved = await download_raw(bundle_id, meta["document_id"])
    assert retrieved == data


@pytest.mark.asyncio
async def test_upload_transform_meta_writes_the_document_scoped_gcs_artifact(monkeypatch):
    uploaded: dict[str, object] = {}

    class Blob:
        def upload_from_string(self, data, content_type):
            uploaded.update(data=data, content_type=content_type)

    class Bucket:
        def blob(self, path):
            uploaded["path"] = path
            return Blob()

    monkeypatch.setattr(storage, "_get_gcs_client", lambda: SimpleNamespace(bucket=lambda _name: Bucket()))
    transforms = [{"document_id": "doc-1", "page": 1, "rotation": 0}]

    uri = await storage.upload_transform_meta("bnd-1", "doc-1", transforms)

    assert uri.endswith("/bundles/bnd-1/processed/doc-1/transform.json")
    assert uploaded["path"] == "bundles/bnd-1/processed/doc-1/transform.json"
    assert uploaded["content_type"] == "application/json"
    assert json.loads(uploaded["data"]) == transforms


@pytest.mark.asyncio
async def test_download_transform_meta_reads_the_document_scoped_gcs_artifact(monkeypatch):
    downloaded: dict[str, object] = {}
    transforms = [{"document_id": "doc-1", "page": 1, "rotation": 0}]

    class Blob:
        def exists(self):
            return True

        def download_as_bytes(self):
            return json.dumps(transforms).encode()

    class Bucket:
        def blob(self, path):
            downloaded["path"] = path
            return Blob()

    monkeypatch.setattr(storage, "_get_gcs_client", lambda: SimpleNamespace(bucket=lambda _name: Bucket()))

    assert await storage.download_transform_meta("bnd-1", "doc-1") == transforms
    assert downloaded["path"] == "bundles/bnd-1/processed/doc-1/transform.json"


@pytest.mark.asyncio
async def test_upload_processed_artifacts_writes_private_sequential_local_pdfs(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path))
    artifacts = [
        {"artifact_id": "part-001", "payload": b"%PDF-1.4 one"},
        {"artifact_id": "part-002", "payload": b"%PDF-1.4 two"},
    ]

    await storage.upload_processed_artifacts("bnd-1", "doc-1", artifacts)

    directory = tmp_path / "bundles" / "bnd-1" / "processed" / "doc-1"
    assert (directory / "part-001.pdf").read_bytes() == b"%PDF-1.4 one"
    assert (directory / "part-002.pdf").read_bytes() == b"%PDF-1.4 two"


@pytest.mark.asyncio
async def test_upload_processed_artifacts_writes_private_sequential_gcs_pdfs(monkeypatch):
    uploaded: list[tuple[str, bytes, str]] = []

    class Blob:
        def __init__(self, path):
            self.path = path

        def upload_from_string(self, data, content_type):
            uploaded.append((self.path, data, content_type))

    class Bucket:
        def blob(self, path):
            return Blob(path)

    monkeypatch.setattr(storage, "_get_gcs_client", lambda: SimpleNamespace(bucket=lambda _name: Bucket()))

    await storage.upload_processed_artifacts(
        "bnd-1",
        "doc-1",
        [{"artifact_id": "part-001", "payload": b"%PDF-1.4 one"}],
    )

    assert uploaded == [
        ("bundles/bnd-1/processed/doc-1/part-001.pdf", b"%PDF-1.4 one", "application/pdf")
    ]


@pytest.mark.asyncio
async def test_upload_document_endpoint_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create bundle
        create_resp = await client.post(
            "/api/v1/bundles",
            json={"reference": "REF-UPLOAD-01", "destination_country": "SG"},
        )
        bundle_id = create_resp.json()["id"]

        # Upload document
        fake_pdf = b"%PDF-1.5 Commercial Invoice content"
        files = {"file": ("invoice.pdf", fake_pdf, "application/pdf")}

        upload_resp = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files=files,
        )
        assert upload_resp.status_code == 201
        doc_data = upload_resp.json()
        assert doc_data["filename"] == "invoice.pdf"
        assert doc_data["bundle_id"] == bundle_id
        assert doc_data["bytes"] == len(fake_pdf)

        # Retrieve file using bundle-scoped route
        file_resp = await client.get(
            f"/api/v1/bundles/{bundle_id}/documents/{doc_data['document_id']}/file"
        )
        assert file_resp.status_code == 200
        assert file_resp.content == fake_pdf


@pytest.mark.asyncio
async def test_upload_document_invalid_mime():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/bundles",
            json={"reference": "REF-UPLOAD-02", "destination_country": "SG"},
        )
        bundle_id = create_resp.json()["id"]

        files = {"file": ("malicious.exe", b"MZ12345", "application/x-msdownload")}
        upload_resp = await client.post(
            f"/api/v1/bundles/{bundle_id}/documents",
            files=files,
        )
        assert upload_resp.status_code == 422
        assert upload_resp.json()["code"] == "VALIDATION_ERROR"
