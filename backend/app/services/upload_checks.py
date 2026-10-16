"""Checks on an uploaded file and its name, and the headers a download carries.

Pure functions, except ``read_pdf_facts`` and ``embedded_file_count``, which shell out to poppler (``pdfinfo``, ``pdfdetach``); they
are the blocking calls, so callers run ``check_pdf`` in a worker thread.

What ``check_pdf`` refuses, and why it is poppler's answer and not a search through the bytes: a file poppler cannot read at all
(truncated, a zip behind a ``%PDF-`` line: nothing downstream could render it, and the model must never be handed it raw), one that
needs a password to open, one with more pages than ``max_pages``, one with a page too large to render safely, one with a script,
and one with an embedded file. A PDF that only restricts copying or printing opens without a password and is accepted. Only when
poppler is not installed at all are these checks skipped (a development machine); the container image carries it.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import re
import subprocess
import tempfile
import unicodedata
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from urllib.parse import quote

import structlog

from app.gateway.errors import ValidationError
from app.services.preprocess import TARGET_DPI

logger = structlog.get_logger(__name__)

_HEADER_WINDOW = 1024
_MAX_NAME_CHARS = 150
_MAX_EXTENSION_CHARS = 16
_FALLBACK_NAME = "document.pdf"
_PDFINFO_TIMEOUT_SECONDS = 15
_POINTS_PER_INCH = 72
_PAGE_SIZE_KEY = re.compile(r"Page\s*(\d*)\s*size")
_PAGE_SIZE_VALUE = re.compile(r"([\d.]+)\s*x\s*([\d.]+)\s*pts")
_EMBEDDED_FILES = re.compile(r"\s*(\d+) embedded files?")


# ---------------------------------------------------------------------------
# content
# ---------------------------------------------------------------------------


def check_pdf_header(data: bytes) -> None:
    """The file must carry ``%PDF-`` within its first 1024 bytes."""
    if b"%PDF-" not in data[:_HEADER_WINDOW]:
        raise ValidationError("The file is not a PDF.")


# The file on disk that the poppler tools of ONE request share: (the bytes it holds, its path). See ``shared_pdf``.
_SHARED: contextvars.ContextVar[tuple[bytes, str] | None] = contextvars.ContextVar("shared_pdf", default=None)


@contextmanager
def shared_pdf(data: bytes) -> Iterator[str]:
    """Write ``data`` to ONE temporary file for everything in the block that needs the file on disk (``pdfdetach``, ``pdftotext`` and the
    page renders of the relevance gate and of preprocessing: ``pdf_on_disk``), instead of one copy of up to MAX_UPLOAD_MB for each.
    The block's context (and a ``asyncio.to_thread`` call made in it) sees it; a task started in it with its own context does not."""
    with _write_temp(data) as handle:
        token = _SHARED.set((data, handle.name))
        try:
            yield handle.name
        finally:
            _SHARED.reset(token)


@asynccontextmanager
async def shared_pdf_async(data: bytes) -> AsyncIterator[str]:
    """``shared_pdf`` for the event loop: the (up to MAX_UPLOAD_MB) write happens in a worker thread, and the file is shared with the
    code in this context, including the threads it starts."""
    handle = await asyncio.to_thread(_write_temp, data)
    token = _SHARED.set((data, handle.name))
    try:
        yield handle.name
    finally:
        _SHARED.reset(token)
        await asyncio.to_thread(handle.close)  # closing deletes the file


def _write_temp(data: bytes) -> "tempfile._TemporaryFileWrapper[bytes]":
    handle = tempfile.NamedTemporaryFile(suffix=".pdf")  # noqa: SIM115 - closed by the caller, after the block that uses it
    handle.write(data)
    handle.flush()
    return handle


@contextmanager
def pdf_on_disk(data: bytes) -> Iterator[str]:
    """The path of a file that holds ``data``: the one ``shared_pdf`` wrote when this is inside its block and the bytes are the same
    object, else a temporary file of its own that goes away at the end of the block."""
    shared = _SHARED.get()
    if shared is not None and shared[0] is data:
        yield shared[1]
        return
    with _write_temp(data) as handle:
        yield handle.name


class PdfUnreadable(Exception):
    """poppler ran and could not open the file. ``password``: it needs one; ``timed_out``: poppler did not answer in time."""

    def __init__(self, *, password: bool = False, timed_out: bool = False) -> None:
        super().__init__("password" if password else "timeout" if timed_out else "unreadable")
        self.password = password
        self.timed_out = timed_out


@dataclass(frozen=True)
class PdfFacts:
    """What ``pdfinfo`` says about a file: the page count, whether it carries JavaScript, and the size in points of each page it
    was asked about (the first ``max_pages``), as (page number, width, height)."""

    pages: int
    javascript: bool
    page_sizes: tuple[tuple[int, float, float], ...]


def read_pdf_facts(data: bytes, max_pages: int) -> PdfFacts | None:
    """The facts poppler's ``pdfinfo`` reports about ``data``, or None when poppler is not installed (the checks that need it are
    then skipped). Raises ``PdfUnreadable`` when poppler is there and cannot open the file."""
    try:
        from pdf2image import pdfinfo_from_bytes
        from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPopplerTimeoutError
    except ImportError:
        logger.info("pdf_checks_skipped", reason="pdf2image_not_installed")
        return None
    try:
        info = pdfinfo_from_bytes(data, timeout=_PDFINFO_TIMEOUT_SECONDS, first_page=1, last_page=max(1, max_pages))
        pages = int(info["Pages"])
    except PDFInfoNotInstalledError:
        logger.info("pdf_checks_skipped", reason="poppler_not_installed")
        return None
    except Exception as exc:  # noqa: BLE001 - whatever poppler or its wrapper raised, the file could not be read
        logger.info("pdf_unreadable", reason=type(exc).__name__)
        raise PdfUnreadable(
            password="Incorrect password" in str(exc), timed_out=isinstance(exc, PDFPopplerTimeoutError)
        ) from exc
    sizes = []
    for key, value in info.items():
        named, measured = _PAGE_SIZE_KEY.fullmatch(str(key)), _PAGE_SIZE_VALUE.match(str(value))
        if named and measured:
            sizes.append((int(named.group(1) or 1), float(measured.group(1)), float(measured.group(2))))
    return PdfFacts(pages=pages, javascript=str(info.get("JavaScript", "no")).lower().startswith("yes"), page_sizes=tuple(sorted(sizes)))


def embedded_file_count(data: bytes) -> int | None:
    """The number of attachments and embedded files according to poppler's ``pdfdetach``, or None when it is not installed.
    Raises ``PdfUnreadable`` when it cannot answer."""
    with pdf_on_disk(data) as path:
        try:
            done = subprocess.run(
                ["pdfdetach", "-list", path], capture_output=True, text=True, timeout=_PDFINFO_TIMEOUT_SECONDS, check=False
            )
        except FileNotFoundError:
            logger.info("pdf_checks_skipped", reason="pdfdetach_not_installed")
            return None
        except subprocess.TimeoutExpired as exc:
            raise PdfUnreadable(timed_out=True) from exc
    found = _EMBEDDED_FILES.match(done.stdout)
    if found is None:
        raise PdfUnreadable()
    return int(found.group(1))


def check_page_limit(pages: int | None, limit: int) -> None:
    if pages is not None and pages > limit:
        raise ValidationError(f"The document has {pages} pages; the limit is {limit}.")


def check_page_sizes(sizes: tuple[tuple[int, float, float], ...], max_megapixels: float, dpi: int = TARGET_DPI) -> None:
    """Refuse a page whose render at ``dpi`` would exceed ``max_megapixels``: a page the size of a billboard is a few kilobytes of PDF
    and gigabytes of pixels (decompression-bomb style), and it is rendered before anything else looks at it."""
    for page, width, height in sizes:
        megapixels = (width / _POINTS_PER_INCH * dpi) * (height / _POINTS_PER_INCH * dpi) / 1_000_000
        if megapixels > max_megapixels:
            raise ValidationError(
                f"Page {page} is {width:.0f} x {height:.0f} points, {megapixels:.0f} megapixels when read at {dpi} DPI; "
                f"the limit is {max_megapixels:g}.",
                detail={"page": page, "megapixels": round(megapixels), "max_megapixels": max_megapixels},
            )


def _unreadable(failure: PdfUnreadable) -> ValidationError:
    if failure.password:
        return ValidationError("Password-protected PDFs are not supported.")
    if failure.timed_out:
        return ValidationError("The file took too long to check; it may be damaged.")
    return ValidationError("The file could not be read as a PDF.")


def check_pdf(data: bytes, max_pages: int, max_page_megapixels: float | None = None) -> None:
    """All content checks, in order: header, then what poppler says (readable, page count, page sizes, scripts, attachments).

    ``max_page_megapixels`` defaults to ``MAX_PAGE_MEGAPIXELS``. Without poppler everything after the header is skipped.
    """
    from app.core.config import settings

    check_pdf_header(data)
    try:
        facts = read_pdf_facts(data, max_pages)
        if facts is None:
            return
        check_page_limit(facts.pages, max_pages)
        check_page_sizes(facts.page_sizes, settings.max_page_megapixels if max_page_megapixels is None else max_page_megapixels)
        if facts.javascript:
            raise ValidationError("The PDF contains scripts, which are not accepted.")
        attachments = embedded_file_count(data)
    except PdfUnreadable as failure:
        raise _unreadable(failure) from failure
    if attachments:
        raise ValidationError("The PDF contains attached or embedded files, which are not accepted.")


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
