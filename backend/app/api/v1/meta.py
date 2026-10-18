from typing import Any
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core import mode
from app.core.config import settings
from app.domain.auth import UserIdentity
from app.gateway.auth import get_optional_user
from app.gateway.errors import UpstreamError

router = APIRouter(tags=["meta"])


class SetModeRequest(BaseModel):
    mode: str = Field(..., description="Target execution mode ('demo' or 'live')")


@router.get(
    "/meta",
    summary="Get system metadata, auth state, and application mode",
)
async def get_meta(
    request: Request,
    current_user: UserIdentity | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """Returns current app_mode ('demo' or 'live'), auth settings, and active user context."""
    res: dict[str, Any] = {
        "app_mode": settings.app_mode,
        "data_source_policy": "live" if settings.app_mode == "live" else "fixture_with_offline_fallbacks",
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


@router.get(
    "/mode",
    summary="Get active execution mode, provider details, and AI health status",
)
async def get_mode(request: Request) -> dict[str, Any]:
    """Returns detailed status about runtime execution mode and Vertex AI connectivity."""
    header_mode = request.headers.get(mode.EXECUTION_MODE_HEADER)
    cookie_mode = request.cookies.get(mode.EXECUTION_MODE_COOKIE)
    active_mode = mode.resolve_execution_mode(header_val=header_mode, cookie_val=cookie_mode)
    return mode.get_mode_status(active_mode)


@router.post(
    "/mode",
    summary="Switch execution mode at runtime ('demo' or 'live')",
)
async def set_mode(
    payload: SetModeRequest,
    response: Response,
    _current_user: UserIdentity | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """Switches the active execution mode for the current session without server restart."""
    target_mode = mode.resolve_execution_mode(requested=payload.mode)

    if target_mode == "live":
        source = mode.credential_source()
        if source is None:
            raise UpstreamError(
                f"Cannot activate Live AI Mode: {mode.no_credentials_message()}",
                detail={
                    "requested_mode": "live",
                    "reason": "Missing GCP credentials",
                    "provider": "Google Cloud Vertex AI",
                    "model": settings.gemini_live_model,
                },
            )

    response.set_cookie(
        key=mode.EXECUTION_MODE_COOKIE,
        value=target_mode,
        max_age=31536000,
        httponly=False,
        samesite="lax",
    )

    return mode.get_mode_status(target_mode)




