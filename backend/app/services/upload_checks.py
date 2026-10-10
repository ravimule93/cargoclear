"""Checks on an uploaded file and its name, and the headers a download carries.

Pure functions (``pdf_page_count`` shells out to poppler's ``pdfinfo``; it is the one blocking call, so callers run
``check_pdf`` in a worker thread).
"""

from __future__ import annotations

import os
import re
import unicodedata
from urllib.parse import quote

import structlog

from app.gateway.errors import ValidationError

logger = structlog.get_logger(__name__)

_HEADER_WINDOW = 1024
_MAX_NAME_CHARS = 150
_MAX_EXTENSION_CHARS = 16
_FALLBACK_NAME = "document.pdf"
_PDFINFO_TIMEOUT_SECONDS = 15


# ---------------------------------------------------------------------------
# content
# ---------------------------------------------------------------------------


def check_pdf_header(data: bytes) -> None:
    """The file must carry ``%PDF-`` within its first 1024 bytes."""
    if b"%PDF-" not in data[:_HEADER_WINDOW]:
        raise ValidationError("The file is not a PDF.")


def check_not_encrypted(data: bytes) -> None:
    """Refuse a PDF with an /Encrypt dictionary: nobody here has the password, so it can never be read."""
    if b"/Encrypt" in data:
        raise ValidationError("Password-protected PDFs are not supported.")


def pdf_page_count(data: bytes) -> int | None:
    """Number of pages according to poppler, or None when it cannot be told (no poppler, or a PDF it cannot parse)."""
    try:
        from pdf2image import pdfinfo_from_bytes

        return int(pdfinfo_from_bytes(data, timeout=_PDFINFO_TIMEOUT_SECONDS)["Pages"])
    except Exception as exc:  # noqa: BLE001 - poppler missing, a broken PDF, a timeout: the check is skipped
        logger.info("pdf_page_count_skipped", reason=type(exc).__name__)
        return None


def check_page_limit(pages: int | None, limit: int) -> None:
    if pages is not None and pages > limit:
        raise ValidationError(f"The document has {pages} pages; the limit is {limit}.")


def check_pdf(data: bytes, max_pages: int) -> None:
    """All content checks, in order: header, encryption, page count (the last is skipped without poppler)."""
    check_pdf_header(data)
    check_not_encrypted(data)
    check_page_limit(pdf_page_count(data), max_pages)


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------


def sanitize_filename(name: str | None) -> str:
    """A file name that is safe to store, audit and put in a header.

    The last path component (both ``/`` and ``\\``); control and format characters (CR/LF, NUL, bidi overrides,
    zero-width) and quotes dropped; whitespace collapsed; cut to 150 characters keeping the extension; ``document.pdf``
    if nothing usable is left (empty, or only dots). Non-ASCII names are kept.
    """
    if not name:
        return _FALLBACK_NAME
    last = re.split(r"[\\/]", name)[-1]
    kept = "".join(ch for ch in last if unicodedata.category(ch) not in ("Cc", "Cf") and ch not in "\"'")
    cleaned = " ".join(kept.split())
    if not cleaned.strip("."):
        return _FALLBACK_NAME
    if len(cleaned) > _MAX_NAME_CHARS:
        stem, extension = os.path.splitext(cleaned)
        if 0 < len(extension) <= _MAX_EXTENSION_CHARS:
            cleaned = stem[: _MAX_NAME_CHARS - len(extension)] + extension
        else:
            cleaned = cleaned[:_MAX_NAME_CHARS]
    return cleaned


# ---------------------------------------------------------------------------
# download headers
# ---------------------------------------------------------------------------


def content_disposition(filename: str) -> str:
    """``inline; filename="<ascii>"; filename*=UTF-8''<percent-encoded>`` for any stored name, hostile or not.

    The ASCII fallback replaces every non-ASCII, control, quote, backslash and percent character with ``_``; the
    UTF-8 form carries the real name. Both parts are plain ASCII, which is what a header value must be.
    """
    fallback = "".join(ch if 0x20 <= ord(ch) < 0x7F and ch not in '"\\%' else "_" for ch in filename)
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def download_headers(filename: str) -> dict[str, str]:
    """Headers for serving a stored PDF: a safe Content-Disposition, private caching, no MIME sniffing."""
    return {
        "Content-Disposition": content_disposition(filename),
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    }
