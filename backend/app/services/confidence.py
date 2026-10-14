"""Confidence routing service.

Implements the 4-tier routing table from Specification §3 (Epic 5, US 5.3):

  Extraction Confidence   Deterministic Result     Action               Resulting Status
  >= 0.95                 PASS                     AUTO_ACCEPT          COMPLIANT_FOR_SUBMISSION
  >= 0.95                 FAIL                     AUTO_FLAG            MATERIAL_CONTRADICTION
  0.65 – 0.94             any                      INTERACTIVE_REVIEW   SPECIALIST_REVIEW_REQUIRED
  < 0.65                  any                      MANUAL_ENTRY         SPECIALIST_REVIEW_REQUIRED

"Extraction confidence" is scoped to what the verdict rests on, so a field no check looks at cannot force a review:

  min_overall_confidence   minimum over EVERY populated field (the original semantics, kept for reference)
  min_field_confidence     minimum over the RELEVANT fields: the FieldRefs cited by ``ctx["checks"][*].evidence``
                           that carry a value. When no cited field resolves (no checks, no evidence) every populated
                           field is relevant. This is the figure the UI shows.
  min_doc_type_confidence  minimum ``doc_type_confidence`` over ALL extracted documents
  tier                     min(min_field_confidence, min_doc_type_confidence)

The result also says what determined the tier: ``low_confidence_fields`` (which fields, used by which checks) and a
one-sentence ``reason``. No documents, or nothing populated, is MANUAL_ENTRY.

Runs after grounding in the pipeline, so it sees the evidence of G-001 as well as the deterministic checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from app.domain.schemas import ExtractedDocument, FieldRef, LineItem

MIN_FIELD_CONF_THRESHOLD: float = 0.65
HIGH_CONF_THRESHOLD: float = 0.95
MAX_LOW_CONFIDENCE_FIELDS: int = 10

_DOC_FIELDS = frozenset(ExtractedDocument.model_fields)
_LINE_FIELDS = frozenset(LineItem.model_fields)
# lists of field references on the document itself (a certificate's table cells and heat numbers): evidence points at one
# with {"field": <list name>, "row": <index>}
_ROW_LISTS = ("heat_numbers", "test_results")


@dataclass
class _Scoped:
    """One field in scope: where it is, how sure the extraction was, and which checks cite it."""

    document_id: str
    name: str
    line_item: int | None      # the line, or, with ``collection``, the row of that list
    confidence: float
    used_by: set[str] = field(default_factory=set)
    collection: str | None = None   # "test_results" / "heat_numbers" for a row of such a list; None otherwise

    @property
    def sort_key(self) -> tuple[float, int, str, int, str]:
        return (self.confidence, 0, self.document_id, -1 if self.line_item is None else self.line_item, self.name)

    @property
    def label(self) -> str:
        if self.collection is not None:
            where = f"{self.collection}[{self.line_item}]"
        else:
            where = self.name if self.line_item is None else f"line_items[{self.line_item}].{self.name}"
        return f"{self.document_id}.{where}"


def _iter_fields(doc: ExtractedDocument) -> Iterator[tuple[str, int | None, FieldRef, str | None]]:
    """Every FieldRef on a document as (name, index, ref, collection): header fields (index None), the rows of a
    certificate's lists (collection = the list), and the fields of each line item (collection None)."""
    for name in _DOC_FIELDS:
        value = getattr(doc, name, None)
        if isinstance(value, FieldRef):
            yield name, None, value, None
    for collection in _ROW_LISTS:
        for index, ref in enumerate(getattr(doc, collection, None) or []):
            if isinstance(ref, FieldRef):
                yield collection, index, ref, collection
    for index, item in enumerate(doc.line_items):
        for name in _LINE_FIELDS:
            value = getattr(item, name, None)
            if isinstance(value, FieldRef):
                yield name, index, value, None


def _resolve(doc: ExtractedDocument, name: Any, line_item: Any, row: Any = None) -> list[tuple[int | None, FieldRef, str | None]]:
    """The FieldRef(s) an evidence entry points at as (index, ref, collection); empty when it cannot be resolved.

    With ``row`` and a list name ("test_results", "heat_numbers") the one row. With ``line_item`` the field of that line;
    without it a header field, or (for a line-item field such as hs_code_declared) the field of every line of the document.
    """
    if not isinstance(name, str):
        return []
    if name in _ROW_LISTS:
        rows = getattr(doc, name, None) or []
        if isinstance(row, bool) or not isinstance(row, int) or not 0 <= row < len(rows):
            return []
        return [(row, rows[row], name)] if isinstance(rows[row], FieldRef) else []
    if line_item is not None:
        if isinstance(line_item, bool) or not isinstance(line_item, int) or not 0 <= line_item < len(doc.line_items):
            return []
        value = getattr(doc.line_items[line_item], name, None) if name in _LINE_FIELDS else None
        return [(line_item, value, None)] if isinstance(value, FieldRef) else []

    header = getattr(doc, name, None) if name in _DOC_FIELDS else None
    if isinstance(header, FieldRef):
        return [(None, header, None)]
    if name in _LINE_FIELDS:
        return [
            (index, value, None)
            for index, item in enumerate(doc.line_items)
            if isinstance(value := getattr(item, name, None), FieldRef)
        ]
    return []


def _cited_fields(docs: list[ExtractedDocument], checks: list[dict[str, Any]]) -> list[_Scoped]:
    """The populated fields that checks cite, each with the ids of the checks that cite it."""
    by_id = {d.document_id: d for d in docs}
    cited: dict[tuple[str, str, int | None], _Scoped] = {}
    for check in checks:
        check_id = check.get("check_id")
        for entry in check.get("evidence") or []:
            if not isinstance(entry, dict):
                continue
            doc = by_id.get(entry.get("doc"))
            if doc is None:
                continue
            for index, ref, collection in _resolve(doc, entry.get("field"), entry.get("line_item"), entry.get("row")):
                if ref.value is None:
                    continue
                key = (doc.document_id, entry["field"], index)
                scoped = cited.setdefault(
                    key, _Scoped(doc.document_id, entry["field"], index, round(float(ref.confidence), 4), collection=collection)
                )
                if check_id:
                    scoped.used_by.add(str(check_id))
    return list(cited.values())


def _fmt(confidence: float) -> str:
    return f"{confidence:.2f}" if round(confidence, 2) == confidence else f"{confidence:.4f}".rstrip("0")


def _action(tier_confidence: float, math_passed: bool) -> str:
    if tier_confidence >= HIGH_CONF_THRESHOLD:
        return "AUTO_ACCEPT" if math_passed else "AUTO_FLAG"
    if tier_confidence >= MIN_FIELD_CONF_THRESHOLD:
        return "INTERACTIVE_REVIEW"
    return "MANUAL_ENTRY"


def _reason(
    *,
    tier_confidence: float,
    in_scope: list[_Scoped],
    uses_checks: bool,
    lowest_doc: ExtractedDocument,
    min_doc: float,
) -> str:
    """One sentence naming the field or document that determined the tier."""
    if tier_confidence >= HIGH_CONF_THRESHOLD:
        scope = "Every field used by a check" if uses_checks else "Every populated field"
        return f"{scope} and every document classification is >= {HIGH_CONF_THRESHOLD:.2f}."

    outcome = "interactive review" if tier_confidence >= MIN_FIELD_CONF_THRESHOLD else "manual entry"
    lowest_field = min(in_scope, key=lambda s: s.sort_key)
    if min_doc < lowest_field.confidence:
        return (
            f"Lowest confidence is the document classification of {lowest_doc.document_id} "
            f"({_fmt(min_doc)}) -> {outcome}."
        )
    scope = "fields used by checks" if uses_checks else "all populated fields (no check cites a field)"
    return f"Lowest confidence among {scope}: {lowest_field.label} ({_fmt(lowest_field.confidence)}) -> {outcome}."


async def route(ctx: dict[str, Any]) -> dict[str, Any]:
    """Execute confidence-based routing for the extracted document bundle.

    Reads:
      - ctx["extracted"] (list[ExtractedDocument])
      - ctx.get("checks") (list[dict]; the evidence they cite defines which fields matter)
      - ctx.get("math_status", "COMPLIANT_FOR_SUBMISSION")

    Writes:
      - ctx["confidence"] (dict: min_field_confidence, action, min_overall_confidence, min_doc_type_confidence,
        low_confidence_fields, reason)
      - ctx["force_status"] (optional status override when confidence requires review)
    """
    extracted_docs: list[ExtractedDocument] = ctx.get("extracted", [])
    math_passed = ctx.get("math_status", "COMPLIANT_FOR_SUBMISSION") == "COMPLIANT_FOR_SUBMISSION"

    populated = [
        _Scoped(doc.document_id, name, index, round(float(ref.confidence), 4), collection=collection)
        for doc in extracted_docs
        for name, index, ref, collection in _iter_fields(doc)
        if ref.value is not None
    ]
    cited = _cited_fields(extracted_docs, ctx.get("checks", []))
    in_scope = cited or populated  # nothing cited that resolves: every populated field is relevant

    min_overall = min((s.confidence for s in populated), default=None)
    min_field = min((s.confidence for s in in_scope), default=0.0)
    lowest_doc = min(extracted_docs, key=lambda d: d.doc_type_confidence, default=None)
    min_doc = round(float(lowest_doc.doc_type_confidence), 4) if lowest_doc is not None else None

    low_fields = sorted((s for s in in_scope if s.confidence < HIGH_CONF_THRESHOLD), key=lambda s: s.sort_key)
    low: list[tuple[tuple[float, int, str, int, str], dict[str, Any]]] = []
    for scoped in low_fields[:MAX_LOW_CONFIDENCE_FIELDS]:
        entry: dict[str, Any] = {"document_id": scoped.document_id, "field": scoped.name}
        if scoped.line_item is not None:
            entry["row" if scoped.collection else "line_item"] = scoped.line_item
        entry.update(confidence=scoped.confidence, used_by=sorted(scoped.used_by))
        low.append((scoped.sort_key, entry))
    for doc in extracted_docs:
        doc_conf = round(float(doc.doc_type_confidence), 4)
        if doc_conf < HIGH_CONF_THRESHOLD:
            low.append(((doc_conf, 1, doc.document_id, -1, "doc_type"),
                        {"document_id": doc.document_id, "field": "doc_type", "confidence": doc_conf}))

    if lowest_doc is None or min_doc is None:
        action, reason = "MANUAL_ENTRY", "No documents were extracted -> manual entry."
    elif not populated:
        action, reason = "MANUAL_ENTRY", "No populated field was extracted -> manual entry."
    else:
        tier_confidence = min(min_field, min_doc)
        action = _action(tier_confidence, math_passed)
        reason = _reason(
            tier_confidence=tier_confidence, in_scope=in_scope, uses_checks=bool(cited),
            lowest_doc=lowest_doc, min_doc=min_doc,
        )

    ctx["confidence"] = {
        "min_field_confidence": min_field,
        "action": action,
        "min_overall_confidence": min_overall,
        "min_doc_type_confidence": min_doc,
        "low_confidence_fields": [entry for _, entry in sorted(low, key=lambda pair: pair[0])],
        "reason": reason,
    }

    # Moderate or low confidence overrides compliance to force specialist review
    if action in ("INTERACTIVE_REVIEW", "MANUAL_ENTRY"):
        ctx["force_status"] = "SPECIALIST_REVIEW_REQUIRED"

    return ctx
