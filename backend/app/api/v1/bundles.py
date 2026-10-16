"""Bundles router — POST /bundles, GET /bundles/{bundle_id}, GET /audit, GET /extractions."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.domain.auth import UserIdentity
from app.domain.schemas import BundleResponse, CreateBundleRequest
from app.gateway.auth import get_current_user
from app.gateway.errors import ConflictError, ForbiddenError, NotFoundError
from app.repo import firestore
from app.services import audit, corrections, signing

router = APIRouter(tags=["bundles"])


@router.post(
    "/bundles",
    response_model=BundleResponse,
    status_code=201,
    summary="Create a new trade assessment bundle",
)
async def create_bundle(
    body: CreateBundleRequest,
    current_user: UserIdentity = Depends(get_current_user),
) -> BundleResponse:
    """Initialise a new shipment bundle, scoped to the user's brokerage tenant."""
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
        "tenant_id": current_user.tenant_id,
        "created_by": current_user.email,
    }

    await firestore.create_bundle(bundle_data)

    await audit.record({
        "bundle_id": bundle_id,
        "iteration": 0,
        "audit_event_type": "BUNDLE_CREATED",
        "audit_payload": {
            "reference": body.reference,
            "destination_country": body.destination_country.upper(),
            "tenant_id": current_user.tenant_id,
            "created_by": current_user.email,
        },
        "actor": f"cha:{current_user.email}",
    })

    return BundleResponse(
        id=bundle_id,
        reference=body.reference,
        destination_country=body.destination_country.upper(),
        status="PENDING",
        current_iteration=0,
        documents=[],
        created_at=now,
        tenant_id=current_user.tenant_id,
        created_by=current_user.email,
    )


@router.get(
    "/bundles",
    response_model=list[BundleResponse],
    summary="List recent trade assessment bundles",
)
async def list_bundles(
    limit: int = Query(default=30, ge=1, le=100),
    current_user: UserIdentity = Depends(get_current_user),
) -> list[BundleResponse]:
    """Retrieve recent bundles scoped to the authenticated tenant."""
    bundles = await firestore.list_bundles(tenant_id=current_user.tenant_id, limit=limit)
    return [
        BundleResponse(
            id=b["id"],
            reference=b.get("reference"),
            destination_country=b.get("destination_country", "SG"),
            status=b.get("status", "PENDING"),
            current_iteration=b.get("current_iteration", 0),
            documents=b.get("documents", []),
            created_at=b.get("created_at", ""),
            tenant_id=b.get("tenant_id") or current_user.tenant_id,
            created_by=b.get("created_by") or current_user.email,
        )
        for b in bundles
    ]


@router.get(
    "/bundles/{bundle_id}",
    response_model=BundleResponse,
    summary="Get bundle details and attached documents",
)
async def get_bundle(
    bundle_id: str,
    current_user: UserIdentity = Depends(get_current_user),
) -> BundleResponse:
    """Retrieve an existing bundle with multi-tenant domain authorization."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    # Multi-tenant scoping: if bundle has tenant_id and user is in a different tenant
    bundle_tenant = bundle.get("tenant_id")
    if bundle_tenant and bundle_tenant != current_user.tenant_id and current_user.tenant_id != "*":
        raise ForbiddenError(
            f"Access denied: Bundle belongs to organization '{bundle_tenant}'.",
            detail={"bundle_tenant": bundle_tenant, "user_tenant": current_user.tenant_id},
        )

    return BundleResponse(
        id=bundle["id"],
        reference=bundle.get("reference"),
        destination_country=bundle.get("destination_country", "SG"),
        status=bundle.get("status", "PENDING"),
        current_iteration=bundle.get("current_iteration", 0),
        documents=bundle.get("documents", []),
        created_at=bundle.get("created_at", ""),
        tenant_id=bundle_tenant or current_user.tenant_id,
        created_by=bundle.get("created_by") or current_user.email,
    )

@router.get(
    "/bundles/{bundle_id}/status",
    summary="Get current run status and pipeline stage",
)
async def get_bundle_status(
    bundle_id: str,
    current_user: UserIdentity = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve current pipeline execution status and stage for a bundle."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    bundle_tenant = bundle.get("tenant_id")
    if bundle_tenant and bundle_tenant != current_user.tenant_id and current_user.tenant_id != "*":
        raise ForbiddenError(
            f"Access denied: Bundle belongs to organization '{bundle_tenant}'.",
            detail={"bundle_tenant": bundle_tenant, "user_tenant": current_user.tenant_id},
        )

    return await firestore.get_run_state(bundle_id)



@router.get(
    "/bundles/{bundle_id}/audit",
    summary="Get cryptographic tamper-evident audit trail",
)
async def get_audit(bundle_id: str) -> dict[str, Any]:
    """Retrieve audit events and cryptographic chain verification result."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    events = await audit.list_audit_events(bundle_id)
    verified, error_reason = audit.verify_audit_chain(events)

    return {
        "events": events,
        "verified": verified,
        "error": error_reason,
        "signature": await signing.summarize(events, bundle_id),
    }


@router.post(
    "/bundles/{bundle_id}/audit/sign",
    summary="Sign the current head of the audit chain now",
)
async def sign_audit_head(bundle_id: str) -> dict[str, Any]:
    """Signs the newest event (when a run could not, or after corrections made since): returns the signature summary.
    409 when signing is not configured. Signing a head that is already signed changes nothing."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})
    if signing.get_signer() is None:
        raise ConflictError("Audit signing is not configured for this service.", detail={"bundle_id": bundle_id})
    events = await audit.list_audit_events(bundle_id)
    verified, error_reason = audit.verify_audit_chain(events)
    if not verified:
        raise ConflictError("The audit chain does not verify, so its head is not signed.", detail={"error": error_reason})
    latest = await firestore.latest_iteration(bundle_id)
    await signing.sign_head(bundle_id, iteration=int(latest["iteration"]) if latest else 0)
    return await signing.summarize(await audit.list_audit_events(bundle_id), bundle_id)


@router.get(
    "/bundles/{bundle_id}/extractions",
    summary="Get document extractions with spatial bounding boxes, as that assessment's checks saw them",
)
async def get_extractions(
    bundle_id: str,
    iteration: int | None = Query(default=None, description="Optional iteration number"),
) -> list[dict[str, Any]]:
    """Retrieve extraction JSON snapshots for spatial provenance overlays.

    What the model read, with the corrections that iteration used laid on: a corrected field carries ``corrected: true`` and
    ``original_value``. The stored record itself is never changed.
    """
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})

    return await corrections.effective_extraction(bundle_id, iteration=iteration)
