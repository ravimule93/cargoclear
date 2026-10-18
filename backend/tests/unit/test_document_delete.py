"""DELETE /bundles/{id}/documents/{doc} (audit fix item 10): a bad document can be taken out of a bundle.

What it removes (the stored files, the model's kept answers, the record), what it must not touch (other documents, other bundles, the
audit chain and the stored assessments), when it refuses (a run is live) and that a delete which stopped half way can be sent again.
Real poppler and the real Case C PDFs; no network, no credentials.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from typing import Any

import pytest

from app.agents import extraction
from app.agents.tools import bq_tariff
from app.api.v1 import documents
from app.core.config import settings
from app.gateway.errors import NotFoundError, UpstreamError
from app.repo import firestore, leases
from app.services import audit, orchestrator, storage, token_usage
from app.services.documents import register_document
from tests.helpers import api_client, case_c_pdf, wait_for_run
from tests.unit.extraction_fakes import case_c_gemini, first_page_of, response

needs_poppler = pytest.mark.skipif(
    shutil.which("pdftoppm") is None, reason="poppler is not installed"
)

PRELOADED = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf")
MTC = "mtc_pipe_test_cert.pdf"


async def new_bundle(client: Any, reference: str = "DELETE") -> str:
    return (await client.post("/api/v1/bundles", json={"reference": reference, "destination_country": "SG"})).json()["id"]


async def upload(client: Any, bundle_id: str, name: str) -> dict[str, Any]:
    response = await client.post(f"/api/v1/bundles/{bundle_id}/documents", files={"file": (name, case_c_pdf(name), "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()


async def demo_bundle(client: Any) -> tuple[str, dict[str, str]]:
    """The Case C demo bundle (three real PDFs) and {file name: document id}."""
    body = (await client.post("/api/v1/demo/case-c")).json()
    return body["id"], {d["filename"]: d["document_id"] for d in body["documents"]}


async def run(client: Any, bundle_id: str, action: str = "analyze") -> dict[str, Any]:
    response = await client.post(f"/api/v1/bundles/{bundle_id}/{action}")
    assert response.status_code == 202, response.text
    return await wait_for_run(bundle_id, response.json()["run_id"], timeout=30)


def files_of(document_id: str) -> list[str]:
    """Every file under the local storage that belongs to this document, whatever the bundle."""
    root = storage._get_local_storage_dir()
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and document_id in p.parts)


def digest_of(kwargs: dict[str, Any]) -> str:
    """Which document a Gemini request is about: the SHA-256 of its first page."""
    return hashlib.sha256(first_page_of(kwargs)).hexdigest()


def touch(relative: str) -> None:
    target = storage._get_local_storage_dir() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instantly(_seconds: float) -> None:
        return None

    monkeypatch.setattr(extraction, "_sleep", instantly, raising=False)


@pytest.fixture
def offline_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_MODE=live with every GCP client getter patched to None: in-memory stores, no credentials, no network."""
    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: None)
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: None)
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: None)
    monkeypatch.setattr(settings, "app_mode", "live")


# ---------------------------------------------------------------------------
# storage: which files go
# ---------------------------------------------------------------------------

A, B = "doc-aaaaaaaaaaaaaaaa", "doc-bbbbbbbbbbbbbbbb"


def lay_out_files() -> None:
    """Document A and B in bundle bnd-1 in every place the pipeline writes, and A again in another bundle."""
    for doc in (A, B):
        for relative in (
            f"bundles/bnd-1/raw/{doc}/original.pdf", f"bundles/bnd-1/raw/{doc}/meta.json",
            f"bundles/bnd-1/processed/{doc}/transform.json", f"bundles/bnd-1/processed/{doc}/artifact-1.pdf",
            f"bundles/bnd-1/pages/{doc}/page-001.png",  # pages kept per document, before they were kept per assessment
            f"bundles/bnd-1/pages/it0001/{doc}/page-001.png", f"bundles/bnd-1/pages/it0002/{doc}/page-002.png",
        ):
            touch(relative)
    touch(f"bundles/bnd-2/raw/{A}/original.pdf")
    touch(f"bundles/bnd-2/pages/it0001/{A}/page-001.png")


@pytest.mark.asyncio
async def test_every_file_of_the_document_goes_and_nothing_else() -> None:
    lay_out_files()
    before_b = files_of(B)

    removed = await storage.delete_document_files("bnd-1", A)

    assert removed == 7
    assert [f for f in files_of(A) if "bnd-1" in f] == []
    assert files_of(B) == before_b  # a sibling is untouched
    assert files_of(A) == [f"bundles/bnd-2/pages/it0001/{A}/page-001.png", f"bundles/bnd-2/raw/{A}/original.pdf"]  # so is another bundle


@pytest.mark.asyncio
async def test_a_second_delete_finds_nothing_and_is_not_an_error() -> None:
    lay_out_files()
    await storage.delete_document_files("bnd-1", A)

    assert await storage.delete_document_files("bnd-1", A) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("document_id", ["..", "../bnd-2", "doc-", "doc-AAAAAAAAAAAAAAAA", f"{A}/..", "", "pages", "doc-aaaaaaaaaaaaaaa"])
async def test_only_an_id_this_service_makes_may_name_a_folder_to_remove(document_id) -> None:
    lay_out_files()
    before = files_of(A) + files_of(B)

    with pytest.raises(NotFoundError):
        await storage.delete_document_files("bnd-1", document_id)

    assert files_of(A) + files_of(B) == before


class FakeBlob:
    def __init__(self, bucket: "FakeBucketStore", name: str) -> None:
        self.bucket, self.name = bucket, name

    def delete(self) -> None:
        if self.name in self.bucket.fail_on:
            raise RuntimeError("503 backend error")
        self.bucket.names.discard(self.name)


class FakeBucketStore:
    """A bucket of object names; ``list_blobs`` answers by prefix, as Cloud Storage does."""

    def __init__(self, names: list[str]) -> None:
        self.names = set(names)
        self.fail_on: set[str] = set()
        self.listed: list[tuple[str, str]] = []

    def list_blobs(self, bucket: str, prefix: str = "") -> list[FakeBlob]:
        self.listed.append((bucket, prefix))
        return [FakeBlob(self, n) for n in sorted(self.names) if n.startswith(prefix)]


def cloud_names() -> list[str]:
    names = []
    for doc in (A, B):
        names += [
            f"bundles/bnd-1/raw/{doc}/original.pdf", f"bundles/bnd-1/raw/{doc}/meta.json", f"bundles/bnd-1/processed/{doc}/transform.json",
            f"bundles/bnd-1/pages/{doc}/page-001.png", f"bundles/bnd-1/pages/it0001/{doc}/page-001.png",
        ]
    # lookalikes that must stay: another bundle, and a bundle whose id starts with this one's
    return names + [f"bundles/bnd-2/raw/{A}/original.pdf", f"bundles/bnd-10/raw/{A}/original.pdf", f"bundles/bnd-10/pages/it0001/{A}/page-001.png"]


@pytest.mark.asyncio
async def test_on_cloud_storage_the_document_is_found_by_prefix_and_only_its_own_objects_are_deleted(monkeypatch) -> None:
    bucket = FakeBucketStore(cloud_names())
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: bucket)

    removed = await storage.delete_document_files("bnd-1", A)

    assert removed == 5
    assert bucket.names == {n for n in cloud_names() if not ("bnd-1/" in n and A in n)}
    assert {bucket for bucket, _ in bucket.listed} == {settings.raw_bucket}


@pytest.mark.asyncio
async def test_a_cloud_storage_failure_is_an_upstream_error_and_a_repeat_removes_the_rest(monkeypatch) -> None:
    bucket = FakeBucketStore(cloud_names())
    monkeypatch.setattr(storage, "_get_gcs_client", lambda: bucket)
    bucket.fail_on = {f"bundles/bnd-1/processed/{A}/transform.json"}

    with pytest.raises(UpstreamError):
        await storage.delete_document_files("bnd-1", A)
    assert any(A in n and "bnd-1/" in n for n in bucket.names)  # the delete stopped part way

    bucket.fail_on = set()
    await storage.delete_document_files("bnd-1", A)
    assert not any(A in n and "bnd-1/" in n for n in bucket.names)


# ---------------------------------------------------------------------------
# Firestore: the two removals, against a fake client (no database here)
# ---------------------------------------------------------------------------


class FakeFirestore:
    """The few calls the two removals make, over a dict of document path -> data."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self.docs = dict(docs)
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.batches = 0

    def collection(self, name: str) -> "FakeCollection":
        return FakeCollection(self, name)

    def batch(self) -> "FakeBatch":
        return FakeBatch(self)


class FakeBatch:
    """Writes that land together or not at all: nothing is applied before ``commit``."""

    def __init__(self, store: FakeFirestore) -> None:
        self.store, self.operations = store, []

    def delete(self, ref: "FakeRef") -> None:
        self.operations.append(("delete", ref, None))

    def update(self, ref: "FakeRef", data: dict[str, Any]) -> None:
        self.operations.append(("update", ref, data))

    async def commit(self) -> None:
        self.store.batches += 1
        for kind, ref, data in self.operations:
            if kind == "delete":
                self.store.docs.pop(ref.path, None)
            else:
                self.store.updated.append((ref.path, data))


class FakeCollection:
    def __init__(self, store: FakeFirestore, path: str) -> None:
        self.store, self.path, self.wanted = store, path, None

    def document(self, doc_id: str) -> "FakeRef":
        return FakeRef(self.store, f"{self.path}/{doc_id}")

    def where(self, field: str, op: str, value: Any) -> "FakeCollection":
        assert op == "=="
        self.wanted = (field, value)
        return self

    async def stream(self):
        for path, data in sorted(self.store.docs.items()):
            if path.rsplit("/", 1)[0] == self.path and (self.wanted is None or data.get(self.wanted[0]) == self.wanted[1]):
                yield FakeSnap(self.store, path)


class FakeRef:
    def __init__(self, store: FakeFirestore, path: str) -> None:
        self.store, self.path = store, path

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.store, f"{self.path}/{name}")

    async def get(self) -> "FakeSnap":
        return FakeSnap(self.store, self.path)

    async def delete(self) -> None:
        self.store.docs.pop(self.path, None)

    async def update(self, data: dict[str, Any]) -> None:
        self.store.updated.append((self.path, data))


class FakeSnap:
    def __init__(self, store: FakeFirestore, path: str) -> None:
        self.reference = FakeRef(store, path)
        self.exists = path in store.docs


@pytest.mark.asyncio
async def test_only_the_kept_answers_of_that_document_in_that_bundle_are_removed_from_firestore(monkeypatch) -> None:
    cache = "bundles/bnd-1/extraction_cache"
    store = FakeFirestore({
        f"{cache}/fp-1": {"document_id": A}, f"{cache}/fp-2": {"document_id": A}, f"{cache}/fp-3": {"document_id": B},
        "bundles/bnd-2/extraction_cache/fp-1": {"document_id": A},
    })
    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: store)

    assert await firestore.delete_cached_answers("bnd-1", A) == 2

    assert sorted(store.docs) == [f"{cache}/fp-3", "bundles/bnd-2/extraction_cache/fp-1"]
    assert await firestore.delete_cached_answers("bnd-1", A) == 0


@pytest.mark.asyncio
async def test_the_record_is_removed_from_firestore_and_removing_it_twice_is_not_an_error(monkeypatch) -> None:
    store = FakeFirestore({f"bundles/bnd-1/documents/{A}": {"document_id": A}, f"bundles/bnd-1/documents/{B}": {"document_id": B}})
    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: store)

    assert await firestore.delete_evidence_document("bnd-1", A, gate_tokens=1_870) is True
    assert await firestore.delete_evidence_document("bnd-1", A, gate_tokens=1_870) is False

    assert sorted(store.docs) == [f"bundles/bnd-1/documents/{B}"]
    assert store.batches == 2  # the record and the bundle's figures change in one write
    first, second = store.updated
    assert first[0] == second[0] == "bundles/bnd-1" and "updated_at" in first[1]  # the bundle's updated_at moved
    assert first[1]["deleted_gate_tokens"].__class__.__name__ == "Increment" and first[1]["deleted_gate_tokens"].value == 1_870
    assert "deleted_gate_tokens" not in second[1]  # the repeat found no record: the cost is not counted twice


# ---------------------------------------------------------------------------
# the route: what is removed
# ---------------------------------------------------------------------------


@needs_poppler
@pytest.mark.asyncio
async def test_the_record_the_files_and_the_kept_answers_of_the_document_are_removed() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target, sibling = ids["commercial_invoice.pdf"], ids["bill_of_lading.pdf"]
        assert (await run(client, bundle_id))["state"] == "COMPLETE"
        await firestore.put_cached_answer(bundle_id, "fp-target", {"document_id": target, "answer_text": "{}"})
        await firestore.put_cached_answer(bundle_id, "fp-sibling", {"document_id": sibling, "answer_text": "{}"})
        assert any("/pages/" in f for f in files_of(target)) and any("/raw/" in f for f in files_of(target))  # there is something to remove

        response = await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["document_id"] == target and body["filename"] == "commercial_invoice.pdf"
        assert body["files_removed"] >= 3 and body["cached_answers_removed"] == 1
        assert files_of(target) == []
        assert files_of(sibling) != []  # the other documents of the bundle keep their files
        assert await firestore.get_cached_answer(bundle_id, "fp-target") is None
        assert await firestore.get_cached_answer(bundle_id, "fp-sibling") is not None
        listed = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]
        assert {d["document_id"] for d in listed} == set(ids.values()) - {target}
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{target}/file")).status_code == 404
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{target}/pages/1")).status_code == 404
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{sibling}/file")).status_code == 200


@pytest.mark.asyncio
async def test_a_deleted_document_does_not_count_towards_the_cap_and_can_be_uploaded_again(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_documents_per_bundle", 2)
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        first = await upload(client, bundle_id, PRELOADED[0])
        await upload(client, bundle_id, PRELOADED[1])
        assert (await client.post(f"/api/v1/bundles/{bundle_id}/documents", files={"file": (PRELOADED[2], case_c_pdf(PRELOADED[2]), "application/pdf")})).status_code == 422

        assert (await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{first['document_id']}")).status_code == 200

        third = await upload(client, bundle_id, PRELOADED[2])  # room again
        assert (await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{third['document_id']}")).status_code == 200
        again = await upload(client, bundle_id, PRELOADED[0])  # the bytes that were removed: the same content-addressed id, a new record
        assert again["document_id"] == first["document_id"]
        assert len((await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]) == 2
        assert files_of(first["document_id"]) != []


@pytest.mark.asyncio
async def test_unknown_bundles_and_documents_are_404_and_another_bundles_document_is_left_alone() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        other_id, other_ids = await demo_bundle(client)
        mine = ids["commercial_invoice.pdf"]
        theirs = other_ids["commercial_invoice.pdf"]
        assert mine == theirs  # same bytes, same content-addressed id, in two bundles

        assert (await client.delete(f"/api/v1/bundles/bnd-nope/documents/{mine}")).status_code == 404
        assert (await client.delete(f"/api/v1/bundles/{bundle_id}/documents/doc-0000000000000000")).status_code == 404
        assert (await client.delete(f"/api/v1/bundles/{bundle_id}/documents/..")).status_code in (404, 405)

        assert (await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{mine}")).status_code == 200
        assert (await client.get(f"/api/v1/bundles/{other_id}/documents/{theirs}/file")).status_code == 200
        assert len((await client.get(f"/api/v1/bundles/{other_id}")).json()["documents"]) == 3


# ---------------------------------------------------------------------------
# the audit chain, the stored assessments, the usage figures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_deletion_is_one_audit_event_and_the_chain_still_verifies() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["packing_list.pdf"]

        await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")

        log = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        deleted = [e for e in log["events"] if e["event_type"] == "DOCUMENT_DELETED"]
        assert len(deleted) == 1 and deleted[0]["actor"] == "user"
        payload = deleted[0]["payload"]
        assert payload["document_id"] == target and payload["filename"] == "packing_list.pdf"
        assert payload["sha256"] and payload["bytes"] > 0 and payload["files_removed"] >= 2
        assert [e["event_type"] for e in log["events"]].count("DOCUMENT_UPLOADED") == 3  # the upload stays in the history
        assert log["verified"] is True


@pytest.mark.asyncio
async def test_the_newest_assessment_is_not_touched_and_a_recompute_is_refused_until_a_reassess() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["commercial_invoice.pdf"]
        assert (await run(client, bundle_id))["state"] == "COMPLETE"
        before = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()

        body = (await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")).json()

        assert body["latest_iteration"] == 1 and body["in_latest_assessment"] is True
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json() == before
        refused = await client.post(f"/api/v1/bundles/{bundle_id}/recompute")
        assert refused.status_code == 409 and "Reassess" in refused.json()["message"]

        assert (await run(client, bundle_id, "reassess"))["state"] == "COMPLETE"
        after = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()
        assert after["iteration"] == 2 and target not in after["documents"]
        listing = (await client.get(f"/api/v1/bundles/{bundle_id}/iterations")).json()
        iterations = listing["iterations"] if isinstance(listing, dict) else listing
        assert target in next(i for i in iterations if i["iteration"] == 1)["documents"]  # the earlier assessment still says what it was made from


@pytest.mark.asyncio
async def test_a_document_that_was_not_in_the_newest_assessment_says_so() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        assert (await run(client, bundle_id))["state"] == "COMPLETE"
        late = await upload(client, bundle_id, MTC)

        body = (await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{late['document_id']}")).json()

        assert body["latest_iteration"] == 1 and body["in_latest_assessment"] is False
        assert (await run(client, bundle_id, "recompute"))["state"] == "COMPLETE"  # the document set is the analysed one again
        assert set(ids.values()) == set((await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()["documents"])


@pytest.mark.asyncio
async def test_a_correction_made_on_a_deleted_document_is_skipped_by_the_next_assessment_not_lost() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["commercial_invoice.pdf"]
        assert (await run(client, bundle_id))["state"] == "COMPLETE"
        made = await client.post(
            f"/api/v1/bundles/{bundle_id}/corrections", json={"document_id": target, "path": "consignee", "value": "SOMEONE ELSE PTE LTD"}
        )
        assert made.status_code in (200, 201), made.text

        await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")
        assert (await run(client, bundle_id, "reassess"))["state"] == "COMPLETE"

        latest = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()
        assert [c["status"] for c in latest["corrections"]] == ["skipped"]
        assert "not part of this analysis" in latest["corrections"][0]["note"]
        history = (await client.get(f"/api/v1/bundles/{bundle_id}/corrections")).json()
        assert len(history["corrections"]) == 1  # still in the history


@pytest.mark.asyncio
async def test_what_the_upload_check_cost_stays_in_the_usage_figures_after_the_document_is_gone() -> None:
    gate = token_usage.empty_gate_usage()
    gate.update(requests=1, prompt_tokens=1_860, output_tokens=10, total_tokens=1_870)
    async with api_client() as client:
        bundle_id = await new_bundle(client)
        gone = await register_document(bundle_id, data=case_c_pdf(PRELOADED[0]), filename=PRELOADED[0], gate_usage=gate)
        await register_document(bundle_id, data=case_c_pdf(PRELOADED[1]), filename=PRELOADED[1], gate_usage=gate)
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/usage")).json()["totals"]["upload_gate_tokens"] == 3_740

        assert (await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{gone['document_id']}")).status_code == 200

        assert (await client.get(f"/api/v1/bundles/{bundle_id}/usage")).json()["totals"]["upload_gate_tokens"] == 3_740


# ---------------------------------------------------------------------------
# when it refuses, and what it waits for
# ---------------------------------------------------------------------------


async def assert_untouched(client: Any, bundle_id: str, document_id: str) -> None:
    assert (await client.get(f"/api/v1/bundles/{bundle_id}/documents/{document_id}/file")).status_code == 200
    assert document_id in {d["document_id"] for d in (await client.get(f"/api/v1/bundles/{bundle_id}")).json()["documents"]}
    events = [e["event_type"] for e in (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["events"]]
    assert "DOCUMENT_DELETED" not in events


@pytest.mark.asyncio
async def test_a_run_in_progress_refuses_the_delete_and_nothing_is_removed() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["commercial_invoice.pdf"]
        await firestore.set_run_stage(bundle_id, "run-live", "extract", 0.3)  # a RUNNING record that is still heartbeating

        response = await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT" and "in progress" in response.json()["message"]
        await assert_untouched(client, bundle_id, target)


@pytest.mark.asyncio
async def test_a_run_that_is_queued_for_a_worker_refuses_the_delete() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["commercial_invoice.pdf"]
        await leases.claim(bundle_id, run_id="run-queued", mode="full", state=leases.QUEUED)

        response = await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")

        assert response.status_code == 409 and response.json()["detail"]["run_id"] == "run-queued"
        await assert_untouched(client, bundle_id, target)


@pytest.mark.asyncio
async def test_a_run_that_died_does_not_block_the_delete(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["commercial_invoice.pdf"]
        await firestore.set_run_stage(bundle_id, "run-dead", "extract", 0.3)
        monkeypatch.setattr(orchestrator, "_is_stale", lambda _run: True)  # its heartbeat stopped

        response = await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")

        assert response.status_code == 200
        events = [e["event_type"] for e in (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["events"]]
        assert "ANALYSIS_FAILED" in events and "DOCUMENT_DELETED" in events


@pytest.mark.asyncio
async def test_it_takes_the_upload_lock_so_the_two_cannot_interleave() -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["commercial_invoice.pdf"]
        lock = documents._bundle_lock(bundle_id)
        await lock.acquire()  # an upload is in its critical section
        pending = asyncio.create_task(client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}"))

        await asyncio.sleep(0.1)
        assert not pending.done()
        assert (await firestore.get_bundle_document(bundle_id, target)) is not None

        lock.release()
        assert (await pending).status_code == 200
        assert (await firestore.get_bundle_document(bundle_id, target)) is None


@pytest.mark.asyncio
async def test_no_run_can_start_while_a_delete_is_in_progress(monkeypatch) -> None:
    release = asyncio.Event()
    inside = asyncio.Event()
    real = storage.delete_document_files

    async def slow(bundle_id: str, document_id: str) -> int:
        inside.set()
        await release.wait()
        return await real(bundle_id, document_id)

    monkeypatch.setattr(storage, "delete_document_files", slow)
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["commercial_invoice.pdf"]
        deleting = asyncio.create_task(client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}"))
        await inside.wait()

        starting = asyncio.create_task(orchestrator.start_run(bundle_id, mode="full"))
        await asyncio.sleep(0.1)
        assert not starting.done(), "a run started while a document was being removed"

        release.set()
        assert (await deleting).status_code == 200
        run_id = await starting
        state = await wait_for_run(bundle_id, run_id, timeout=30)
        assert state["state"] == "COMPLETE"
        assert target not in (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()["documents"]  # it read what was left


@pytest.mark.asyncio
async def test_a_delete_that_failed_half_way_finishes_when_it_is_sent_again(monkeypatch) -> None:
    real = audit.record
    failures = {"left": 1}

    async def flaky(ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx.get("audit_event_type") == "DOCUMENT_DELETED" and failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("the audit store is down")
        return await real(ctx)

    monkeypatch.setattr(audit, "record", flaky)
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        target = ids["commercial_invoice.pdf"]

        failed = await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")

        assert failed.status_code == 500
        assert await firestore.get_bundle_document(bundle_id, target) is not None  # still listed, so it can be sent again
        assert files_of(target) == []  # the files went first
        retry = await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{target}")
        assert retry.status_code == 200 and retry.json()["files_removed"] == 0
        log = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        assert [e["event_type"] for e in log["events"]].count("DOCUMENT_DELETED") == 1 and log["verified"] is True
        assert await firestore.get_bundle_document(bundle_id, target) is None


# ---------------------------------------------------------------------------
# the same request limits as an upload, and the browser may send it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cors_preflight_for_delete_is_allowed() -> None:
    async with api_client() as client:
        response = await client.options(
            "/api/v1/bundles/bnd-1/documents/doc-aaaaaaaaaaaaaaaa",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "DELETE"},
        )

    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]


@pytest.mark.asyncio
async def test_deleting_counts_against_the_write_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 2)
    async with api_client() as client:
        statuses = [(await client.delete(f"/api/v1/bundles/bnd-x/documents/doc-{i:016x}")).status_code for i in range(3)]

    assert statuses == [404, 404, 429]


# ---------------------------------------------------------------------------
# the point of the route: one document the model cannot read no longer ruins the bundle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_document_the_model_cannot_read_is_taken_out_and_the_rest_cost_nothing_to_read_again(monkeypatch, offline_live) -> None:
    fake = await case_c_gemini(PRELOADED + (MTC,))
    bad_digest = next(d for d, name in fake.by_hash.items() if name == MTC)
    real_outcome = fake.outcome

    def outcome(number: int, kwargs: dict[str, Any]) -> Any:
        if digest_of(kwargs) == bad_digest:
            return response('{"document_id": "cut off', finish="MAX_TOKENS")  # what a dense 30-page file did in the audit (F16)
        return real_outcome(number, kwargs)

    fake.outcome = outcome
    fake.delay = lambda kwargs: 0.05 if digest_of(kwargs) == bad_digest else 0.0  # the others are answered, and kept, before it fails
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)

    async with api_client() as client:
        bundle_id = await new_bundle(client, "RUINED")
        ids = {name: (await upload(client, bundle_id, name))["document_id"] for name in PRELOADED + (MTC,)}

        failed = await run(client, bundle_id)
        assert failed["state"] == "ERROR"  # one document the model could not read: no verdict for the bundle
        assert (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).status_code == 404
        requests_for_the_failed_run = len(fake.calls)

        deleted = await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{ids[MTC]}")
        assert deleted.status_code == 200 and deleted.json()["latest_iteration"] is None

        fixed = await run(client, bundle_id)
        assert fixed["state"] == "COMPLETE"
        assessment = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()
        assert assessment["iteration"] == 1 and assessment["status"] == "MISSING_EVIDENCE"
        assert sorted(assessment["documents"]) == sorted(ids[n] for n in PRELOADED)
        # the three documents the model had read before the bad one failed were not read again
        assert len(fake.calls) == requests_for_the_failed_run
        usage = (await client.get(f"/api/v1/bundles/{bundle_id}/usage")).json()
        assert [r["state"] for r in usage["runs"]] == ["ERROR", "COMPLETE"]
        assert usage["runs"][1]["token_usage"]["requests"] == 0 and usage["runs"][1]["token_usage"]["saved_tokens"] > 0
        events = [e["event_type"] for e in (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["events"]]
        assert "ANALYSIS_FAILED" in events and "DOCUMENT_DELETED" in events and events[-1] == "ASSESSMENT_COMPLETED"


# ---------------------------------------------------------------------------
# one definition of "a run is in progress" for starting a run and for removing a document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["a running record", "a queued run holding the lease"])
async def test_starting_a_run_and_removing_a_document_agree_on_whether_the_bundle_is_busy(how) -> None:
    async with api_client() as client:
        bundle_id, ids = await demo_bundle(client)
        if how == "a running record":
            await firestore.set_run_stage(bundle_id, "run-live", "extract", 0.3)
            expected = "run-live"
        else:
            await leases.claim(bundle_id, run_id="run-queued", mode="full", state=leases.QUEUED)
            expected = "run-queued"

        started = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        removed = await client.delete(f"/api/v1/bundles/{bundle_id}/documents/{ids['commercial_invoice.pdf']}")

    assert started.status_code == removed.status_code == 409
    assert started.json()["detail"]["run_id"] == removed.json()["detail"]["run_id"] == expected
