"""Handing a queued run to a worker: Cloud Tasks (services/run_queue.py).

With ``RUN_DISPATCH=cloudtasks`` the API does not run an assessment itself. ``POST /analyze`` claims the bundle (a QUEUED
lease), writes the run record and enqueues ONE Cloud Task whose target is this service's internal worker endpoint
(``/internal/v1/runs/{bundle_id}/{run_id}/execute``). The worker request executes the pipeline, so:

* a run lives inside an HTTP request, which Cloud Run keeps alive (and CPU-allocated) until it ends: scale-in cannot kill it
  mid-run, and any instance can pick it up;
* Cloud Tasks delivers at least once, and retries when a worker dies; the lease makes that safe (a second delivery of a run
  that is being executed answers "busy"; the delivery after an executor died takes the run over, with a new fence);
* the queue's own ``max-concurrent-dispatches`` is the service-wide cap on concurrent runs (infra/tasks/setup_queue.sh).

The task carries no data: the lease holds the mode and iteration number, and the worker reads the bundle itself. The task
name is the run id, so enqueueing the same run twice is one task (Cloud Tasks answers AlreadyExists, which is success here).
The task is authenticated with an OIDC token of ``TASKS_SERVICE_ACCOUNT`` (audience = ``API_URL``); the API is private, so
that account holds ``roles/run.invoker`` and the worker endpoint accepts only it (api/internal.py).
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.core.config import settings
from app.gateway.errors import UpstreamError

logger = structlog.get_logger(__name__)

_client: Any = None


def execute_path(bundle_id: str, run_id: str) -> str:
    return f"/internal/v1/runs/{bundle_id}/{run_id}/execute"


def _require(value: str | None, name: str) -> str:
    if not value:
        raise UpstreamError(f"RUN_DISPATCH=cloudtasks needs {name} to be set")
    return value


def _get_client() -> Any:
    global _client
    if _client is None:
        from google.cloud import tasks_v2

        _client = tasks_v2.CloudTasksAsyncClient()
    return _client


def build_task(bundle_id: str, run_id: str) -> dict[str, Any]:
    """The Cloud Task (as the API's dict form) for one run. Pure: configuration in, a dict out."""
    from google.protobuf import duration_pb2

    api_url = _require(settings.api_url, "API_URL").rstrip("/")
    service_account = _require(settings.tasks_service_account, "TASKS_SERVICE_ACCOUNT")
    project = _require(settings.project_id, "PROJECT_ID")
    location = settings.tasks_location or settings.region
    from google.cloud import tasks_v2

    parent = tasks_v2.CloudTasksAsyncClient.queue_path(project, location, settings.tasks_queue)
    return {
        "name": f"{parent}/tasks/{run_id}",
        "dispatch_deadline": duration_pb2.Duration(seconds=int(settings.tasks_dispatch_deadline_seconds)),
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{api_url}{execute_path(bundle_id, run_id)}",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"bundle_id": bundle_id, "run_id": run_id}).encode("utf-8"),
            "oidc_token": {"service_account_email": service_account, "audience": api_url},
        },
    }


def queue_parent() -> str:
    from google.cloud import tasks_v2

    return tasks_v2.CloudTasksAsyncClient.queue_path(
        _require(settings.project_id, "PROJECT_ID"), settings.tasks_location or settings.region, settings.tasks_queue
    )


async def enqueue(bundle_id: str, run_id: str) -> None:
    """Enqueue the run. A task that already exists for this run is fine; anything else is an UpstreamError (the caller then
    releases the claim, so a queue outage never leaves a bundle locked)."""
    from google.api_core.exceptions import AlreadyExists, GoogleAPICallError

    task = build_task(bundle_id, run_id)
    try:
        await _get_client().create_task(request={"parent": queue_parent(), "task": task})
    except AlreadyExists:
        logger.info("run_task_already_enqueued", bundle_id=bundle_id, run_id=run_id)
    except GoogleAPICallError as exc:
        logger.error("run_task_enqueue_failed", bundle_id=bundle_id, run_id=run_id, error_type=type(exc).__name__)
        raise UpstreamError("The run could not be queued. Try again shortly.") from exc
    logger.info("run_task_enqueued", bundle_id=bundle_id, run_id=run_id, queue=settings.tasks_queue)
