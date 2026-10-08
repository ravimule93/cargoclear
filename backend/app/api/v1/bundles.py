"""Bundles router — POST /bundles, GET /bundles/{bundle_id}."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from app.domain.schemas import BundleResponse, CreateBundleRequest
from app.gateway.errors import NotFoundError
from app.repo import firestore
from app.services import audit

router = APIRouter(tags=["bundles"])


@router.post(
    "/bundles",
    response_model=BundleResponse,
    status_code=201,
    summary="Create a new trade assessment bundle",
)
async def create_bundle(body: CreateBundleRequest) -> BundleResponse:
    """Initialise a new shipment bundle and persist to Firestore."""
    bundle_id = f"bnd-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    bundle_data = {
        "id": bundle_id,
        "reference": body.reference,
        "destination_country": body.destination_country.upper(),
        "status": "PENDING",
        "current_iteration": 0,
        "created_at": now,
        "updated_at": now,
    }

    # Persist bundle
    await firestore.create_bundle(bundle_data)

    # Record initial audit event
    await audit.record({
        "bundle_id": bundle_id,
        "iteration": 0,
        "audit_event_type": "BUNDLE_CREATED",
        "audit_payload": {
            "reference": body.reference,
            "destination_country": body.destination_country.upper(),
        },
        "actor": "user",
    })

    return BundleResponse(
        id=bundle_id,
        reference=body.reference,
        destination_country=body.destination_country.upper(),
        status="PENDING",
        current_iteration=0,
        documents=[],
        created_at=now,
    )


@router.get(
    "/bundles/{bundle_id}",
    response_model=BundleResponse,
    summary="Get bundle details and attached documents",
)
async def get_bundle(bundle_id: str) -> BundleResponse:
    """Retrieve an existing bundle with all attached evidence documents."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    return BundleResponse(
        id=bundle["id"],
        reference=bundle.get("reference"),
        destination_country=bundle.get("destination_country", "SG"),
        status=bundle.get("status", "PENDING"),
        current_iteration=bundle.get("current_iteration", 0),
        documents=bundle.get("documents", []),
        created_at=bundle.get("created_at", ""),
    )
