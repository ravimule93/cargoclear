"""Internal endpoints: called by Cloud Tasks, never by a browser or the UI.

``POST /internal/v1/runs/{bundle_id}/{run_id}/execute`` is the WORKER of a dispatched run (RUN_DISPATCH=cloudtasks,
services/run_queue.py): it executes the pipeline of a queued run and answers when the run has ended. It lives outside
``/api/v1``, which is all the UI's proxy forwards, and is protected twice:

1. Cloud Run's own IAM check: the service is private, and only an identity holding ``roles/run.invoker`` gets here at all.
   The UI's service account holds it too, so IAM alone is not enough:
2. the request must carry an OIDC token that is VERIFIED here (signature, audience = this service's URL, ``email_verified``)
   and whose email is the Cloud Tasks service account (``INTERNAL_CALLER_EMAIL``, default ``TASKS_SERVICE_ACCOUNT``).

Answers: 200 ``done`` (the run ended, complete or failed: Cloud Tasks must not retry a deterministic failure) or ``obsolete``
(the run no longer owns its bundle: nothing to do); 409 ``busy`` (another executor is running it: Cloud Tasks retries later,
which is how a dead executor's run is taken over once its lease has expired).

In every other mode (RUN_DISPATCH=local) the endpoint does not exist: 404.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.gateway.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.services import orchestrator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal/v1", tags=["internal"], include_in_schema=False)

_AUTH_FAILED = "The caller could not be authenticated."


def _verify_token(token: str, audience: str) -> dict[str, Any]:
    """The verified claims of a Google-signed OIDC token for ``audience``. Blocking (it may fetch Google's certificates,
    which google-auth caches); called in a worker thread. Raises ``ValueError`` for any token that does not verify."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    claims: dict[str, Any] = id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)  # type: ignore[no-untyped-call]
    return claims


def expected_caller() -> str | None:
    return settings.internal_caller_email or settings.tasks_service_account


async def require_internal_caller(request: Request) -> None:
    """Only the Cloud Tasks service account, with a verified token, in cloudtasks mode."""
    if settings.run_dispatch != "cloudtasks":
        raise NotFoundError("Not found.")
    audience, caller = settings.api_url, expected_caller()
    if not audience or not caller:  # a misconfigured service must refuse, never accept
        logger.error("internal_endpoint_misconfigured", has_audience=bool(audience), has_caller=bool(caller))
        raise ForbiddenError(_AUTH_FAILED)

    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError(_AUTH_FAILED)
    try:
        claims = await asyncio.to_thread(_verify_token, token.strip(), audience.rstrip("/"))
    except Exception as exc:  # noqa: BLE001 - any verification failure is the same answer; the text may carry the token
        logger.warning("internal_token_rejected", error_type=type(exc).__name__)
        raise UnauthorizedError(_AUTH_FAILED) from exc
    if claims.get("email_verified") is not True or str(claims.get("email", "")).lower() != caller.lower():
        logger.warning("internal_caller_refused", email_claim_present=bool(claims.get("email")))
        raise ForbiddenError(_AUTH_FAILED)


@router.post("/runs/{bundle_id}/{run_id}/execute", dependencies=[Depends(require_internal_caller)])
async def execute_run(request: Request, bundle_id: str = Path(...), run_id: str = Path(...)) -> JSONResponse:
    """Execute a queued run; returns when it has ended."""
    logger.info(
        "run_task_received", bundle_id=bundle_id, run_id=run_id,
        task=request.headers.get("x-cloudtasks-taskname"), retry=request.headers.get("x-cloudtasks-taskretrycount"),
    )
    result = await orchestrator.execute_queued(bundle_id, run_id)
    if result == "busy":
        return JSONResponse({"result": "busy"}, status_code=409, headers={"Retry-After": "30"})
    return JSONResponse({"result": result})
