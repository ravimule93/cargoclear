"""Audit append is safe against a second writer (D1).

On Firestore each event is created at document id ``f"{seq:010d}"`` with ``create()``: if another writer got that
sequence number first, ``create`` raises AlreadyExists, the tail is re-read and the append retried (at most 5
times). The stored ``event_id`` field keeps its old format, and the hash chain format is unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.gateway.errors import UpstreamError
from app.services import audit
from tests.unit.firestore_fakes import FakeFirestore

BUNDLE = "bnd-x"
COLLECTION = ("bundles", BUNDLE, "audit")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    client = FakeFirestore()
    monkeypatch.setattr(audit, "_get_firestore_client", lambda: client)
    return client


def record(event_type: str = "BUNDLE_CREATED", iteration: int = 0, **payload):
    return audit.record({"bundle_id": BUNDLE, "iteration": iteration, "audit_event_type": event_type,
                         "audit_payload": payload, "actor": "system"})


def chain(client: FakeFirestore) -> list[dict]:
    rows = [(path, data) for path, data in client.docs.items() if path[: len(COLLECTION)] == COLLECTION]
    return [data for _path, data in sorted(rows, key=lambda row: row[1]["seq"])]


def rival_writer(client: FakeFirestore, *, times: int):
    """Install a hook that, inside the first ``times`` create() calls, plays another process that wins the race:
    it appends a valid event at the very sequence number we are about to create."""
    state = {"left": times}

    def hook(path: tuple[str, ...], _data: dict) -> None:
        if path[: len(COLLECTION)] != COLLECTION or state["left"] <= 0:
            return
        state["left"] -= 1
        events = chain(client)
        prev_hash = events[-1]["hash"] if events else "GENESIS"
        seq = len(events) + 1
        ts = f"2026-10-10T00:00:0{seq}+00:00"
        client.docs[COLLECTION + (f"{seq:010d}",)] = {
            "event_id": f"{BUNDLE}:0:{seq}", "bundle_id": BUNDLE, "iteration": 0, "seq": seq, "ts": ts,
            "actor": "rival", "event_type": "RIVAL_EVENT", "payload": {"n": seq}, "prev_hash": prev_hash,
            "hash": audit.compute_hash(prev_hash, seq, ts, BUNDLE, 0, "RIVAL_EVENT", "rival", {"n": seq}),
        }

    client.before_create = hook
    return state


# ---------------------------------------------------------------------------
# the document id and create()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_firestore_document_id_is_the_zero_padded_sequence_number(fake) -> None:
    await record()
    await record("DOCUMENT_UPLOADED", 1)

    assert sorted(path[-1] for path in fake.docs if path[: len(COLLECTION)] == COLLECTION) == ["0000000001", "0000000002"]


@pytest.mark.asyncio
async def test_the_stored_event_id_field_keeps_its_old_format(fake) -> None:
    await record("ANALYSIS_STARTED", 3)

    [event] = chain(fake)
    assert event["event_id"] == f"{BUNDLE}:3:1" and event["seq"] == 1


@pytest.mark.asyncio
async def test_events_are_created_not_set(fake) -> None:
    await record()

    assert fake.where_calls("create") == [COLLECTION + ("0000000001",)]
    assert [path for path in fake.where_calls("set") if path[: len(COLLECTION)] == COLLECTION] == []


@pytest.mark.asyncio
async def test_zero_padded_ids_sort_in_sequence_order(fake) -> None:
    for _ in range(12):
        await record()

    ids = [path[-1] for path in fake.docs if path[: len(COLLECTION)] == COLLECTION]
    assert sorted(ids) == [f"{n:010d}" for n in range(1, 13)]
    assert [e["seq"] for e in chain(fake)] == list(range(1, 13))


@pytest.mark.asyncio
async def test_a_chain_written_the_normal_way_verifies(fake) -> None:
    for i in range(4):
        await record("X", i, i=i)

    events = await audit.list_audit_events(BUNDLE)
    assert audit.verify_audit_chain(events) == (True, None)
    assert [e["seq"] for e in events] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_the_hash_format_is_unchanged(fake) -> None:
    ctx = await record("X", 2, a=1)

    event = ctx["audit_event"]
    assert event["hash"] == audit.compute_hash("GENESIS", 1, event["ts"], BUNDLE, 2, "X", "system", {"a": 1})
    assert event["prev_hash"] == "GENESIS"


# ---------------------------------------------------------------------------
# a second writer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_losing_the_race_once_rereads_the_tail_and_appends_at_the_next_sequence_number(fake) -> None:
    rival_writer(fake, times=1)

    ctx = await record("ANALYSIS_STARTED", 1)

    events = chain(fake)
    assert [(e["seq"], e["event_type"]) for e in events] == [(1, "RIVAL_EVENT"), (2, "ANALYSIS_STARTED")]
    assert ctx["audit_event"]["seq"] == 2
    assert events[1]["prev_hash"] == events[0]["hash"]  # chained onto the rival's event, not onto GENESIS
    assert audit.verify_audit_chain(await audit.list_audit_events(BUNDLE)) == (True, None)
    assert len(fake.where_calls("create")) == 2  # the conflicting attempt and the successful one


@pytest.mark.asyncio
async def test_four_conflicts_in_a_row_still_succeed_on_the_fifth_attempt(fake) -> None:
    rival_writer(fake, times=4)

    ctx = await record()

    assert ctx["audit_event"]["seq"] == 5
    assert len(fake.where_calls("create")) == 5
    assert audit.verify_audit_chain(await audit.list_audit_events(BUNDLE)) == (True, None)


@pytest.mark.asyncio
async def test_five_conflicts_raise_in_live_mode(fake, monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")
    rival_writer(fake, times=99)

    with pytest.raises(UpstreamError) as raised:
        await record()

    assert len(fake.where_calls("create")) == 5, "at most five attempts"
    assert "conflict" in raised.value.message.lower()
    assert audit.verify_audit_chain(await audit.list_audit_events(BUNDLE)) == (True, None)  # the rivals' events are intact


@pytest.mark.asyncio
async def test_five_conflicts_in_demo_mode_are_logged_not_raised(fake) -> None:
    rival_writer(fake, times=99)

    ctx = await record()

    assert len(fake.where_calls("create")) == 5
    assert "audit_event" in ctx


@pytest.mark.asyncio
async def test_a_conflict_is_a_warning_not_an_error(fake) -> None:
    from structlog.testing import capture_logs

    rival_writer(fake, times=1)
    with capture_logs() as logs:
        await record()

    conflicts = [entry for entry in logs if entry["event"] == "audit_append_conflict"]
    assert len(conflicts) == 1 and conflicts[0]["log_level"] == "warning" and conflicts[0]["seq"] == 1


@pytest.mark.asyncio
async def test_the_tail_is_read_again_before_every_attempt(fake) -> None:
    rival_writer(fake, times=2)

    await record()

    # one tail read per attempt: two conflicts and the append that finally worked
    assert fake.where_calls("stream").count(COLLECTION) == 3


@pytest.mark.asyncio
async def test_another_create_error_is_not_retried_and_hides_its_text_in_live_mode(fake, monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")

    def fail(path, data):
        raise PermissionError("TOP-SECRET /Users/someone/key.json")

    fake.before_create = fail

    with pytest.raises(UpstreamError) as raised:
        await record()

    assert len(fake.where_calls("create")) == 1
    assert raised.value.message == "Audit event persist failed in live mode: PermissionError"


@pytest.mark.asyncio
async def test_two_appends_in_one_process_are_serialised_and_all_land(fake) -> None:
    import asyncio

    await asyncio.gather(*[record("X", i) for i in range(8)])

    assert [e["seq"] for e in chain(fake)] == list(range(1, 9))
    assert audit.verify_audit_chain(await audit.list_audit_events(BUNDLE)) == (True, None)
    assert len(fake.where_calls("create")) == 8, "the in-process lock means no self-inflicted conflicts"


@pytest.mark.asyncio
async def test_the_in_memory_branch_is_unchanged() -> None:
    audit._IN_MEMORY_AUDIT.clear()
    first = await record("A")
    second = await record("B")

    events = audit._IN_MEMORY_AUDIT[BUNDLE]
    assert [e["seq"] for e in events] == [1, 2]
    assert first["audit_event"]["event_id"] == f"{BUNDLE}:0:1"
    assert second["audit_event"]["prev_hash"] == first["audit_event"]["hash"]
    assert audit.verify_audit_chain(events) == (True, None)


# ---------------------------------------------------------------------------
# the rest of the audit module's contract (client factory, demo-mode fallbacks, chain verification)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failing_tail_read_in_demo_mode_is_logged_and_the_chain_starts_over(fake, monkeypatch) -> None:
    class Broken:
        def collection(self, name: str):
            return SimpleNamespace(document=lambda _id: SimpleNamespace(collection=lambda _n: _BrokenCollection(fake)))

    class _BrokenCollection:
        def __init__(self, store) -> None:
            self._real = store.collection("bundles").document(BUNDLE).collection("audit")

        def order_by(self, *_a, **_k):
            raise OSError("query failed")

        def document(self, doc_id: str):
            return self._real.document(doc_id)

    monkeypatch.setattr(audit, "_get_firestore_client", lambda: Broken())

    ctx = await record()

    assert ctx["audit_event"]["seq"] == 1 and ctx["audit_event"]["prev_hash"] == "GENESIS"


@pytest.mark.asyncio
async def test_a_failing_create_in_demo_mode_is_logged_and_the_event_is_still_returned(fake) -> None:
    def fail(path, data):
        raise PermissionError("denied")

    fake.before_create = fail

    ctx = await record()

    assert ctx["audit_event"]["seq"] == 1 and len(fake.where_calls("create")) == 1


def test_the_firestore_client_is_built_once_and_cached(monkeypatch) -> None:
    built: list[dict] = []
    monkeypatch.setattr(audit, "use_live_gcp", lambda: True)
    monkeypatch.setattr(
        "google.cloud.firestore_v1.async_client.AsyncClient", lambda **kw: built.append(kw) or SimpleNamespace(kind="client")
    )

    first, second = audit._get_firestore_client(), audit._get_firestore_client()

    assert first is second and len(built) == 1
    assert built[0] == {"project": settings.project_id, "database": settings.firestore_database}


def test_a_client_that_cannot_be_built_falls_back_to_memory_in_demo_mode(monkeypatch) -> None:
    def boom(**_kw):
        raise RuntimeError("no")

    monkeypatch.setattr(audit, "use_live_gcp", lambda: True)
    monkeypatch.setattr("google.cloud.firestore_v1.async_client.AsyncClient", boom)

    assert audit._get_firestore_client() is None


def test_an_empty_chain_verifies() -> None:
    assert audit.verify_audit_chain([]) == (True, None)


@pytest.mark.asyncio
async def test_a_broken_link_is_detected() -> None:
    audit._IN_MEMORY_AUDIT.clear()
    await record("A")
    await record("B")
    events = [dict(e) for e in audit._IN_MEMORY_AUDIT[BUNDLE]]
    events[1]["prev_hash"] = "f" * 64

    ok, reason = audit.verify_audit_chain(events)

    assert ok is False and reason.startswith("Broken link at seq=2")
