"""Is this document what it was uploaded as, and can its values be compared with the others'? Two findings, both WARN:

  T-001-<document>  The upload said the file is one type (``declared_type``) and the model read another, or could not type it. The
                    assessment uses the document as READ, so the declared type may be missing from the bundle: the person who uploaded
                    it has to look. Nothing is flagged when no type was declared: the file name is never used to guess one.
  L-001-<document>  Most of the letters in the values read from the document are not Latin script (Chinese, Arabic, Cyrillic, ...).
                    Names, currencies, units and origins are compared with the other documents as printed, with no translation, so
                    findings that compare them may be differences of language, not real mismatches (audit finding F12).

Both are computed from the extraction and the document records, like the page-coverage checks, so a recompute says them too, and a
correction of a document's type (``doc_type``) clears T-001 when the agent says the model was wrong.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Any

from app.agents.grounding import CORE_TRADE_DOCUMENTS
from app.domain.schemas import CheckResult, ExtractedDocument
from app.gateway.errors import ValidationError

TYPE_LABELS: dict[str, str] = {
    "COMMERCIAL_INVOICE": "Commercial Invoice",
    "BILL_OF_LADING": "Bill of Lading",
    "PACKING_LIST": "Packing List",
    "CERTIFICATE_OF_ORIGIN": "Certificate of Origin",
    "PHYTOSANITARY": "Phytosanitary Certificate",
    "MILL_TEST_CERTIFICATE": "Mill Test Certificate",
}
DECLARABLE_TYPES: tuple[str, ...] = tuple(TYPE_LABELS)  # the types the extraction reads; UNKNOWN is what it says when it cannot tell
REQUIRED_TYPES = frozenset(doc_type for doc_type, _label in CORE_TRADE_DOCUMENTS)  # the assessment always expects these (grounding.py)

# "Most": more than half of the letters. And at least this many letters that are not Latin, so a stray word cannot raise it.
MIN_NON_LATIN_LETTERS = 4

_SCRIPT_NAMES: dict[str, str] = {
    "CJK": "Chinese or Japanese ideographs", "HIRAGANA": "Japanese", "KATAKANA": "Japanese", "HANGUL": "Korean", "CYRILLIC": "Cyrillic",
    "ARABIC": "Arabic", "DEVANAGARI": "Devanagari", "THAI": "Thai", "GREEK": "Greek", "HEBREW": "Hebrew", "BENGALI": "Bengali",
    "TAMIL": "Tamil",
}


def parse_declared_type(value: str | None) -> str | None:
    """The declared type of an upload, normalised ("bill of lading" and "Bill_Of_Lading" both mean BILL_OF_LADING), or None when none
    was given (a form field left empty counts as none). 422 for a value that names none of the types the assessment reads."""
    if value is None or not value.strip():
        return None
    normalised = "_".join(value.strip().upper().replace("-", " ").replace("_", " ").split())
    if normalised not in TYPE_LABELS:
        raise ValidationError(
            f"declared_type must be one of {', '.join(DECLARABLE_TYPES)}.",
            detail={"declared_type": value[:64], "allowed": list(DECLARABLE_TYPES)},
        )
    return normalised


def _label_of(meta: dict[str, Any]) -> str:
    return str(meta.get("filename") or meta.get("document_id"))


def type_checks(documents: list[dict[str, Any]], extracted: list[ExtractedDocument]) -> list[CheckResult]:
    """T-001 for every document whose declared type is not the type it was read as, in the bundle's order."""
    read_as = {d.document_id: d for d in extracted}
    results: list[CheckResult] = []
    for meta in documents:
        declared, document_id = meta.get("declared_type"), meta.get("document_id")
        read = read_as.get(str(document_id))
        if not declared or read is None or read.doc_type == declared:
            continue
        label, declared_name = _label_of(meta), TYPE_LABELS.get(declared, declared)
        if read.doc_type == "UNKNOWN":
            said = f"the model could not tell what it is (confidence {round(read.doc_type_confidence * 100)}%)"
        else:
            said = f"the model read it as a {TYPE_LABELS.get(read.doc_type, read.doc_type)} (confidence {round(read.doc_type_confidence * 100)}%)"
        others = [d for d in extracted if d.doc_type == declared and d.document_id != read.document_id]
        consequence = "The assessment uses it as read. "
        if not others:
            # "missing" only where the assessment itself expects the document; for the other types it is only a fact about this bundle
            consequence += (
                f"No other file was read as a {declared_name}, so one is still missing. " if declared in REQUIRED_TYPES
                else f"No other file was read as a {declared_name}. "
            )
        results.append(CheckResult(
            check_id=f"T-001-{document_id}", severity="WARN", focus_document=str(document_id),
            message=(
                f"{label}: uploaded as a {declared_name}, but {said}. {consequence}Check that this is the file you meant to "
                "upload; if the model is wrong, correct the document type."
            ),
        ))
    return results


def _values(node: Any, out: list[str]) -> None:
    """Every printed value of an extraction: the ``value`` (and ``unit``) of each field, cell and row, wherever they sit."""
    if isinstance(node, dict):
        for key, child in node.items():
            if key in ("value", "unit") and isinstance(child, str):
                out.append(child)
            else:
                _values(child, out)
    elif isinstance(node, list):
        for child in node:
            _values(child, out)


def _script_of(letter: str) -> str:
    name = unicodedata.name(letter, "")
    if name.startswith(("LATIN", "FULLWIDTH LATIN")):
        return "LATIN"
    return name.split(" ")[0] if name else "UNKNOWN"


def letters_by_script(document: ExtractedDocument) -> Counter[str]:
    """How many letters of the values read from the document are in each script (digits, punctuation and spaces are not letters)."""
    values: list[str] = []
    _values(document.model_dump(mode="json"), values)
    return Counter(_script_of(ch) for text in values for ch in text if ch.isalpha())


def script_checks(documents: list[dict[str, Any]], extracted: list[ExtractedDocument]) -> list[CheckResult]:
    """L-001 for every document whose values are mostly not Latin script, in the bundle's order."""
    by_id = {str(m.get("document_id")): m for m in documents}
    rank = {document_id: position for position, document_id in enumerate(by_id)}
    results: list[CheckResult] = []
    for document in sorted(extracted, key=lambda d: rank.get(d.document_id, len(rank))):
        counts = letters_by_script(document)
        total = sum(counts.values())
        other = total - counts["LATIN"]
        if other < MIN_NON_LATIN_LETTERS or other * 2 <= total:
            continue
        script = max((s for s in counts if s != "LATIN"), key=lambda s: counts[s])
        label = _label_of(by_id.get(document.document_id, {"document_id": document.document_id}))
        results.append(CheckResult(
            check_id=f"L-001-{document.document_id}", severity="WARN", focus_document=document.document_id,
            message=(
                f"{label}: {other} of the {total} letters in the values read from this document are not Latin script "
                f"(mostly {_SCRIPT_NAMES.get(script, script.title())}). Names, currencies, units and the country of origin are compared "
                "with the other documents as printed, with no translation, so a finding about them (for example the consignee, the "
                "consignor, the origin or the HS code) may be a difference of language and not a real mismatch. Check the values read "
                "from this document."
            ),
        ))
    return results


def checks(documents: list[dict[str, Any]], extracted: list[ExtractedDocument]) -> list[CheckResult]:
    """The identity findings of a bundle: T-001 for each document, then L-001 for each."""
    return [*type_checks(documents, extracted), *script_checks(documents, extracted)]
