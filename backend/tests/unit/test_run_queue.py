"""The Cloud Task of a run (services/run_queue.py): what it targets, how it authenticates, and what a failure to enqueue means."""

from __future__ import annotations

from typing import Any

import pytest
from google.api_core.exceptions import AlreadyExists, DeadlineExceeded, PermissionDenied

from app.core.config import settings
from app.gateway.errors import UpstreamError
from app.services import run_queue


@pytest.fixture(autouse=True)
def configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "project_id", "proj")
    monkeypatch.setattr(settings, "region", "asia-south1")
    monkeypatch.setattr(settings, "tasks_location", None)
    monkeypatch.setattr(settings, "tasks_queue", "cargoclear-runs")
    monkeypatch.setattr(settings, "api_url", "https://cargoclear-api-abc-el.a.run.app/")
    monkeypatch.setattr(settings, "tasks_service_account", "tasks-sa@proj.iam.gserviceaccount.com")
    monkeypatch.setattr(settings, "tasks_dispatch_deadline_seconds", 1500)


class FakeClient:
    def __init__(self, error: BaseException | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.error = error

    async def create_task(self, request: dict[str, Any]) -> None:
        self.requests.append(request)
        if self.error is not None:
            raise self.error


def test_the_task_targets_the_internal_worker_and_authenticates_as_the_tasks_account() -> None:
    task = run_queue.build_task("bnd-0123456789ab", "run-0123456789ab")
    request = task["http_request"]

    assert task["name"] == "projects/proj/locations/asia-south1/queues/cargoclear-runs/tasks/run-0123456789ab", "named by the run: a duplicate enqueue is one task"
    assert request["url"] == "https://cargoclear-api-abc-el.a.run.app/internal/v1/runs/bnd-0123456789ab/run-0123456789ab/execute"
    assert request["oidc_token"] == {
        "service_account_email": "tasks-sa@proj.iam.gserviceaccount.com",
        "audience": "https://cargoclear-api-abc-el.a.run.app",
    }, "the audience is the service URL without a trailing slash: what the worker verifies against"
    assert request["http_method"].name == "POST" and request["headers"] == {"Content-Type": "application/json"}
    assert task["dispatch_deadline"].seconds == 1500, "longer than the run deadline, so Cloud Tasks does not give up on a healthy run"
    assert b"bnd-0123456789ab" in request["body"] and b"run-0123456789ab" in request["body"]


def test_the_location_follows_the_region_unless_set(monkeypatch) -> None:
    assert "/locations/asia-south1/" in run_queue.build_task("b", "r")["name"]
    monkeypatch.setattr(settings, "tasks_location", "asia-southeast1")
    assert "/locations/asia-southeast1/" in run_queue.build_task("b", "r")["name"]


@pytest.mark.parametrize("missing", ["api_url", "tasks_service_account"])
def test_a_task_cannot_be_built_without_its_target_and_identity(monkeypatch, missing) -> None:
    monkeypatch.setattr(settings, missing, None)
    with pytest.raises(UpstreamError, match="needs"):
        run_queue.build_task("b", "r")


@pytest.mark.asyncio
async def test_enqueue_sends_the_task_to_the_queue(monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(run_queue, "_client", client)
    await run_queue.enqueue("bnd-0123456789ab", "run-0123456789ab")
    [request] = client.requests
    assert request["parent"] == "projects/proj/locations/asia-south1/queues/cargoclear-runs"
    assert request["task"]["name"].endswith("/tasks/run-0123456789ab")


@pytest.mark.asyncio
async def test_a_task_that_already_exists_is_success(monkeypatch) -> None:
    monkeypatch.setattr(run_queue, "_client", FakeClient(AlreadyExists("exists")))
    await run_queue.enqueue("b", "r")


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [PermissionDenied("secret: queue path /x/y"), DeadlineExceeded("slow")])
async def test_any_other_failure_is_an_upstream_error_with_a_fixed_text(monkeypatch, error) -> None:
    monkeypatch.setattr(run_queue, "_client", FakeClient(error))
    with pytest.raises(UpstreamError) as raised:
        await run_queue.enqueue("b", "r")
    assert raised.value.message == "The run could not be queued. Try again shortly." and "secret" not in raised.value.message
