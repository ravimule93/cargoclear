"""Meta router — GET /meta returning environment and application mode metadata."""

from typing import Any
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["meta"])


@router.get(
    "/meta",
    summary="Get system metadata and application mode",
)
async def get_meta() -> dict[str, Any]:
    """Returns current app_mode ('demo' or 'live') and data source policy."""
    is_live = settings.app_mode == "live"
    return {
        "app_mode": settings.app_mode,
        "data_source_policy": "live" if is_live else "fixture_with_offline_fallbacks",
    }
