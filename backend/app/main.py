"""CargoClear-JAPAC Backend — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import bundles, demo, documents, assessment, stream, meta, auth
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
from app.services import engines, orchestrator


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Refuse to start without the configured pipeline engine; on shutdown, cancel the running analyses and wait
    (briefly) for them to record that they were cancelled."""
    engines.require_engine(settings.pipeline_engine)
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
            "Pre-submission adversarial customs adjudicator for JAPAC cross-border trade. "
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
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    for router in (
        bundles.router,
        documents.router,
        assessment.router,
        stream.router,
        meta.router,
        demo.router,
        auth.router,
    ):
        app.include_router(router, prefix="/api/v1")

    @app.get("/healthz", tags=["ops"], summary="Liveness probe")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"], summary="Readiness probe")
    async def readyz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
