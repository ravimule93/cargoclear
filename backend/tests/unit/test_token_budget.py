"""services/token_budget.py: the daily model-token budget. One counter for the whole service, per UTC day; checked when an analysis or a
reassessment starts and before a relevance check asks the model; counted when a run ends and when a relevance check is made. A recompute
is never refused. No Gemini, no credentials: a fake client where the pipeline needs one."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import structlog

from app.agents import extraction
from app.core.config import settings
from app.gateway.errors import TokenBudgetExceededError
from app.repo import firestore
from app.services import relevance, token_budget
from tests.gating import harness
from tests.helpers import api_client, case_c_pdf

NOON = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def small_budget(monkeypatch):
    monkeypatch.setattr(settings, "daily_token_budget", 5000)


# --- the counter ---


def test_the_day_is_the_utc_date_and_the_reset_is_the_next_midnight() -> None:
    assert token_budget.today(NOON) == "20261016"
    assert token_budget.seconds_until_reset(NOON) == 12 * 3600 + 1
    assert token_budget.seconds_until_reset(datetime(2026, 10, 16, 23, 59, 59, tzinfo=timezone.utc)) == 2
    assert token_budget.today(datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc)) == "20261231"


async def test_spend_adds_up_and_a_new_day_starts_at_zero(monkeypatch) -> None:
    monkeypatch.setattr(token_budget, "_now", lambda: NOON)
    await token_budget.add_spend(1200)
    await token_budget.add_spend(300)
    assert await token_budget.spent_today() == 1500

    monkeypatch.setattr(token_budget, "_now", lambda: datetime(2026, 10, 17, 0, 0, 1, tzinfo=timezone.utc))
    assert await token_budget.spent_today() == 0


@pytest.mark.parametrize("tokens", [0, -5])
async def test_nothing_is_counted_for_zero_or_negative(tokens) -> None:
    await token_budget.add_spend(tokens)

    assert firestore._IN_MEMORY_DAILY_TOKENS == {}


async def test_nothing_is_counted_when_the_budget_is_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_token_budget", 0)

    await token_budget.add_spend(1000)

    assert firestore._IN_MEMORY_DAILY_TOKENS == {}
    assert await token_budget.exhausted() is False
    await token_budget.check()


async def test_the_check_passes_under_the_limit_and_refuses_at_it() -> None:
    await token_budget.add_spend(4999)
    await token_budget.check()
    await token_budget.add_spend(1)

    with pytest.raises(TokenBudgetExceededError) as raised:
        await token_budget.check()

    error = raised.value
    assert error.http_status == 429 and error.code == "TOKEN_BUDGET_EXCEEDED"
    assert "resets at 00:00 UTC" in error.message and "Recompute" in error.message
    assert error.detail["limit_tokens"] == 5000 and 1 <= error.detail["resets_in_seconds"] <= 86401
    assert error.headers["Retry-After"] == str(error.detail["resets_in_seconds"])


async def test_a_counter_that_cannot_be_read_never_stops_the_product(monkeypatch) -> None:
    async def broken(_day):
        raise ConnectionError("firestore is down")

    monkeypatch.setattr(firestore, "get_daily_tokens", broken)
    with structlog.testing.capture_logs() as logs:
        await token_budget.check()
        assert await token_budget.exhausted() is False
        assert (await token_budget.status())["spent_tokens"] is None

    assert any(e["event"] == "token_budget_unavailable" and e["operation"] == "read" for e in logs)


async def test_a_counter_that_cannot_be_written_is_logged_not_raised(monkeypatch) -> None:
    async def broken(_day, _tokens):
        raise ConnectionError("firestore is down")

    monkeypatch.setattr(firestore, "add_daily_tokens", broken)
    with structlog.testing.capture_logs() as logs:
        await token_budget.add_spend(100)

    assert any(e["event"] == "token_budget_unavailable" and e["operation"] == "write" and e["tokens"] == 100 for e in logs)


async def test_the_status_says_the_limit_the_spend_what_remains_and_when_it_resets() -> None:
    await token_budget.add_spend(1500)

    status = await token_budget.status()

    assert status["limit_tokens"] == 5000 and status["enabled"] is True and status["spent_tokens"] == 1500
    assert status["remaining_tokens"] == 3500 and status["day"] == token_budget.today() and status["resets_in_seconds"] >= 1


async def test_remaining_never_goes_below_zero() -> None:
    await token_budget.add_spend(9000)

    assert (await token_budget.status())["remaining_tokens"] == 0


async def test_the_status_of_a_budget_that_is_off() -> None:
    settings.daily_token_budget = 0  # restored by the autouse fixture's monkeypatch teardown

    status = await token_budget.status()

    assert status["enabled"] is False and status["limit_tokens"] == 0 and status["remaining_tokens"] is None


# --- the Firestore document ---


async def test_a_day_is_one_document_with_an_atomic_increment_and_an_expiry(monkeypatch) -> None:
    written: list[tuple] = []

    class Document:
        def __init__(self, day):
            self.day = day

        async def set(self, data, merge=False):
            written.append((self.day, data, merge))

    class Client:
        def collection(self, name):
            assert name == "token_budget"
            return SimpleNamespace(document=Document)

    monkeypatch.setattr(firestore, "_get_firestore_client", lambda: Client())

    await firestore.add_daily_tokens("20261016", 1234)

    [(day, data, merge)] = written
    assert day == "20261016" and merge is True
    assert data["tokens"].__class__.__name__ == "Increment" and data["tokens"].value == 1234
    assert data["expires_at"].isoformat().startswith("2026-10-19")  # the day plus 3: Firestore deletes it after that, not before it is over


# --- the pipeline ---


class FakeVertex:
    """One document costs 1,000 + 50 tokens; the relevance check's answer is ``gate``."""

    def __init__(self, gate: str = "COMMERCIAL_INVOICE") -> None:
        self.gate, self.requests = gate, []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model, contents, config):
        is_gate = isinstance(getattr(config, "response_schema", None), dict)
        self.requests.append("gate" if is_gate else "extraction")
        text = json.dumps({"kind": self.gate}) if is_gate else json.dumps(
            {"doc_type": "COMMERCIAL_INVOICE", "doc_type_confidence": 0.9, "fields": [], "heat_numbers": [], "line_cells": [], "test_results": []}
        )
        return SimpleNamespace(
            text=text, candidates=[SimpleNamespace(finish_reason="STOP")], prompt_feedback=None,
            usage_metadata=SimpleNamespace(prompt_token_count=1000, candidates_token_count=50, thoughts_token_count=0, total_token_count=1050),
        )


@pytest.fixture
def vertex(monkeypatch):
    fake = FakeVertex()
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
    return fake


async def invoice_bundle(client) -> str:
    created = await client.post("/api/v1/bundles", json={"reference": "BUDGET", "destination_country": "SG"})
    bundle_id = created.json()["id"]
    uploaded = await harness.upload(client, bundle_id, "commercial_invoice.pdf", case_c_pdf("commercial_invoice.pdf"))
    assert uploaded.status_code == 201 if hasattr(uploaded, "status_code") else uploaded.status == 201
    return bundle_id


async def run(client, bundle_id, action):
    from tests.helpers import wait_for_run

    started = await client.post(f"/api/v1/bundles/{bundle_id}/{action}")
    if started.status_code == 202:
        await wait_for_run(bundle_id, started.json()["run_id"], timeout=60.0)
    return started


async def test_a_run_adds_what_it_spent_and_the_next_analysis_is_refused_once_the_budget_is_spent(vertex, monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_token_budget", 1000)  # one document costs 1,050
    async with api_client() as client:
        bundle_id = await invoice_bundle(client)
        first = await run(client, bundle_id, "analyze")
        spent = await token_budget.spent_today()
        refused = await client.post(f"/api/v1/bundles/{bundle_id}/analyze")
        reassess = await client.post(f"/api/v1/bundles/{bundle_id}/reassess")

    assert first.status_code == 202 and spent == 1050  # a run that started finishes, even past the limit
    for response in (refused, reassess):
        assert response.status_code == 429 and response.json()["code"] == "TOKEN_BUDGET_EXCEEDED"
        assert int(response.headers["Retry-After"]) >= 1
    assert len(vertex.requests) == 1  # nothing was asked after the budget was spent


async def test_a_recompute_is_never_refused_for_the_budget(vertex, monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_token_budget", 1000)
    async with api_client() as client:
        bundle_id = await invoice_bundle(client)
        await run(client, bundle_id, "analyze")
        assert await token_budget.exhausted()

        recompute = await run(client, bundle_id, "recompute")

    assert recompute.status_code == 202 and len(vertex.requests) == 1


async def test_a_refused_start_claims_nothing_and_the_next_day_it_runs(vertex, monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_token_budget", 1000)
    async with api_client() as client:
        bundle_id = await invoice_bundle(client)
        await run(client, bundle_id, "analyze")
        refused = await client.post(f"/api/v1/bundles/{bundle_id}/reassess")
        monkeypatch.setattr(token_budget, "_now", lambda: datetime(2099, 1, 1, 0, 0, 1, tzinfo=timezone.utc))  # tomorrow: a fresh counter

        again = await run(client, bundle_id, "reassess")

    assert refused.status_code == 429 and again.status_code == 202  # no lease was left claimed by the refusal


async def test_a_run_that_fails_still_counts_what_it_spent(vertex, monkeypatch) -> None:
    class Cut(FakeVertex):
        async def _generate(self, *, model, contents, config):
            reply = await super()._generate(model=model, contents=contents, config=config)
            if not isinstance(getattr(config, "response_schema", None), dict):
                reply.candidates = [SimpleNamespace(finish_reason="MAX_TOKENS")]
            return reply

    monkeypatch.setattr(extraction, "_get_genai_client", lambda: Cut())
    async with api_client() as client:
        bundle_id = await invoice_bundle(client)
        await run(client, bundle_id, "analyze")

    assert await token_budget.spent_today() == 1050


async def test_the_budget_off_means_nothing_is_counted_and_nothing_refused(vertex, monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_token_budget", 0)
    async with api_client() as client:
        bundle_id = await invoice_bundle(client)
        await run(client, bundle_id, "analyze")
        second = await run(client, bundle_id, "reassess")

    assert second.status_code == 202 and firestore._IN_MEMORY_DAILY_TOKENS == {}


async def test_the_route_shows_the_budget(vertex) -> None:
    await token_budget.add_spend(800)
    async with api_client() as client:
        body = (await client.get("/api/v1/token-budget")).json()

    assert body["limit_tokens"] == 5000 and body["spent_tokens"] == 800 and body["remaining_tokens"] == 4200 and body["enabled"] is True


# --- the relevance check ---


async def test_a_relevance_check_is_counted_and_a_refused_file_costs_the_same(monkeypatch) -> None:
    fake = FakeVertex(gate="OTHER")
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
    monkeypatch.setattr(relevance, "read_page_texts", lambda _data, _last: [""])
    monkeypatch.setattr(relevance, "_first_page_png", lambda _data: b"png")

    with pytest.raises(Exception, match="does not look like"):
        await relevance.check_document(b"%PDF-")

    assert await token_budget.spent_today() == 1050 and fake.requests == ["gate"]


async def test_when_the_budget_is_spent_the_relevance_check_does_not_ask_the_model(monkeypatch) -> None:
    fake = FakeVertex(gate="OTHER")
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
    monkeypatch.setattr(relevance, "read_page_texts", lambda _data, _last: [""])
    monkeypatch.setattr(relevance, "_first_page_png", lambda _data: b"png")
    await token_budget.add_spend(5000)

    with structlog.testing.capture_logs() as logs:
        assert await relevance.check_document(b"%PDF-") is None  # the file passes; extraction is what the budget stops

    assert fake.requests == [] and any(e["event"] == "relevance_gate_skipped" and e["reason"] == "daily_token_budget_spent" for e in logs)


# --- a failure after the run completed ---


async def test_a_failure_after_the_run_completed_does_not_count_its_tokens_again_or_turn_its_record_into_a_failure(vertex, monkeypatch) -> None:
    """The iteration is written and the run's usage kept (state COMPLETE, 1,050 tokens added to the day); then the last step, signing the
    audit head, fails. The run is marked failed, as it always was, but its tokens are not counted a second time and its record stays."""
    from app.services import signing

    async def broken(*_args, **_kwargs):
        raise RuntimeError("the signing store is down")

    monkeypatch.setattr(signing, "sign_head_quietly", broken)
    async with api_client() as client:
        bundle_id = await invoice_bundle(client)
        await run(client, bundle_id, "analyze")
        usage = (await client.get(f"/api/v1/bundles/{bundle_id}/usage")).json()

    assert await token_budget.spent_today() == 1050
    assert [(r["state"], r["iteration"], r["token_usage"]["total_tokens"]) for r in usage["runs"]] == [("COMPLETE", 1, 1050)]


# --- the default is not a decision ---


async def test_a_live_service_that_was_never_told_its_budget_says_so_at_start(monkeypatch) -> None:
    from app.main import create_app, lifespan

    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(type(settings), "model_fields_set", property(lambda _self: set()))

    with structlog.testing.capture_logs() as logs:
        async with lifespan(create_app()):
            pass

    [warning] = [entry for entry in logs if entry["event"] == "daily_token_budget_is_the_default"]
    assert warning["limit_tokens"] == settings.daily_token_budget and warning["log_level"] == "warning"


async def test_a_budget_that_was_set_is_not_warned_about(monkeypatch) -> None:
    from app.main import create_app, lifespan

    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(type(settings), "model_fields_set", property(lambda _self: {"daily_token_budget"}))

    with structlog.testing.capture_logs() as logs:
        async with lifespan(create_app()):
            pass

    assert not [entry for entry in logs if entry["event"] == "daily_token_budget_is_the_default"]
