"""The extraction answer cache (agents/extraction.py::_extract_cached): a document the bundle already had read with the SAME request is
not read again, so an unchanged reassessment costs no tokens. Fake client, no network, no credentials.

The request fingerprint covers what is sent (page labels, the SHA-256 of every page image, the instruction), the system prompt, the
schema, the model, the thinking and output settings: change any one and the model is asked again. The cache is per bundle, keeps only
the model's answer, and is a miss (never an error) when the store fails or an entry cannot be read.
"""

from __future__ import annotations

import pytest
from google.genai import types

from app.agents import extraction
from app.agents.extraction import run_extraction_agent
from app.core.config import settings
from app.gateway.errors import ExtractionError
from app.repo import firestore
from tests.unit.extraction_fakes import FakeGenai, always, ctx_for, good_doc, response, script

BUNDLE = "bnd-cache"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instantly(_seconds: float) -> None:
        return None

    monkeypatch.setattr(extraction, "_sleep", instantly, raising=False)


@pytest.fixture
def install(monkeypatch):
    """The fake stands in for the Gemini client while the app stays in demo mode: the bundle store is the in-memory one (live mode
    would ask for Google Cloud credentials the moment a bundle id is set)."""

    def _install(fake: FakeGenai) -> FakeGenai:
        monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
        return fake

    return _install


def run(*doc_ids: str, bundle: str = BUNDLE, **kw):
    return run_extraction_agent(ctx_for(*doc_ids, bundle_id=bundle, **kw))


async def test_the_second_run_over_unchanged_pages_makes_no_request_and_reads_the_same_document(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))

    first = await run("doc-1", "doc-2")
    second = await run("doc-1", "doc-2")

    assert len(fake.calls) == 2  # the two documents of the first run, nothing for the second
    assert [d.model_dump() for d in second["extracted"]] == [d.model_dump() for d in first["extracted"]]
    assert [s["cached"] for s in first["extraction_stats"]] == [False, False]
    for stat in second["extraction_stats"]:
        assert stat["cached"] is True and stat["attempts"] == 0 and stat["prompt_tokens"] == 0 and stat["output_tokens"] == 0


async def test_only_the_document_that_is_new_is_asked_about(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1", "doc-2")

    result = await run("doc-1", "doc-2", "doc-3")

    assert len(fake.calls) == 3
    assert [s["cached"] for s in result["extraction_stats"]] == [True, True, False]


async def test_a_kept_answer_still_gets_the_sanitiser_and_its_warnings(install) -> None:
    doc = good_doc()
    doc["consignee"]["bbox"]["ymax"] = 9999  # a box that cannot be right: dropped, with a warning
    install(FakeGenai(always(response(doc))))

    first = await run("doc-1")
    second = await run("doc-1")

    assert second["extracted"][0].consignee.bbox is None
    assert second["extraction_warnings"] == first["extraction_warnings"] != []


async def test_a_change_to_the_conversion_applies_to_a_kept_answer(install, monkeypatch) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    real = extraction._sanitise_extraction

    def stricter(raw, page_count):
        clean, warnings = real(raw, page_count)
        return clean, [*warnings, {"path": "x", "reason": "a rule added after the answer was kept"}]

    monkeypatch.setattr(extraction, "_sanitise_extraction", stricter)

    second = await run("doc-1")

    assert len(fake.calls) == 1 and second["extraction_stats"][0]["cached"] is True
    assert second["extraction_warnings"] == [{"document_id": "doc-1", "path": "x", "reason": "a rule added after the answer was kept"}]


# --- what makes it a different request ---


def _other_bytes(ctx):
    ctx["processed_pages"][0]["payload"] = b"the page was scanned again"


def _other_page_number(ctx):
    ctx["processed_pages"][0]["source_page"] = 4


def _other_total(ctx):
    ctx["processed_pages"][0]["total_pages"] = 12


def _other_mime(ctx):
    ctx["processed_pages"][0]["mime"] = "application/pdf"


@pytest.mark.parametrize("change", [_other_bytes, _other_page_number, _other_total, _other_mime],
                         ids=["page-bytes", "page-number", "pages-in-the-file", "mime"])
async def test_a_different_page_is_a_different_request(install, change) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    ctx = ctx_for("doc-1", bundle_id=BUNDLE)
    change(ctx)

    result = await run_extraction_agent(ctx)

    assert len(fake.calls) == 2 and result["extraction_stats"][0]["cached"] is False


async def test_an_added_page_is_a_different_request(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")

    await run("doc-1", pages=2)

    assert len(fake.calls) == 2


@pytest.mark.parametrize(
    ("what", "value"),
    [
        ("gemini_live_model", "gemini-3.5-flash"), ("gemini_thinking_budget", 1024), ("gemini_max_output_tokens", 8192),
    ],
)
async def test_a_different_model_or_setting_is_a_different_request(install, monkeypatch, what, value) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    monkeypatch.setattr(settings, what, value)

    await run("doc-1")

    assert len(fake.calls) == 2


async def test_a_different_thinking_level_is_a_different_request_on_gemini_3(install, monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_live_model", "gemini-3.5-flash")
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    monkeypatch.setattr(settings, "gemini_thinking_level", "HIGH")

    await run("doc-1")

    assert len(fake.calls) == 2


@pytest.mark.parametrize("name", ["SYSTEM_INSTRUCTION", "EXTRACT_INSTRUCTION"])
async def test_a_different_prompt_is_a_different_request(install, monkeypatch, name) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    monkeypatch.setattr(extraction, name, getattr(extraction, name) + " One more rule.")

    await run("doc-1")

    assert len(fake.calls) == 2


async def test_a_different_response_schema_is_a_different_request(install, monkeypatch) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    real = extraction.wire.Answer.model_json_schema
    monkeypatch.setattr(extraction.wire.Answer, "model_json_schema", classmethod(lambda cls, *a, **k: {**real(*a, **k), "title": "Other"}))

    await run("doc-1")

    assert len(fake.calls) == 2


async def test_a_new_cache_version_is_a_different_request(install, monkeypatch) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    monkeypatch.setattr(extraction, "CACHE_VERSION", extraction.CACHE_VERSION + 1)

    await run("doc-1")

    assert len(fake.calls) == 2


def test_the_fingerprint_is_stable_and_depends_on_the_bytes_not_on_the_list_object() -> None:
    pages = ctx_for("doc-1")["processed_pages"]
    again = [dict(page) for page in pages]

    assert extraction.extraction_fingerprint(types, "m", pages) == extraction.extraction_fingerprint(types, "m", again)
    assert extraction.extraction_fingerprint(types, "m", pages) != extraction.extraction_fingerprint(types, "n", pages)
    assert len(extraction.extraction_fingerprint(types, "m", pages)) == 64


# --- scope ---


async def test_another_bundle_never_reads_this_bundles_answers(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1", bundle="bnd-a")

    await run("doc-1", bundle="bnd-b")

    assert len(fake.calls) == 2


async def test_without_a_bundle_nothing_is_kept(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))

    await run("doc-1", bundle="")
    await run("doc-1", bundle="")

    assert len(fake.calls) == 2 and firestore._IN_MEMORY_EXTRACTION_CACHE == {}


async def test_the_cache_can_be_switched_off(install, monkeypatch) -> None:
    monkeypatch.setattr(settings, "extraction_cache", False)
    fake = install(FakeGenai(always(response(good_doc()))))

    await run("doc-1")
    await run("doc-1")

    assert len(fake.calls) == 2 and firestore._IN_MEMORY_EXTRACTION_CACHE == {}


async def test_only_the_models_answer_is_kept(install) -> None:
    install(FakeGenai(always(response(good_doc()))))

    await run("doc-1")

    [entry] = firestore._IN_MEMORY_EXTRACTION_CACHE[BUNDLE].values()
    assert set(entry) == {"document_id", "model", "answer_text", "prompt_tokens", "output_tokens", "thinking_tokens", "total_tokens", "bundle_id",
                     "fingerprint", "created_at", "expires_at"}
    assert entry["prompt_tokens"] == 1200 and entry["output_tokens"] == 340 and entry["model"] == settings.gemini_live_model


# --- failure modes: always a miss, never an error ---


async def test_a_store_that_cannot_be_read_costs_a_request_not_the_run(install, monkeypatch) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")

    async def broken(*_a, **_kw):
        raise ConnectionError("firestore is down")

    monkeypatch.setattr(firestore, "get_cached_answer", broken)

    result = await run("doc-1")

    assert len(fake.calls) == 2 and result["extracted"][0].document_id == "doc-1"


async def test_a_store_that_cannot_be_written_costs_the_next_run_its_saving_not_this_one_its_result(install, monkeypatch) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))

    async def broken(*_a, **_kw):
        raise ConnectionError("firestore is down")

    monkeypatch.setattr(firestore, "put_cached_answer", broken)

    result = await run("doc-1")
    await run("doc-1")

    assert result["extracted"][0].document_id == "doc-1" and len(fake.calls) == 2


@pytest.mark.parametrize("text", ["not json at all", "[1, 2]", '{"doc_type": "NOT_A_TYPE"}'])
async def test_an_entry_the_code_cannot_read_is_asked_about_again_and_replaced(install, text) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    [fingerprint] = firestore._IN_MEMORY_EXTRACTION_CACHE[BUNDLE]
    firestore._IN_MEMORY_EXTRACTION_CACHE[BUNDLE][fingerprint]["answer_text"] = text

    result = await run("doc-1")

    assert len(fake.calls) == 2 and result["extraction_stats"][0]["cached"] is False
    assert firestore._IN_MEMORY_EXTRACTION_CACHE[BUNDLE][fingerprint]["answer_text"] != text


# --- what a failed run leaves behind ---


async def test_a_document_that_was_read_before_a_sibling_failed_is_not_paid_for_again(install, monkeypatch) -> None:
    """The audit's finding 10: three clean documents were read and thrown away because a fourth hit its output cap."""
    monkeypatch.setattr(settings, "gemini_max_concurrency", 1)  # one at a time: doc-1 is answered before doc-2 fails
    truncated = response('{"doc_type": "COMMERCIAL_INV', finish="MAX_TOKENS")
    fake = install(FakeGenai(script(response(good_doc()), truncated, response(good_doc()))))

    with pytest.raises(ExtractionError):
        await run("doc-1", "doc-2")
    result = await run("doc-1", "doc-2")

    assert len(fake.calls) == 3  # doc-1, doc-2 (failed), then only doc-2 again
    assert [s["cached"] for s in result["extraction_stats"]] == [True, False]


async def test_an_answer_that_was_refused_is_not_kept(install) -> None:
    install(FakeGenai(always(response('{"doc_type": "COMMERCIAL_INV', finish="MAX_TOKENS"))))

    with pytest.raises(ExtractionError):
        await run("doc-1")

    assert firestore._IN_MEMORY_EXTRACTION_CACHE == {}


# --- how long a kept answer lives ---


async def test_a_kept_answer_carries_the_time_it_stops_being_used_and_the_ttl_policy_reads(install, monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(settings, "extraction_cache_ttl_days", 10)
    install(FakeGenai(always(response(good_doc()))))

    await run("doc-1")

    [entry] = firestore._IN_MEMORY_EXTRACTION_CACHE[BUNDLE].values()
    assert abs(entry["expires_at"] - (datetime.now(timezone.utc) + timedelta(days=10))) < timedelta(minutes=1)


async def test_an_answer_past_its_time_is_not_used_even_before_firestore_deletes_it(install) -> None:
    from datetime import datetime, timedelta, timezone

    fake = install(FakeGenai(always(response(good_doc()))))
    await run("doc-1")
    [entry] = firestore._IN_MEMORY_EXTRACTION_CACHE[BUNDLE].values()
    entry["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    second = await run("doc-1")

    assert len(fake.calls) == 2 and second["extraction_stats"][0]["cached"] is False  # asked again, and kept again
    [fresh] = firestore._IN_MEMORY_EXTRACTION_CACHE[BUNDLE].values()
    assert fresh["expires_at"] > datetime.now(timezone.utc)


def test_the_ttl_has_a_default_of_thirty_days_and_cannot_be_zero() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    assert settings.extraction_cache_ttl_days == 30
    with pytest.raises(ValidationError):
        Settings(EXTRACTION_CACHE_TTL_DAYS=0)
