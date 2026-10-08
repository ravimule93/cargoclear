"""CargoClear-JAPAC Backend — FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.gateway.middleware import ErrorEnvelopeMiddleware, RequestContextMiddleware
from app.api.v1 import bundles, documents, assessment, stream
from app.core.config import settings

app = FastAPI(
    title="CargoClear-JAPAC API",
    version="4.0.0",
    description=(
        "Pre-submission adversarial customs adjudicator for JAPAC cross-border trade. "
        "Decision-support only — the authorised CHA decides."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------------------------
# Middleware (order matters — outermost is applied last)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

# NOTE: SSE stream router must NOT go through ErrorEnvelopeMiddleware
# (streaming responses cannot be re-wrapped). It is mounted separately below.
app.add_middleware(RequestContextMiddleware)
app.add_middleware(ErrorEnvelopeMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

for router in (bundles.router, documents.router, assessment.router, stream.router):
    app.include_router(router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------


@app.get("/healthz", tags=["ops"], summary="Liveness probe")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"], summary="Readiness probe")
async def readyz() -> dict:
    # TODO(Phase 1): Add Firestore + GCS connectivity checks
    return {"status": "ok"}
