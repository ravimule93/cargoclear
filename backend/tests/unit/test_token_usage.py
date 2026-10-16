"""services/token_usage.py and the extraction path that fills it: every request is recorded with what the API reported, refused and
failed ones included (the cost a leak is made of), and the summary is the shape the API returns."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents import extraction
from app.agents.extraction import run_extraction_agent
from app.domain.schemas import TokenUsage
from app.gateway.errors import ExtractionError
from app.services import token_usage
from app.services.token_usage import UsageLog, totals_of, usage_of
from tests.unit.extraction_fakes import HANG, FakeGenai, always, ctx_for, doc_of, good_doc, response, script

BUNDLE = "bnd-usage"


def metadata(**kw):
    return SimpleNamespace(usage_metadata=SimpleNamespace(**kw))


# --- reading what Gemini reported ---


def test_a_response_with_usage_metadata_gives_prompt_output_thinking_and_the_apis_own_total() -> None:
    reported = usage_of(metadata(prompt_token_count=1000, candidates_token_count=200, thoughts_token_count=300, total_token_count=1500))

    assert reported == {"prompt_tokens": 1000, "output_tokens": 200, "thinking_tokens": 300, "total_tokens": 1500}


def test_without_a_total_the_parts_are_summed_and_missing_counts_are_zero() -> None:
    assert usage_of(metadata(prompt_token_count=10, candidates_token_count=5)) == {
        "prompt_tokens": 10, "output_tokens": 5, "thinking_tokens": 0, "total_tokens": 15
    }
    assert usage_of(metadata(prompt_token_count=10, candidates_token_count=None, thoughts_token_count=None))["total_tokens"] == 10


def test_a_response_without_usage_reports_none_not_zero() -> None:
    assert usage_of(SimpleNamespace()) is None and usage_of(SimpleNamespace(usage_metadata=None)) is None


@pytest.mark.parametrize("junk", ["12", 1.5, True, None, [1]])
def test_a_count_that_is_not_an_integer_is_ignored(junk) -> None:
    assert usage_of(metadata(prompt_token_count=junk, candidates_token_count=4))["prompt_tokens"] == 0


# --- the log and its summary ---


def ok(prompt=100, output=50, thinking=0):
    return {"prompt_tokens": prompt, "output_tokens": output, "thinking_tokens": thinking, "total_tokens": prompt + output + thinking}


def test_the_summary_counts_ok_refused_error_and_cancelled_attempts_separately() -> None:
    log = UsageLog()
    log.record("d1", 1, "error: ClientError 429", None)
    log.record("d1", 2, "refused: finish_reason MAX_TOKENS: the answer was cut off", ok(100, 16384), "MAX_TOKENS")
    log.record("d1", 3, "ok", ok(100, 500, 20), "STOP")
    log.record("d2", 1, "cancelled", None)

    summary = log.summary(model="m", documents=[{"document_id": "d1", "filename": "a.pdf"}, {"document_id": "d2"}], mode="full")

    d1, d2 = summary["documents"]
    assert (d1["requests"], d1["failed_requests"], d1["unknown_requests"]) == (3, 2, 1)
    assert (d1["prompt_tokens"], d1["output_tokens"], d1["thinking_tokens"], d1["total_tokens"]) == (200, 16884, 20, 17104)
    assert [a["outcome"] for a in d1["attempts"]][1:] == ["refused: finish_reason MAX_TOKENS: the answer was cut off", "ok"]
    assert d1["attempts"][1]["finish_reason"] == "MAX_TOKENS" and d1["attempts"][0]["usage_reported"] is False
    assert (d2["requests"], d2["failed_requests"], d2["unknown_requests"], d2["total_tokens"]) == (1, 1, 1, 0)
    assert (summary["requests"], summary["failed_requests"], summary["unknown_requests"], summary["total_tokens"]) == (4, 3, 2, 17104)
    assert summary["filename" if False else "model"] == "m" and d1["filename"] == "a.pdf"
    TokenUsage(**summary)  # the shape the API returns


def test_a_cached_document_made_no_request_and_says_what_it_saved() -> None:
    log = UsageLog()
    log.record("d1", 1, "ok", ok(), "STOP")
    log.record_cached("d2", 6559)

    summary = log.summary(model="m", documents=[{"document_id": "d1"}, {"document_id": "d2"}], mode="reassess")

    d1, d2 = summary["documents"]
    assert d2["cached"] is True and d2["requests"] == 0 and d2["total_tokens"] == 0 and d2["saved_tokens"] == 6559
    assert d1["cached"] is False and d1["saved_tokens"] == 0
    assert (summary["cached_documents"], summary["saved_tokens"], summary["total_tokens"]) == (1, 6559, 150)


def test_the_gate_request_at_upload_is_shown_per_document_and_is_not_part_of_the_totals() -> None:
    log = UsageLog()
    log.record("d1", 1, "ok", ok(), "STOP")
    documents = [{"document_id": "d1", "gate_usage": {"total_tokens": 1881}}, {"document_id": "d2", "gate_usage": {"total_tokens": 1876}}]

    summary = log.summary(model="m", documents=documents, mode="full")

    assert [d["gate_tokens"] for d in summary["documents"]] == [1881, 1876]
    assert summary["total_tokens"] == 150 and summary["requests"] == 1


def test_a_document_the_run_did_not_touch_and_that_had_no_gate_request_is_left_out() -> None:
    log = UsageLog()
    log.record("d1", 1, "ok", ok(), "STOP")

    summary = log.summary(model="m", documents=[{"document_id": "d1"}, {"document_id": "d2"}], mode="full")

    assert [d["document_id"] for d in summary["documents"]] == ["d1"]


def test_a_run_that_asked_nothing_has_no_model_and_no_totals() -> None:
    summary = UsageLog().summary(model="m", documents=[{"document_id": "d1"}], mode="recompute")

    assert summary["model"] is None and summary["requests"] == 0 and summary["documents"] == [] and totals_of(summary) is None


def test_the_totals_for_an_audit_event_leave_out_the_rows() -> None:
    log = UsageLog()
    log.record("d1", 1, "ok", ok(100, 50, 7), "STOP")

    totals = totals_of(log.summary(model="m", documents=[{"document_id": "d1"}], mode="full"))

    assert totals == {"requests": 1, "failed_requests": 0, "unknown_requests": 0, "cached_documents": 0, "prompt_tokens": 100,
                      "output_tokens": 50, "thinking_tokens": 7, "total_tokens": 157, "saved_tokens": 0}


def test_the_summary_says_what_is_not_counted() -> None:
    summary = UsageLog().summary(model=None, documents=[], mode=None)

    assert "unknown_requests" in summary["note"] and "may still have been billed" in summary["note"]
    assert "price" not in summary["note"].lower() and "$" not in summary["note"]


# --- the extraction path fills the log ---


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    async def instantly(_seconds: float) -> None:
        return None

    monkeypatch.setattr(extraction, "_sleep", instantly, raising=False)


@pytest.fixture
def install(monkeypatch):
    def _install(fake: FakeGenai) -> FakeGenai:
        monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
        return fake

    return _install


def reply(doc=None, *, thoughts=None, total=None, **kw):
    out = response(doc if doc is not None else good_doc(), **kw)
    if out.usage_metadata is not None:
        out.usage_metadata.thoughts_token_count = thoughts
        out.usage_metadata.total_token_count = total
    return out


async def test_a_clean_read_is_one_ok_attempt_with_what_the_api_reported(install) -> None:
    install(FakeGenai(always(reply(thoughts=300, total=1840))))
    ctx = ctx_for("doc-1", bundle_id=BUNDLE)

    await run_extraction_agent(ctx)

    [attempt] = ctx["usage_log"].attempts
    assert attempt["outcome"] == "ok" and attempt["finish_reason"] == "STOP"
    assert (attempt["prompt_tokens"], attempt["output_tokens"], attempt["thinking_tokens"], attempt["total_tokens"]) == (1200, 340, 300, 1840)
    [stat] = ctx["extraction_stats"]
    assert stat["thinking_tokens"] == 300


async def test_an_answer_that_was_refused_still_counts_and_so_does_the_retry_that_followed(install) -> None:
    install(FakeGenai(script(reply("not json at all"), reply())))
    ctx = ctx_for("doc-1", bundle_id=BUNDLE)

    await run_extraction_agent(ctx)

    first, second = ctx["usage_log"].attempts
    assert first["outcome"] == "refused: response was not valid JSON" and first["usage_reported"] and first["prompt_tokens"] == 1200
    assert second["outcome"] == "ok"
    summary = ctx["usage_log"].summary(model="m", documents=ctx["documents"], mode="full")
    assert summary["requests"] == 2 and summary["failed_requests"] == 1 and summary["prompt_tokens"] == 2400


async def test_a_failed_call_is_counted_with_unknown_usage(install) -> None:
    from tests.unit.test_extraction_live import api_error

    install(FakeGenai(script(api_error(503), reply())))
    ctx = ctx_for("doc-1", bundle_id=BUNDLE)

    await run_extraction_agent(ctx)

    first, _second = ctx["usage_log"].attempts
    assert first["outcome"].startswith("error: ") and first["usage_reported"] is False and first["total_tokens"] == 0


async def test_an_answer_cut_off_at_the_output_cap_is_recorded_before_the_run_fails(install) -> None:
    """The audit's F16: 16,384 output tokens spent, the answer thrown away, and no record of it anywhere."""
    cut = reply('{"doc_type": "COMMERCIAL_INV', finish="MAX_TOKENS", thoughts=0, total=26431)
    cut.usage_metadata.prompt_token_count, cut.usage_metadata.candidates_token_count = 10047, 16384
    install(FakeGenai(always(cut)))
    ctx = ctx_for("doc-1", bundle_id=BUNDLE)

    with pytest.raises(ExtractionError):
        await run_extraction_agent(ctx)

    [attempt] = ctx["usage_log"].attempts
    assert attempt["outcome"].startswith("refused: finish_reason MAX_TOKENS") and attempt["finish_reason"] == "MAX_TOKENS"
    assert (attempt["prompt_tokens"], attempt["output_tokens"], attempt["total_tokens"]) == (10047, 16384, 26431)


async def test_a_sibling_cancelled_in_flight_is_recorded_as_cancelled(install, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.gemini_max_concurrency", 2)
    cut = reply('{"doc_type": "X', finish="MAX_TOKENS")
    # doc-1 is answered (and refused) a moment after doc-2's request is in flight: doc-2 is cancelled with its request out
    fake = install(FakeGenai(lambda _n, kw: cut if doc_of(kw) == "doc-1" else HANG, delay=lambda kw: 0.05 if doc_of(kw) == "doc-1" else 0.0))
    ctx = ctx_for("doc-1", "doc-2", bundle_id=BUNDLE)

    with pytest.raises(ExtractionError):
        await run_extraction_agent(ctx)

    by_doc = {a["document_id"]: a for a in ctx["usage_log"].attempts}
    assert by_doc["doc-1"]["outcome"].startswith("refused") and by_doc["doc-2"]["outcome"] == "cancelled"
    assert by_doc["doc-2"]["usage_reported"] is False and len(fake.calls) == 2


async def test_a_document_served_from_the_cache_is_recorded_with_what_its_first_read_cost(install) -> None:
    install(FakeGenai(always(reply(thoughts=10, total=1550))))
    await run_extraction_agent(ctx_for("doc-1", bundle_id=BUNDLE))
    ctx = ctx_for("doc-1", bundle_id=BUNDLE)

    await run_extraction_agent(ctx)

    assert ctx["usage_log"].attempts == [] and ctx["usage_log"].saved == {"doc-1": 1550}


async def test_a_cache_entry_kept_before_totals_existed_reports_its_parts(install) -> None:
    from app.repo import firestore

    install(FakeGenai(always(reply())))
    await run_extraction_agent(ctx_for("doc-1", bundle_id=BUNDLE))
    [entry] = firestore._IN_MEMORY_EXTRACTION_CACHE[BUNDLE].values()
    del entry["total_tokens"], entry["thinking_tokens"]
    ctx = ctx_for("doc-1", bundle_id=BUNDLE)

    await run_extraction_agent(ctx)

    assert ctx["usage_log"].saved == {"doc-1": 1200 + 340}


async def test_the_log_outlives_the_context_variable_and_is_per_run(install) -> None:
    install(FakeGenai(always(reply())))
    a, b = ctx_for("doc-1", bundle_id=BUNDLE), ctx_for("doc-2", bundle_id=BUNDLE)

    await run_extraction_agent(a)
    await run_extraction_agent(b)

    assert token_usage.CURRENT.get() is None
    assert [x["document_id"] for x in a["usage_log"].attempts] == ["doc-1"] and [x["document_id"] for x in b["usage_log"].attempts] == ["doc-2"]
