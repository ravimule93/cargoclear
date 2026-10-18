"""Authorization dependencies for resources that belong to a tenant."""

from __future__ import annotations

from typing import Any

from fastapi import Depends

from app.core.config import settings
from app.domain.auth import UserIdentity
from app.gateway.auth import get_current_user
from app.gateway.errors import NotFoundError
from app.repo import firestore


async def get_authorized_bundle(
    bundle_id: str,
    current_user: UserIdentity = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a bundle only when it belongs to the authenticated tenant."""
    bundle = await firestore.get_bundle(bundle_id)
    if bundle is None:
        raise NotFoundError(f"Bundle '{bundle_id}' not found.", detail={"bundle_id": bundle_id})
    tenant_id = bundle.get("tenant_id")
    if tenant_id is None:
        if settings.app_mode == "live":
            raise NotFoundError("Bundle not found.", detail={"bundle_id": bundle_id})
        return bundle
    if tenant_id != current_user.tenant_id and current_user.tenant_id != "*":
        raise NotFoundError("Bundle not found.", detail={"bundle_id": bundle_id})
    return bundle


async def require_authorized_bundle(
    bundle: dict[str, Any] = Depends(get_authorized_bundle),
) -> None:
    """Dependency form for routes that do not need the bundle object."""
    del bundle
