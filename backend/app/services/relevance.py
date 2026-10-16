"""What a PDF says it is, and which of its pages are read, before the model is asked anything expensive.

Two decisions, both about the TEXT LAYER first (poppler's ``pdftotext``, already in the container image) and the model last:

  * the relevance gate (``check_document``, called by the upload route): the first page must be a document the assessment reads (a
    commercial invoice, bill of lading, packing list, mill test certificate, certificate of origin or phytosanitary certificate).
    A title phrase or several field words on the page say so for free. When the text cannot say (no text layer: a scan; or text in
    a language the lists do not hold) ONE small vision request decides: page 1 at 100 DPI, a fixed list of answers, 24 output tokens.
    Only a definite "OTHER" refuses the file. No model (demo mode), or the request failing, accepts it: the gate narrows what reaches
    the expensive call, it is not a reason to turn a person away during an outage.
  * the page plan (``plan_pages``, used by preprocessing): page 1, then the pages that look like part of the document, at most
    ``MAX_PAGES_SENT`` of them. Pages of terms and conditions are skipped; content-looking pages beyond the cap are NOT read, and the
    plan records them so that the assessment can say so (services/page_coverage.py).

The text layer is used to DECIDE, never to answer: it is not put in a prompt (a white-on-white sentence lives in the text layer and
not in the pixels the model is shown; docs/input-gating-audit.md, F6a). The vision request sends a rendered image and a fixed sentence.
"""

from __future__ import annotations

import asyncio
import html
import io
import json
import random
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, get_args

import structlog

from app.core.config import settings
from app.domain.schemas import DocType
from app.gateway.errors import ValidationError
from app.services import token_budget, token_usage, upload_checks

logger = structlog.get_logger(__name__)

_PDFTOTEXT_TIMEOUT_SECONDS = 15
_GATE_TIMEOUT_SECONDS = 30
_GATE_ATTEMPTS = 2           # one retry, for the transient failures the extraction call also retries (429 under shared quota, 5xx)
_RETRY_DELAY_SECONDS = 1.0
_sleep = asyncio.sleep       # seam: tests replace it so that a retry never really waits
GATE_DPI = 100
GATE_MAX_OUTPUT_TOKENS = 24
KINDS = tuple(kind for kind in get_args(DocType) if kind != "UNKNOWN") + ("OTHER",)
GATE_INSTRUCTION = "Which kind of shipping document is the page? Answer with one word from the list. OTHER if it is none of them."
REJECTION_MESSAGE = (
    "This file does not look like a document the assessment reads: a commercial invoice, bill of lading, packing list, "
    "mill test certificate, certificate of origin or phytosanitary certificate."
)

# A title phrase names the type by itself; otherwise WEAK_NEEDED field words of one type do. Lowercase. A language that is not here is
# not rejected for it: its first page goes to the vision request.
STRONG = {
    "COMMERCIAL_INVOICE": ("commercial invoice", "商业发票"),
    "BILL_OF_LADING": ("bill of lading", "提单"),
    "PACKING_LIST": ("packing list", "装箱单"),
    "MILL_TEST_CERTIFICATE": ("mill test certificate", "test certificate", "质量证明书"),
    "CERTIFICATE_OF_ORIGIN": ("certificate of origin", "原产地证"),
    "PHYTOSANITARY": ("phytosanitary certificate",),
}
WEAK = {
    "COMMERCIAL_INVOICE": ("invoice no", "unit price", "total value", "incoterm", "country of origin", "consignee"),
    "BILL_OF_LADING": ("vessel", "port of loading", "port of discharge", "shipper", "freight", "gross weight"),
    "PACKING_LIST": ("packages", "net weight", "gross weight", "marks"),
    "MILL_TEST_CERTIFICATE": ("heat no", "chemical composition", "yield strength", "tensile", "specification"),
}
WEAK_NEEDED = 3
MIN_TEXT_CHARS = 40   # fewer characters than this on a page: it has no text layer (a scan)
# A page after the first is part of the document when it has a table's worth of numbers in its lines (the first token of a line, where
# clause and row numbers sit, is not counted: the terms fixture's "3.12" clauses read as data until it was), or names the document.
KEEP_PAGE_NUMBERS = 25
WEAK_NEEDED_FOR_A_PAGE = 2


# ---------------------------------------------------------------------------
# the text layer
# ---------------------------------------------------------------------------


def _pdftotext(data: bytes, options: list[str]) -> "subprocess.CompletedProcess[bytes] | None":
    """poppler's ``pdftotext`` with ``options`` over ``data`` (the request's shared file when there is one), or None when it is not
    installed or timed out."""
    with upload_checks.pdf_on_disk(data) as path:
        try:
            return subprocess.run(
                ["pdftotext", *options, path, "-"], capture_output=True, timeout=_PDFTOTEXT_TIMEOUT_SECONDS, check=False
            )
        except FileNotFoundError:
            logger.info("pdf_text_unavailable", reason="pdftotext_not_installed")
        except subprocess.TimeoutExpired:
            logger.info("pdf_text_unavailable", reason="timeout")
    return None


def read_page_texts(data: bytes, last_page: int) -> list[str] | None:
    """The text of pages 1..``last_page`` (one string per page) by poppler's ``pdftotext``, or None when it cannot be had (not
    installed, timed out, or the file will not give its text: a PDF that forbids copying answers with nothing). A page with no text
    layer is an empty string."""
    done = _pdftotext(data, ["-layout", "-f", "1", "-l", str(max(1, last_page))])
    if done is None:
        return None
    text = done.stdout.decode("utf-8", "replace")
    if not text.strip() and done.returncode != 0:
        logger.info("pdf_text_unavailable", reason="no_text_returned")
        return None
    pages = text.split("\f")
    if pages and pages[-1] == "":
        pages.pop()  # pdftotext ends every page with a form feed
    return pages


def _normalised(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def names_a_document(text: str) -> str | None:
    """The document type a page's text names (a title phrase, or WEAK_NEEDED of its field words), or None."""
    page = _normalised(text)
    for doc_type, phrases in STRONG.items():
        if any(phrase in page for phrase in phrases):
            return doc_type
    for doc_type, words in WEAK.items():
        if sum(1 for word in words if word in page) >= WEAK_NEEDED:
            return doc_type
    return None


def first_page_verdict(text: str) -> tuple[str, str]:
    """("accept", why) when the first page's text names a document the assessment reads, else ("vision", why): the text cannot say."""
    named = names_a_document(text)
    if named is not None:
        return "accept", f"the text names {named}"
    if len(_normalised(text)) < MIN_TEXT_CHARS:
        return "vision", "the first page has no text layer"
    return "vision", "the first page's text names no document in the lists"


# The text layer is written by whoever made the file: white-on-white or a one-point "Commercial Invoice" costs an attacker nothing. So the
# words that make the gate accept a file must be words a reader could see on the first page: tall enough, and drawn in a colour that differs
# from what is behind them.
MIN_WORD_POINTS = 4.0   # a word shorter than this (page points, 72 to the inch) cannot be read
MIN_CONTRAST = 40       # the spread of grey levels (0-255) inside a word's box on the rendered page
_BBOX_WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', re.DOTALL)


def visible_first_page_text(data: bytes) -> str | None:
    """The words of page 1, in order, that can be seen when the page is rendered (``MIN_WORD_POINTS``, ``MIN_CONTRAST``); None when that
    cannot be worked out (no pdftotext, no render). The boxes come from ``pdftotext -bbox`` and are looked up on the page at ``GATE_DPI``.
    A page turned by /Rotate whose boxes do not land on the render reads as unseen, which only sends the file to the vision request."""
    done = _pdftotext(data, ["-bbox", "-f", "1", "-l", "1"])
    if done is None:
        return None
    try:
        image = _first_page_image(data)
    except Exception:  # noqa: BLE001 - no render: the text cannot be checked against the page
        return None
    scale = GATE_DPI / 72
    seen: list[str] = []
    for x0, y0, x1, y1, word in _BBOX_WORD.findall(done.stdout.decode("utf-8", "replace")):
        left, top, right, bottom = (float(v) * scale for v in (x0, y0, x1, y1))
        if (float(y1) - float(y0)) < MIN_WORD_POINTS:
            continue
        box = (max(0, int(left) - 1), max(0, int(top) - 1), min(image.width, int(right) + 2), min(image.height, int(bottom) + 2))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        low, high = image.crop(box).getextrema()
        if high - low >= MIN_CONTRAST:
            seen.append(html.unescape(word))
    return " ".join(seen)


# ---------------------------------------------------------------------------
# the page plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PagePlan:
    """Which source pages (1-based) are read. ``boilerplate``: skipped, they look like terms and conditions. ``over_cap``: they look
    like part of the document and are NOT read because the cap was reached. ``basis``: "text_layer", or "no_text_layer" when the
    file gave no text (a scan, or a file that forbids copying) and the first pages were taken."""

    total: int
    kept: tuple[int, ...]
    boilerplate: tuple[int, ...]
    over_cap: tuple[int, ...]
    basis: str

    def as_dict(self) -> dict[str, Any]:
        return {"total": self.total, "kept": list(self.kept), "boilerplate": list(self.boilerplate),
                "over_cap": list(self.over_cap), "basis": self.basis}


def _looks_like_content(text: str) -> bool:
    page = _normalised(text)
    if len(page) < MIN_TEXT_CHARS:
        return True  # no text layer: a scanned page, which cannot be judged, is kept
    numbers = sum(len(re.findall(r"\d[\d.,]*", " ".join(line.split()[1:]))) for line in text.splitlines())
    if numbers >= KEEP_PAGE_NUMBERS or names_a_document(text) is not None:
        return True
    return any(sum(1 for word in words if word in page) >= WEAK_NEEDED_FOR_A_PAGE for words in WEAK.values())


def plan_pages(total: int, texts: list[str] | None, cap: int) -> PagePlan:
    """The pages to read out of ``total``: page 1 always, then every page that looks like part of the document, the first ``cap`` of
    them. ``texts`` is ``read_page_texts``'s answer (None: no text to judge by)."""
    if texts is None or not any(_normalised(page) for page in texts):
        candidates = list(range(1, total + 1))
        boilerplate: list[int] = []
        basis = "no_text_layer"
    else:
        candidates, boilerplate = [], []
        for number in range(1, total + 1):
            text = texts[number - 1] if number - 1 < len(texts) else ""
            if number == 1 or _looks_like_content(text):
                candidates.append(number)
            else:
                boilerplate.append(number)
        basis = "text_layer"
    return PagePlan(total=total, kept=tuple(candidates[:cap]), boilerplate=tuple(boilerplate), over_cap=tuple(candidates[cap:]), basis=basis)


def page_ranges(pages: list[int] | tuple[int, ...]) -> str:
    """[2, 3, 4, 7] -> "2-4, 7"."""
    runs: list[list[int]] = []  # [first, last] of each run of consecutive pages
    for page in pages:
        if runs and page == runs[-1][1] + 1:
            runs[-1][1] = page
        else:
            runs.append([page, page])
    return ", ".join(str(first) if first == last else f"{first}-{last}" for first, last in runs)


# ---------------------------------------------------------------------------
# the relevance gate
# ---------------------------------------------------------------------------


def _first_page_image(data: bytes) -> Any:
    """Page 1 at GATE_DPI, grey (a PIL image)."""
    from pdf2image import convert_from_path

    with upload_checks.pdf_on_disk(data) as path:
        return convert_from_path(path, dpi=GATE_DPI, first_page=1, last_page=1, fmt="png")[0].convert("L")


def _first_page_png(data: bytes) -> bytes:
    out = io.BytesIO()
    _first_page_image(data).save(out, format="PNG")
    return out.getvalue()


def _is_transient(exc: BaseException) -> bool:
    """A failure worth one more try: the statuses the extraction call retries, a timeout, a dropped connection."""
    from app.agents import extraction

    return getattr(exc, "code", None) in extraction._RETRYABLE_STATUS or isinstance(exc, (TimeoutError, ConnectionError))


@dataclass
class GateResult:
    """The vision request's outcome: ``kind`` (one of ``KINDS``, or None when no answer could be had) and what the requests cost
    (``usage``: requests made, requests that reported nothing, and the tokens the API reported; services/token_usage.py)."""

    kind: str | None
    usage: dict[str, int] = field(default_factory=token_usage.empty_gate_usage)


async def ask_first_page(data: bytes) -> GateResult:
    """One small vision request: which kind of shipping document is page 1 (one of ``KINDS``), or kind None when no answer can be had
    (no model configured, the page cannot be rendered, the request failed or answered something else). Every request is counted."""
    from app.agents import extraction

    result = GateResult(kind=None)

    def count(response: Any) -> None:
        reported = token_usage.usage_of(response) if response is not None else None
        result.usage["requests"] += 1
        if reported is None:
            result.usage["unknown_requests"] += 1
            return
        for key, value in reported.items():
            result.usage[key] += value

    try:
        client = extraction._get_genai_client()
        if client is None:
            logger.info("relevance_gate_skipped", reason="no_model")
            return result
        from google.genai import types

        png = await asyncio.to_thread(_first_page_png, data)
        # as little thinking as the model allows; thinking tokens count toward the output cap, so a model that cannot go below a floor
        # (gemini-2.5-pro: 128) gets that much more room, or its answer would be cut off before the first word
        thinking = extraction.thinking_config(types, settings.gemini_live_model, minimal=True)
        room = int(getattr(thinking, "thinking_budget", None) or 0)
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={"type": "OBJECT", "properties": {"kind": {"type": "STRING", "enum": list(KINDS)}}, "required": ["kind"]},
            temperature=0.0, max_output_tokens=GATE_MAX_OUTPUT_TOKENS + room, thinking_config=thinking,
        )
        contents = [types.Part.from_bytes(data=png, mime_type="image/png"), types.Part.from_text(text=GATE_INSTRUCTION)]
        for attempt in range(1, _GATE_ATTEMPTS + 1):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(model=settings.gemini_live_model, contents=contents, config=config),
                    timeout=min(settings.gemini_timeout_seconds, _GATE_TIMEOUT_SECONDS),
                )
                count(response)
                break
            except Exception as exc:  # noqa: BLE001 - retried once when transient, else handled below
                count(None)  # the call failed: the API reported nothing for this request
                if attempt >= _GATE_ATTEMPTS or not _is_transient(exc):
                    raise
                logger.info("relevance_gate_retry", code=getattr(exc, "code", None), error_type=type(exc).__name__)
                await _sleep(_RETRY_DELAY_SECONDS * (0.5 + random.random()))  # noqa: S311 - jitter only
        kind = json.loads(response.text)["kind"]
    except Exception as exc:  # noqa: BLE001 - the gate never turns an outage into a refusal
        logger.warning(
            "relevance_gate_unavailable", error_type=type(exc).__name__, code=getattr(exc, "code", None),
            error_message=str(getattr(exc, "message", None) or "")[:200] or None,
        )
        return result
    result.kind = kind if kind in KINDS else None
    return result


async def classify_first_page(data: bytes) -> str | None:
    """``ask_first_page``'s kind alone."""
    return (await ask_first_page(data)).kind


async def check_document(data: bytes) -> GateResult | None:
    """Refuse (422) a file whose first page is not a document the assessment reads. Free when the text layer names one; otherwise one
    small vision request. Never raises for anything but a definite "OTHER". Returns the request's ``GateResult`` (what it cost) when
    the model was asked, None when it was not (the text named the document, or the gate is off)."""
    if not settings.relevance_gate:
        return None
    texts = await asyncio.to_thread(read_page_texts, data, 1)
    verdict, why = first_page_verdict(texts[0] if texts else "")
    if verdict == "accept":
        if settings.relevance_vision_always:
            verdict, why = "vision", "RELEVANCE_VISION_ALWAYS: the text layer is not trusted"
        else:
            # the text layer says a document; trust it only for words a reader could see on the page
            seen = await asyncio.to_thread(visible_first_page_text, data)
            if seen is not None and first_page_verdict(seen)[0] == "accept":
                logger.info("relevance_gate_accepted", why=why)
                return None
            verdict, why = "vision", "the text that names a document cannot be seen on the page"
    if await token_budget.exhausted():  # the daily budget is spent: the model is not asked (the file passes, as when the gate cannot answer)
        logger.warning("relevance_gate_skipped", reason="daily_token_budget_spent")
        return None
    result = await ask_first_page(data)
    await token_budget.add_spend(result.usage["total_tokens"])  # a refused file's request counts too
    # a refused file is stored nowhere, so its request is visible here only: the log carries what it cost
    logger.info("relevance_gate_asked_the_model", why=why, kind=result.kind, **{f"gate_{k}": v for k, v in result.usage.items()})
    if result.kind == "OTHER":
        raise ValidationError(REJECTION_MESSAGE, detail={"reason": "not_a_shipping_document"})
    return result
