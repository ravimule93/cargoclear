"""Hermetic stand-ins for the google-genai client, used by the extraction tests. No network, no credentials.

``FakeGenai`` is scripted per call and records everything the code under test sends. It exposes the async
surface (``client.aio.models.generate_content``, which extraction uses) AND the old blocking surface
(``client.models.generate_content``) with the same script, so a test can be pointed at either implementation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from types import SimpleNamespace
from typing import Any, Callable

from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LineItem, QuantityRef

HANG = object()  # an outcome: the call never finishes on its own (it can only be cancelled / time out)


def box(page: int = 1, ymin: float = 100, xmin: float = 100, ymax: float = 130, xmax: float = 350) -> BBox:
    return BBox(page=page, ymin=ymin, xmin=xmin, ymax=ymax, xmax=xmax)


def good_doc(doc_type: str = "COMMERCIAL_INVOICE", hs: str = "73041900", **top: Any) -> dict[str, Any]:
    """A valid model answer (JSON-ready dict) with values exactly as a document would print them."""
    doc = ExtractedDocument(
        document_id="whatever-the-model-wrote",
        doc_type=doc_type,
        doc_type_confidence=0.97,
        document_number=FieldRef(value="INV-2024-001", confidence=0.99, bbox=box()),
        consignee=FieldRef(value="SINGAPORE PRECISION PIPING PTE LTD", confidence=0.98, bbox=box(ymin=200, ymax=240)),
        consignor=FieldRef(value="BHARAT SEAMLESS PIPES LTD", confidence=0.98, bbox=box(ymin=260, ymax=300)),
        total_net_weight_kg=QuantityRef(value="14,000.0", unit="KGS", confidence=0.98, bbox=box(ymin=350, ymax=380)),
        total_gross_weight_kg=QuantityRef(value="14,280.0", unit="KGS", confidence=0.98, bbox=box(ymin=390, ymax=420)),
        line_items=[
            LineItem(
                description=FieldRef(value="Seamless carbon steel pipes API 5L Grade B", confidence=0.98, bbox=box(ymin=450, ymax=480)),
                quantity=FieldRef(value="120 LENGTHS", confidence=0.96, bbox=box(ymin=500, ymax=530)),
                net_weight_kg=QuantityRef(value="14,000.0", unit="KGS", confidence=0.99, bbox=box(ymin=500, ymax=530)),
                gross_weight_kg=QuantityRef(value="14,280.0", unit="KGS", confidence=0.98, bbox=box(ymin=500, ymax=530)),
                hs_code_declared=FieldRef(value=hs, confidence=0.99, bbox=box(ymin=500, ymax=530)),
            )
        ],
    ).model_dump(mode="json")
    return doc | top


def response(
    doc: dict[str, Any] | str | None = None,
    *,
    finish: Any = "STOP",
    usage: bool = True,
    block: str | None = None,
) -> SimpleNamespace:
    """What generate_content returns. ``text`` is the JSON; ``parsed`` imitates the SDK (None if the schema rejects it)."""
    text = json.dumps(doc) if isinstance(doc, dict) else doc
    parsed = None
    if isinstance(doc, dict):
        try:
            parsed = ExtractedDocument.model_validate(doc)
        except Exception:  # noqa: BLE001 - the SDK also hands back None for an answer the schema rejects
            parsed = None
    return SimpleNamespace(
        text=text,
        parsed=parsed,
        candidates=None if finish is None else [SimpleNamespace(finish_reason=finish)],
        usage_metadata=SimpleNamespace(prompt_token_count=1200, candidates_token_count=340) if usage else None,
        prompt_feedback=SimpleNamespace(block_reason=block) if block else None,
    )


def payload_of(kwargs: dict[str, Any]) -> str:
    """The first binary part of a request, decoded: tests give every document a distinct payload."""
    for part in kwargs["contents"]:
        inline = getattr(part, "inline_data", None)
        if inline is not None:
            return bytes(inline.data).decode()
    return ""


def doc_of(kwargs: dict[str, Any]) -> str:
    return payload_of(kwargs).split("-p")[0]


def texts_of(kwargs: dict[str, Any]) -> list[str]:
    return [p if isinstance(p, str) else p.text for p in kwargs["contents"] if isinstance(p, str) or getattr(p, "text", None)]


class FakeGenai:
    def __init__(
        self,
        outcome: Callable[[int, dict[str, Any]], Any],
        delay: float | Callable[[dict[str, Any]], float] = 0.0,
    ) -> None:
        self.outcome = outcome
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.cancelled = 0
        self.models = SimpleNamespace(generate_content=self._sync)
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._async))

    def _delay(self, kwargs: dict[str, Any]) -> float:
        return self.delay(kwargs) if callable(self.delay) else self.delay

    def _finish(self, result: Any) -> Any:
        if isinstance(result, BaseException):
            raise result
        return result

    def _enter(self, kwargs: dict[str, Any]) -> int:
        self.calls.append(kwargs)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        return len(self.calls)

    async def _async(self, **kwargs: Any) -> Any:
        number = self._enter(kwargs)
        try:
            result = self.outcome(number, kwargs)  # evaluated once per call
            if result is HANG:
                await asyncio.sleep(3600)
            if self._delay(kwargs):
                await asyncio.sleep(self._delay(kwargs))
            return self._finish(result)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.in_flight -= 1

    def _sync(self, **kwargs: Any) -> Any:
        """The old blocking call: it holds the whole event loop for as long as it takes."""
        number = self._enter(kwargs)
        try:
            result = self.outcome(number, kwargs)
            if self._delay(kwargs):
                time.sleep(self._delay(kwargs))
            return self._finish(result)
        finally:
            self.in_flight -= 1


def always(result: Any) -> Callable[[int, dict[str, Any]], Any]:
    return lambda _n, _kw: result


def script(*outcomes: Any) -> Callable[[int, dict[str, Any]], Any]:
    """Outcome per call number (1-based); the last one repeats."""
    return lambda n, _kw: outcomes[min(n, len(outcomes)) - 1]


def ctx_for(*doc_ids: str, mime: str = "image/png", pages: int = 1, bundle_id: str = "") -> dict[str, Any]:
    """A pipeline context with ``pages`` processed pages per document; each payload is ``<doc>-p<n>``."""
    documents = [{"document_id": d, "filename": f"{d}.pdf"} for d in doc_ids]
    processed = [
        {"document_id": d, "page": n, "payload": f"{d}-p{n}".encode(), "mime": mime}
        for d in doc_ids
        for n in range(1, pages + 1)
    ]
    return {"bundle_id": bundle_id, "documents": documents, "processed_pages": processed}


# ---------------------------------------------------------------------------
# A fake Gemini for the whole live pipeline: it "reads" the Case C PDFs
# ---------------------------------------------------------------------------


def parts_of(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    """The request parts as plain dicts: {"text": str} or {"mime": str, "data": bytes}."""
    out: list[dict[str, Any]] = []
    for part in kwargs["contents"]:
        inline = getattr(part, "inline_data", None)
        if inline is not None:
            out.append({"mime": inline.mime_type, "data": bytes(inline.data)})
        else:
            out.append({"text": part if isinstance(part, str) else part.text})
    return out


def first_page_of(kwargs: dict[str, Any]) -> bytes:
    return next(p["data"] for p in parts_of(kwargs) if "data" in p)


def fixture_json(filename: str) -> dict[str, Any]:
    """What a flawless extraction of this Case C PDF returns: the values and boxes the PDF was drawn from."""
    from app.agents import extraction

    return extraction._generate_fixture_for_file("model-id", filename).model_dump(mode="json")


async def case_c_gemini(filenames: Any, *, delay: float = 0.0) -> FakeGenai:
    """A FakeGenai that answers each request with ``fixture_json`` of the document whose first page it was sent.

    The document is identified by the sha256 of the first page payload. The hash -> file map is built from the very
    rendering the pipeline performs (``preprocess.run``), so it holds with poppler (PNG pages) and without it (the raw
    PDF is passed through). A request for any other payload fails loudly (and is recorded in ``fake.unknown``).
    """
    from app.services import preprocess
    from tests.helpers import case_c_pdf

    by_hash: dict[str, str] = {}
    for name in filenames:
        rendered = await preprocess.run({"raw_bytes": case_c_pdf(name), "document_id": name})
        by_hash[hashlib.sha256(rendered["processed_pages"][0]["payload"]).hexdigest()] = name

    unknown: list[str] = []

    def outcome(_number: int, kwargs: dict[str, Any]) -> Any:
        digest = hashlib.sha256(first_page_of(kwargs)).hexdigest()
        name = by_hash.get(digest)
        if name is None:
            unknown.append(digest)
            return RuntimeError("the fake Gemini was sent a payload it does not know")
        return response(fixture_json(name))

    fake = FakeGenai(outcome, delay=delay)
    fake.by_hash = by_hash  # type: ignore[attr-defined]
    fake.unknown = unknown  # type: ignore[attr-defined]
    return fake
