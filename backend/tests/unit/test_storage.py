"""Unit tests for storage service, hashing, document upload, and retrieval."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
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

        # Retrieve file
        file_resp = await client.get(f"/api/v1/documents/{doc_data['document_id']}/file")
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
