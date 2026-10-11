"""POST /bundles/{id}/documents and GET .../file: size, content, names, headers, per-bundle cap (C1-C5)."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import pytest

from app.api.v1 import documents
from app.core.config import settings
from app.gateway.errors import PayloadTooLargeError
from app.repo import firestore
from app.services import storage
from tests.helpers import api_client, case_c_pdf

KB = 1024
MB = 1024 * 1024


def pdf(label: str, extra: int = 0) -> bytes:
    return b"%PDF-1.4 " + label.encode() + b" " + b"x" * extra


async def new_bundle(client) -> str:
    return (await client.post("/api/v1/bundles", json={"reference": "DOCS"})).json()["id"]


async def upload(client, bundle_id: str, name: str, data: bytes, content_type: str = "application/pdf"):
    return await client.post(f"/api/v1/bundles/{bundle_id}/documents", files={"file": (name, data, content_type)})


# ---------------------------------------------------------------------------
# C1: the upload is read in 1 MiB chunks and cut as soon as the limit is crossed
# ---------------------------------------------------------------------------


class ChunkedUpload:
    """A stand-in for UploadFile: serves ``total`` bytes and counts what the handler asked for."""

    def __init__(self, total: int, filename: str = "big.pdf") -> None:
        self.remaining = total
        self.filename = filename
        self.content_type = "application/pdf"
        self.sizes_asked: list[int] = []
        self.bytes_served = 0

    async def read(self, size: int = -1) -> bytes:
        self.sizes_asked.append(size)
        count = self.remaining if size < 0 else min(size, self.remaining)
        self.remaining -= count
        self.bytes_served += count
        return b"%PDF-1.4 " + b"x" * (count - 9) if count and self.bytes_served == count else b"x" * count


@pytest.mark.asyncio
async def test_the_handler_reads_in_one_mebibyte_chunks_and_stops_as_soon_as_the_limit_is_crossed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 2)
    async with api_client() as client:
        bundle_id = await new_bundle(client)
    upload_file = ChunkedUpload(total=40 * MB)

    with pytest.raises(PayloadTooLargeError) as raised:
        await documents.upload_document(bundle_id, upload_file)

    assert raised.value.message == "The file is larger than 2 MB." and raised.value.http_status == 413
    assert set(upload_file.sizes_asked) == {MB}, "always one chunk at a time, never read() of everything"
    assert len(upload_file.sizes_asked) == 3, "2 MB allowed: two chunks fit, the third crosses the limit and stops the read"
    assert upload_file.bytes_served == 3 * MB, "never more than limit + one chunk"


@pytest.mark.asyncio
async def test_a_file_exactly_at_the_limit_is_accepted(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "edge.pdf", pdf("edge", MB - len(pdf("edge"))))

    assert response.status_code == 201, response.text
    assert response.json()["bytes"] == MB


@pytest.mark.asyncio
async def test_one_byte_over_the_limit_is_a_413_with_the_message(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "over.pdf", pdf("over", MB - len(pdf("over")) + 1))

    assert response.status_code == 413
    body = response.json()
    assert (body["code"], body["message"]) == ("PAYLOAD_TOO_LARGE", "The file is larger than 1 MB.")
    assert set(body) == {"code", "message", "detail", "request_id"}


@pytest.mark.asyncio
async def test_a_refused_upload_stores_nothing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        await upload(client, bundle_id, "over.pdf", pdf("over", 2 * MB - 100))
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()

    assert bundle["documents"] == []
    assert [e["event_type"] for e in audit["events"]] == ["BUNDLE_CREATED"]


@pytest.mark.asyncio
async def test_an_empty_file_is_still_the_existing_422() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "empty.pdf", b"")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR" and "empty" in response.json()["message"].lower()


@pytest.mark.asyncio
async def test_an_unknown_bundle_is_still_a_404() -> None:
    async with api_client() as client:
        response = await upload(client, "bnd-nope", "a.pdf", pdf("a"))

    assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_a_non_pdf_mime_with_a_non_pdf_name_is_still_refused() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "malicious.exe", b"MZ12345", "application/x-msdownload")

    assert response.status_code == 422 and "Only PDF files are accepted" in response.json()["message"]


# ---------------------------------------------------------------------------
# C2: content checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"MZ\x90\x00 an executable", b"PK\x03\x04 a zip", b"just some text"], ids=["exe", "zip", "text"])
async def test_bytes_that_are_not_a_pdf_are_refused_whatever_the_name_says(data) -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "invoice.pdf", data)
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()

    assert response.status_code == 422
    assert (response.json()["code"], response.json()["message"]) == ("VALIDATION_ERROR", "The file is not a PDF.")
    assert bundle["documents"] == []


@pytest.mark.asyncio
async def test_an_encrypted_pdf_is_refused() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "locked.pdf", b"%PDF-1.6\n<< /Filter /Standard /Encrypt 4 0 R >>")

    assert response.status_code == 422
    assert response.json()["message"] == "Password-protected PDFs are not supported."


@pytest.mark.asyncio
async def test_too_many_pages_are_refused_when_poppler_can_count_them(monkeypatch) -> None:
    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", lambda data, **_kw: {"Pages": 31})
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "long.pdf", pdf("long"))

    assert response.status_code == 422
    assert response.json()["message"] == f"The document has 31 pages; the limit is {settings.gemini_max_pages}."


@pytest.mark.asyncio
async def test_the_page_limit_is_the_gemini_setting(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_max_pages", 3)
    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", lambda data, **_kw: {"Pages": 4})
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "long.pdf", pdf("long"))

    assert response.json()["message"] == "The document has 4 pages; the limit is 3."


@pytest.mark.asyncio
async def test_without_poppler_the_page_check_is_skipped_silently(monkeypatch) -> None:
    def missing(_data, **_kw):
        raise RuntimeError("Unable to get page count. Is poppler installed and in PATH?")

    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", missing)
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, "ok.pdf", pdf("ok"))

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_the_page_count_runs_off_the_event_loop(monkeypatch) -> None:
    import threading

    seen: list[int] = []
    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", lambda data, **_kw: (seen.append(threading.get_ident()), {"Pages": 1})[1])
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        await upload(client, bundle_id, "ok.pdf", pdf("ok"))

    assert seen and threading.get_ident() not in seen


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf", "mtc_pipe_test_cert.pdf"])
async def test_the_case_c_pdfs_are_accepted(name) -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        response = await upload(client, bundle_id, name, case_c_pdf(name))

    assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# C3 + C4: names, and the download headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_chinese_file_name_uploads_and_downloads_with_a_correct_header() -> None:
    data = pdf("invoice")
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        created = await upload(client, bundle_id, "发票.pdf", data)
        document_id = created.json()["document_id"]

        download = await client.get(f"/api/v1/bundles/{bundle_id}/documents/{document_id}/file")

    assert created.status_code == 201 and created.json()["filename"] == "发票.pdf"
    assert download.status_code == 200, download.text
    assert download.content == data
    assert download.headers["content-disposition"] == "inline; filename=\"__.pdf\"; filename*=UTF-8''%E5%8F%91%E7%A5%A8.pdf"
    assert download.headers["cache-control"] == "private, max-age=3600"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_a_traversal_name_is_stored_audited_and_served_sanitised() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        created = await upload(client, bundle_id, "../../etc/passwd.pdf", pdf("p"))
        document_id = created.json()["document_id"]
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        download = await client.get(f"/api/v1/bundles/{bundle_id}/documents/{document_id}/file")

    assert created.json()["filename"] == "passwd.pdf"
    assert [d["filename"] for d in bundle["documents"]] == ["passwd.pdf"]
    assert [e["payload"]["filename"] for e in audit["events"] if e["event_type"] == "DOCUMENT_UPLOADED"] == ["passwd.pdf"]
    assert 'filename="passwd.pdf"' in download.headers["content-disposition"] and "etc" not in download.headers["content-disposition"]


@pytest.mark.asyncio
async def test_a_400_character_name_is_cut_to_150_everywhere() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        created = await upload(client, bundle_id, "n" * 396 + ".pdf", pdf("long-name"))
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()

    assert len(created.json()["filename"]) == 150 and created.json()["filename"].endswith(".pdf")
    assert [len(e["payload"]["filename"]) for e in audit["events"] if e["event_type"] == "DOCUMENT_UPLOADED"] == [150]


@pytest.mark.asyncio
async def test_the_classifier_sees_the_sanitised_name() -> None:
    from app.agents.extraction import classify_filename

    async with api_client() as client:
        bundle_id = await new_bundle(client)
        created = await upload(client, bundle_id, "C:\\scans\\..\\packing_list.pdf", pdf("pl"))

    assert created.json()["filename"] == "packing_list.pdf"
    assert classify_filename(created.json()["filename"]) == "PACKING_LIST"


@pytest.mark.asyncio
async def test_a_name_that_is_only_dots_becomes_document_pdf() -> None:
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        created = await upload(client, bundle_id, "...", pdf("dots"), "application/pdf")

    assert created.status_code == 201 and created.json()["filename"] == "document.pdf"


@pytest.mark.asyncio
async def test_a_document_stored_with_a_legacy_hostile_name_still_downloads_safely() -> None:
    """A record written before the sanitiser existed: the header builder must cope on its own."""
    from app.repo import firestore

    async with api_client() as client:
        bundle_id = await new_bundle(client)
        created = await upload(client, bundle_id, "ok.pdf", pdf("legacy"))
        document_id = created.json()["document_id"]
        firestore._IN_MEMORY_DOCS[bundle_id][document_id]["filename"] = '发"票\r\n.pdf'

        download = await client.get(f"/api/v1/bundles/{bundle_id}/documents/{document_id}/file")

    assert download.status_code == 200
    disposition = download.headers["content-disposition"]
    assert "\r" not in disposition and disposition.startswith("inline; filename=\"")


@pytest.mark.asyncio
async def test_transform_metadata_is_scoped_to_its_document_and_returned_as_private_json() -> None:
    transforms = [{"document_id": "placeholder", "page": 1, "rotation": 0, "deskew_deg": 0.0}]
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        created = await upload(client, bundle_id, "invoice.pdf", pdf("transform"))
        document_id = created.json()["document_id"]
        endpoint = f"/api/v1/bundles/{bundle_id}/documents/{document_id}/transform-metadata"

        missing_reference = await client.get(endpoint)
        transforms[0]["document_id"] = document_id
        uri = await storage.upload_transform_meta(bundle_id, document_id, transforms)
        await firestore.update_document_transform_meta_uri(bundle_id, document_id, uri)
        response = await client.get(endpoint)

    assert missing_reference.status_code == 404
    assert missing_reference.json()["code"] == "NOT_FOUND"
    assert response.status_code == 200
    assert response.json() == {"document_id": document_id, "transform_meta": transforms}
    assert "gs://" not in response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_transform_metadata_returns_404_for_a_missing_artifact_or_wrong_bundle() -> None:
    async with api_client() as client:
        source_bundle = await new_bundle(client)
        created = await upload(client, source_bundle, "invoice.pdf", pdf("transform-missing"))
        document_id = created.json()["document_id"]
        uri = f"gs://bucket/bundles/{source_bundle}/processed/{document_id}/transform.json"
        await firestore.update_document_transform_meta_uri(source_bundle, document_id, uri)

        missing = await client.get(
            f"/api/v1/bundles/{source_bundle}/documents/{document_id}/transform-metadata"
        )
        other_bundle = await new_bundle(client)
        wrong_bundle = await client.get(
            f"/api/v1/bundles/{other_bundle}/documents/{document_id}/transform-metadata"
        )

    for response in (missing, wrong_bundle):
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
        assert set(response.json()) == {"code", "message", "detail", "request_id"}


# ---------------------------------------------------------------------------
# C5: documents per bundle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_21st_distinct_document_is_refused() -> None:
    assert settings.max_documents_per_bundle == 20
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        for index in range(20):
            assert (await upload(client, bundle_id, f"d{index}.pdf", pdf(f"doc-{index}"))).status_code == 201

        refused = await upload(client, bundle_id, "d20.pdf", pdf("doc-20"))
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()

    assert refused.status_code == 422
    assert (refused.json()["code"], refused.json()["message"]) == ("VALIDATION_ERROR", "A bundle can hold at most 20 documents.")
    assert len(bundle["documents"]) == 20


@pytest.mark.asyncio
async def test_re_uploading_identical_bytes_is_idempotent_and_not_counted(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_documents_per_bundle", 2)
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        first = await upload(client, bundle_id, "one.pdf", pdf("one"))
        await upload(client, bundle_id, "two.pdf", pdf("two"))

        again = await upload(client, bundle_id, "one-renamed.pdf", pdf("one"))  # full bundle, but not a new document
        third = await upload(client, bundle_id, "three.pdf", pdf("three"))
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()

    assert again.status_code == 201 and again.json()["document_id"] == first.json()["document_id"]
    assert third.status_code == 422 and third.json()["message"] == "A bundle can hold at most 2 documents."
    # what a duplicate has always done, kept: the record is replaced (new name, type back to UNKNOWN) and re-audited
    assert sorted(d["filename"] for d in bundle["documents"]) == ["one-renamed.pdf", "two.pdf"]
    assert [e["event_type"] for e in audit["events"]].count("DOCUMENT_UPLOADED") == 3


@pytest.mark.asyncio
async def test_the_cap_is_per_bundle(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_documents_per_bundle", 1)
    async with api_client() as client:
        first, second = await new_bundle(client), await new_bundle(client)

        a = await upload(client, first, "a.pdf", pdf("a"))
        b = await upload(client, second, "b.pdf", pdf("b"))
        again = await upload(client, first, "c.pdf", pdf("c"))

    assert (a.status_code, b.status_code, again.status_code) == (201, 201, 422)


@pytest.mark.asyncio
async def test_simultaneous_uploads_cannot_overshoot_the_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_documents_per_bundle", 3)
    from app.repo import firestore

    real = firestore.create_evidence_document

    async def slow_register(bundle_id: str, doc_data: dict[str, Any]):
        await asyncio.sleep(0.02)  # a real store yields between the cap check and the write
        return await real(bundle_id, doc_data)

    monkeypatch.setattr(firestore, "create_evidence_document", slow_register)
    async with api_client() as client:
        bundle_id = await new_bundle(client)

        responses = await asyncio.gather(*[upload(client, bundle_id, f"d{i}.pdf", pdf(f"doc-{i}")) for i in range(8)])
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()

    assert sorted(r.status_code for r in responses) == [201] * 3 + [422] * 5
    assert len(bundle["documents"]) == 3


@pytest.mark.asyncio
async def test_the_document_id_is_still_content_addressed() -> None:
    data = pdf("addressed")
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        created = await upload(client, bundle_id, "a.pdf", data)

    assert created.json()["document_id"] == "doc-" + hashlib.sha256(data).hexdigest()[:16]


@pytest.mark.asyncio
async def test_a_bundle_that_disappears_while_the_upload_waits_for_the_lock_is_a_404(monkeypatch) -> None:
    from app.repo import firestore

    async with api_client() as client:
        bundle_id = await new_bundle(client)
        real = firestore.get_bundle
        reads = {"n": 0}

        async def vanishing(bid: str):
            reads["n"] += 1
            return await real(bid) if reads["n"] == 1 else None

        monkeypatch.setattr(firestore, "get_bundle", vanishing)

        response = await upload(client, bundle_id, "a.pdf", pdf("a"))

    assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"


def test_the_upload_lock_table_does_not_keep_idle_bundles() -> None:
    import gc

    async def use() -> None:
        async with documents._bundle_lock("bnd-transient"):
            assert "bnd-transient" in documents._BUNDLE_LOCKS

    asyncio.run(use())
    gc.collect()

    assert "bnd-transient" not in documents._BUNDLE_LOCKS
