"""Declaration pre-fill router: the values of an assessment, laid out for the person who keys the declaration.

Read-only. Nothing is recorded in the audit chain for a download (a GET must not change state, and with no user
authentication "who downloaded it" would be the literal "user"); the pack carries the audit head it was made at, so a reader can
see whether the trail has moved since.
"""

import asyncio

from fastapi import APIRouter, Depends, Path, Query, Response

from app.domain.prefill import PrefillPack
from app.gateway.authorization import require_authorized_bundle
from app.services import prefill, prefill_pdf

router = APIRouter(tags=["prefill"], dependencies=[Depends(require_authorized_bundle)])


def _filename(pack: PrefillPack, extension: str) -> str:
    return f"cargoclear-prefill-{pack.bundle_id}-assessment{pack.assessment.iteration}.{extension}"


@router.get(
    "/bundles/{bundle_id}/prefill",
    response_model=PrefillPack,
    summary="Declaration pre-fill pack (JSON)",
)
async def get_prefill(
    response: Response,
    bundle_id: str = Path(..., description="Target bundle ID"),
    iteration: int | None = Query(default=None, ge=1, description="Assessment number; the latest when omitted"),
    download: bool = Query(default=False, description="Send as a file download"),
) -> PrefillPack:
    """CargoClear's documented pre-fill JSON (docs/PREFILL_PACK.md): the values the documents state, where each came from, what
    the other documents say, what needs a person's eyes, and what the declarant must supply. Not a government format."""
    pack = await prefill.build(bundle_id, iteration)
    if download:
        response.headers["Content-Disposition"] = f'attachment; filename="{_filename(pack, "json")}"'
    return pack


@router.get(
    "/bundles/{bundle_id}/prefill.pdf",
    summary="Declaration pre-fill summary (PDF)",
    response_class=Response,
)
async def get_prefill_pdf(
    bundle_id: str = Path(..., description="Target bundle ID"),
    iteration: int | None = Query(default=None, ge=1, description="Assessment number; the latest when omitted"),
) -> Response:
    """The same pack as a printable A4 summary, verdict first."""
    pack = await prefill.build(bundle_id, iteration)
    pdf = await asyncio.to_thread(prefill_pdf.render, pack)  # layout is CPU work: off the event loop
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename(pack, "pdf")}"'},
    )
