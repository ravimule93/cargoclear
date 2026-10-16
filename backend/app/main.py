"""CargoClear-JAPAC Backend — FastAPI application entry point."""

from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import internal
from app.api.v1 import assessment, auth, bundles, corrections, demo, documents, meta, prefill, stream, usage
from app.core.config import settings
from app.gateway.ids import validate_path_ids
from app.gateway.limits import BodySizeLimitMiddleware, RateLimitMiddleware
from app.gateway.middleware import (
    ErrorEnvelopeMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    http_exception_handler,
    validation_error_handler,
)
from app.reference.loader import require_reference
from app.services import engines, orchestrator

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Refuse to start without the configured pipeline engine or with a malformed reference table; on shutdown, cancel the running analyses and wait
    (briefly) for them to record that they were cancelled."""
    engines.require_engine(settings.pipeline_engine)
    require_reference()  # a malformed rule table must stop the service here, not change a verdict silently
    if settings.app_mode == "live" and "daily_token_budget" not in settings.model_fields_set:
        # nobody chose the number: the placeholder default is enforced, and past it every new analysis answers 429 until 00:00 UTC
        logger.warning("daily_token_budget_is_the_default", limit_tokens=settings.daily_token_budget,
                       note="set DAILY_TOKEN_BUDGET to the number of tokens a day you are willing to spend (0 = no limit)")
    yield
    await orchestrator.shutdown(timeout=5)


def create_app() -> FastAPI:
    """Build the application. /docs, /redoc and /openapi.json exist only when ``settings.api_docs_enabled``."""
    docs = settings.api_docs_enabled
    app = FastAPI(
        lifespan=lifespan,
        title="CargoClear-JAPAC API",
        version="4.0.0",
        description=(
            "Pre-submission customs document assessment for JAPAC cross-border trade. "
            "Decision-support only — the authorised CHA decides."
        ),
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        dependencies=[Depends(validate_path_ids)],
    )

    # 422 and the Starlette HTTPExceptions (404 unknown route, 405, ...) answer the same envelope as everything else
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # -----------------------------------------------------------------------
    # Middleware. add_middleware puts the LAST one added OUTERMOST, so this reads inside-out. Request path:
    #   RequestContext -> SecurityHeaders -> CORS -> RateLimit -> BodySizeLimit -> ErrorEnvelope -> routes
    # (everything the guards refuse still carries the request id, the security headers and the CORS headers)
    # -----------------------------------------------------------------------
    app.add_middleware(ErrorEnvelopeMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    for router in (
        bundles.router,
        documents.router,
        assessment.router,
        corrections.router,
        prefill.router,
        stream.router,
        usage.router,
        meta.router,
        demo.router,
        auth.router,
    ):
        app.include_router(router, prefix="/api/v1")
    app.include_router(internal.router)  # Cloud Tasks only: outside /api/v1, which is all the UI's proxy forwards

    @app.get("/healthz", tags=["ops"], summary="Liveness probe")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"], summary="Readiness probe")
    async def readyz() -> dict:
        return {"status": "ok"}

    @app.get("/version", tags=["ops"], summary="Non-sensitive release identity")
    async def version() -> dict:
        """Identify the deployed build without exposing credentials or customer data.

        This endpoint deliberately reports configuration that a reviewer needs to
        connect a hosted result to its source revision. It is not a health check
        and must not be used to infer that external dependencies are available.
        """
        return {
            "application_version": app.version,
            "release_sha": settings.release_sha,
            "release_timestamp": settings.release_timestamp,
            "app_mode": settings.app_mode,
            "region": settings.region,
            "gemini_live_model": settings.gemini_live_model,
            "gemini_live_location": settings.gemini_live_location,
        }

    return app


app = create_app()
