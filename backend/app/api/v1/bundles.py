"""Bundles router — POST /bundles, GET /bundles/{bundle_id}."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from app.domain.schemas import BundleResponse, CreateBundleRequest
from app.gateway.errors import NotFoundError

router = APIRouter(tags=["bundles"])


@router.post("/bundles", response_model=BundleResponse, status_code=201)
async def create_bundle(body: CreateBundleRequest) -> BundleResponse:
    """Initialise a new shipment bundle and return its ID.

    Phase 1: Persists to Firestore.
    Skeleton: Returns an in-memory stub response.
    """
    # TODO(Phase 1): persist to Firestore via repo.firestore.create_bundle()
    bundle_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    return BundleResponse(
        id=bundle_id,
        reference=body.reference,
        destination_country=body.destination_country,
        status="PENDING",
        current_iteration=0,
        documents=[],
        created_at=now,
    )


@router.get("/bundles/{bundle_id}", response_model=BundleResponse)
async def get_bundle(bundle_id: str) -> BundleResponse:
    """Retrieve a bundle by ID.

    Phase 1: Reads from Firestore.
    Skeleton: Returns a stub response.
    """
    # TODO(Phase 1): fetch from Firestore via repo.firestore.get_bundle(bundle_id)
    raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})
