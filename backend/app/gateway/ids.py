"""Path-parameter ids: every bundle_id / document_id in a URL must look like an id.

The local demo storage builds file paths from them, and Firestore document paths too, so ``..`` or a 3000-character
string must never get that far. An id that does not look like one answers the same 404 an unknown id does.
"""

from __future__ import annotations

import re

from fastapi import Request

from app.gateway.errors import NotFoundError

ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
CORRECTION_ID_PATTERN = re.compile(r"cor-[0-9]{1,10}")
RUN_ID_PATTERN = re.compile(r"run-[0-9a-f]{12}")

_ECHO_LIMIT = 64


def _echo(value: str) -> str:
    """At most 64 printable characters of ``value``: what a 404 message may repeat of a hostile id."""
    return "".join(ch if ch.isprintable() else "?" for ch in value[:_ECHO_LIMIT])


def validate_path_ids(request: Request) -> None:
    """App-wide dependency: 404 unless ``bundle_id``, ``document_id``, ``correction_id`` and ``run_id`` (whichever the route has) look like ids."""
    bundle_id = request.path_params.get("bundle_id")
    if bundle_id is not None and not ID_PATTERN.fullmatch(bundle_id):
        shown = _echo(bundle_id)
        raise NotFoundError(f"Bundle '{shown}' not found.", detail={"bundle_id": shown})

    document_id = request.path_params.get("document_id")
    if document_id is not None and not ID_PATTERN.fullmatch(document_id):
        shown_bundle, shown_document = _echo(bundle_id or ""), _echo(document_id)
        raise NotFoundError(
            f"Document '{shown_document}' not found in bundle '{shown_bundle}'.",
            detail={"bundle_id": shown_bundle, "document_id": shown_document},
        )

    correction_id = request.path_params.get("correction_id")
    if correction_id is not None and not CORRECTION_ID_PATTERN.fullmatch(correction_id):
        shown = _echo(correction_id)
        raise NotFoundError(f"'{shown}' is not a correction in force for this bundle.", detail={"correction_id": shown})

    run_id = request.path_params.get("run_id")
    if run_id is not None and not RUN_ID_PATTERN.fullmatch(run_id):
        shown = _echo(run_id)
        raise NotFoundError(f"Run '{shown}' not found.", detail={"run_id": shown})
