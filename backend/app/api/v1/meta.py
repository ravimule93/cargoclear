from typing import Any
from fastapi import APIRouter, Depends

from app.core.config import settings
from app.domain.auth import UserIdentity
from app.gateway.auth import get_optional_user

router = APIRouter(tags=["meta"])


@router.get(
    "/meta",
    summary="Get system metadata, auth state, and application mode",
)
async def get_meta(
    current_user: UserIdentity | None = Depends(get_optional_user),
) -> dict[str, Any]:

    """Returns current app_mode ('demo' or 'live'), auth settings, and active user context."""
    is_live = settings.app_mode == "live"
    res: dict[str, Any] = {
        "app_mode": settings.app_mode,
        "data_source_policy": "live" if is_live else "fixture_with_offline_fallbacks",
        "pipeline_engine": settings.pipeline_engine,
    }
    if settings.auth_enabled:
        res["auth"] = {
            "enabled": True,
            "oauth_client_id": settings.oauth_client_id,
            "oauth_issuer": settings.oauth_issuer,
            "allowed_email_domains": settings.allowed_domains_list,
        }
        res["user"] = current_user.model_dump() if current_user else None
    return res



