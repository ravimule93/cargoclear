"""The worker endpoint Cloud Tasks calls (api/internal.py): who may call it, and what it answers."""

from __future__ import annotations

from typing import Any

import pytest

from app.api import internal
from app.core.config import settings
from app.repo import firestore, leases
from app.services import orchestrator, run_queue
from tests.helpers import api_client, asgi_call, create_bundle_with_documents
from tests.unit.test_run_lifecycle import FILES

CALLER = "cargoclear-tasks-sa@proj.iam.gserviceaccount.com"
AUDIENCE = "https://cargoclear-api-abc-el.a.run.app"


@pytest.fixture
def cloudtasks(monkeypatch) -> list[tuple[str, str]]:
    monkeypatch.setattr(settings, "run_dispatch", "cloudtasks")
    monkeypatch.setattr(settings, "api_url", AUDIENCE)
    monkeypatch.setattr(settings, "tasks_service_account", CALLER)
    monkeypatch.setattr(settings, "internal_caller_email", None)
    sent: list[tuple[str, str]] = []

    async def enqueue(bundle_id: str, run_id: str) -> None:
        sent.append((bundle_id, run_id))

    monkeypatch.setattr(run_queue, "enqueue", enqueue)
    return sent


def verifier(monkeypatch, claims: dict[str, Any] | Exception) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def verify(token: str, audience: str) -> dict[str, Any]:
        calls.append((token, audience))
        if isinstance(claims, Exception):
            raise claims
        return claims

    monkeypatch.setattr(internal, "_verify_token", verify)
    return calls


def call(bundle_id: str, run_id: str, token: str | None = "good-token"):
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return asgi_call("POST", f"/internal/v1/runs/{bundle_id}/{run_id}/execute", headers={**headers, "x-cloudtasks-taskname": "t-1", "x-cloudtasks-taskretrycount": "0"})


@pytest.mark.asyncio
async def test_the_endpoint_does_not_exist_unless_runs_are_dispatched() -> None:
    result = await call("bnd-0123456789ab", "run-0123456789ab")
    assert result.status == 404 and result.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["api_url", "tasks_service_account"])
async def test_a_misconfigured_service_refuses_everybody(cloudtasks, monkeypatch, missing) -> None:
    monkeypatch.setattr(settings, missing, None)
    calls = verifier(monkeypatch, {"email": CALLER, "email_verified": True})
    result = await call("bnd-0123456789ab", "run-0123456789ab")
    assert result.status == 403 and calls == [], "it never even looks at a token"


@pytest.mark.asyncio
async def test_a_request_without_a_bearer_token_is_401(cloudtasks, monkeypatch) -> None:
    calls = verifier(monkeypatch, {"email": CALLER, "email_verified": True})
    for headers in ({}, {"authorization": "Basic abc"}, {"authorization": "Bearer "}, {"authorization": "Bearer"}):
        result = await asgi_call("POST", "/internal/v1/runs/bnd-0123456789ab/run-0123456789ab/execute", headers=headers)
        assert result.status == 401 and result.json()["code"] == "UNAUTHORIZED"
    assert calls == []


@pytest.mark.asyncio
async def test_a_token_that_does_not_verify_is_401_and_the_text_is_not_echoed(cloudtasks, monkeypatch) -> None:
    verifier(monkeypatch, ValueError("Token expired: secret-token-text"))
    result = await call("bnd-0123456789ab", "run-0123456789ab", token="secret-token-text")
    assert result.status == 401 and "secret-token-text" not in result.body.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims",
    [
        {"email": "cargoclear-ui-sa@proj.iam.gserviceaccount.com", "email_verified": True},  # the UI also holds run.invoker
        {"email": CALLER, "email_verified": False},
        {"email": CALLER},
        {"email_verified": True},
        {},
    ],
)
async def test_only_the_cloud_tasks_account_with_a_verified_email_is_let_in(cloudtasks, monkeypatch, claims) -> None:
    verifier(monkeypatch, claims)
    result = await call("bnd-0123456789ab", "run-0123456789ab")
    assert result.status == 403 and result.json()["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_the_token_is_verified_against_this_services_url(cloudtasks, monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_url", AUDIENCE + "/")
    calls = verifier(monkeypatch, {"email": CALLER.upper(), "email_verified": True})
    result = await call("bnd-0123456789ab", "run-0123456789ab", token="the-jwt")
    assert calls == [("the-jwt", AUDIENCE)], "no trailing slash: the audience is the URL as Cloud Tasks wrote it"
    assert result.status == 200, "the email compares without case"


@pytest.mark.asyncio
async def test_a_verified_call_executes_the_run_and_answers_when_it_has_ended(cloudtasks, monkeypatch) -> None:
    verifier(monkeypatch, {"email": CALLER, "email_verified": True})
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        assert cloudtasks == [(bundle_id, run_id)]

        result = await call(bundle_id, run_id)
        assert result.status == 200 and result.json() == {"result": "done"}
        assert (await firestore.get_run_state(bundle_id, run_id))["state"] == "COMPLETE"

        again = await call(bundle_id, run_id)  # delivered a second time
        assert again.status == 200 and again.json() == {"result": "obsolete"}


@pytest.mark.asyncio
async def test_a_run_that_another_executor_has_answers_409_so_cloud_tasks_retries_later(cloudtasks, monkeypatch) -> None:
    verifier(monkeypatch, {"email": CALLER, "email_verified": True})
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        await leases.acquire(bundle_id, run_id, owner="another-worker")

        result = await call(bundle_id, run_id)
        assert result.status == 409 and result.json() == {"result": "busy"} and result.headers.get("retry-after") == "30"


@pytest.mark.asyncio
async def test_hostile_ids_are_the_same_404_and_the_route_is_not_documented(cloudtasks, monkeypatch) -> None:
    verifier(monkeypatch, {"email": CALLER, "email_verified": True})
    for bundle_id, run_id in (("..", "run-0123456789ab"), ("bnd-0123456789ab", "run-x"), ("bnd-0123456789ab", "a" * 3000)):
        result = await call(bundle_id, run_id)
        assert result.status == 404 and len(result.body) < 1000
    from app.main import app

    assert not any(path.startswith("/internal") for path in app.openapi()["paths"])


@pytest.mark.asyncio
async def test_the_internal_path_is_not_reachable_through_the_public_prefix(cloudtasks, monkeypatch) -> None:
    verifier(monkeypatch, {"email": CALLER, "email_verified": True})
    result = await asgi_call("POST", "/api/v1/internal/v1/runs/bnd-0123456789ab/run-0123456789ab/execute", headers={"authorization": "Bearer x"})
    assert result.status == 404
