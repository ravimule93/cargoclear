"""What was NOT read: checks about the pages of a document that the model was not shown.

A page the model never saw contributes nothing to the assessment, so the assessment has to say it was left out instead of
passing over it in silence (services/relevance.py decides which pages are read):

  P-001-<document>  WARN. Pages that look like part of the document were not read because the per-document cap was reached. Values
                    printed on them are not in the assessment, so a person has to look: the status cannot be COMPLIANT_FOR_SUBMISSION.
  P-002-<document>  PASS. Pages that look like terms and conditions (no table of figures, no field names) were skipped. Listed so that
                    nothing disappears unseen; the page images the model was shown are kept (the viewer's "What the model saw").

The plan of each document is stored with its extraction (``page_plans``), so a recompute, which reads no document again, still says it.
"""

from __future__ import annotations

from typing import Any

from app.domain.schemas import CheckResult
from app.services.relevance import page_ranges


def _label(plan: dict[str, Any], documents: list[dict[str, Any]]) -> str:
    document_id = plan.get("document_id")
    named = next((d.get("filename") for d in documents if d.get("document_id") == document_id and d.get("filename")), None)
    return str(named or document_id)


def checks(page_plans: dict[str, dict[str, Any]] | None, documents: list[dict[str, Any]]) -> list[CheckResult]:
    """The coverage checks for every document whose plan left pages out, in the bundle's document order."""
    if not page_plans:
        return []
    order = [str(d["document_id"]) for d in documents if d.get("document_id") in page_plans]
    order += [document_id for document_id in page_plans if document_id not in order]
    results: list[CheckResult] = []
    for document_id in order:
        plan = {**page_plans[document_id], "document_id": document_id}
        label = _label(plan, documents)
        over_cap, boilerplate = plan.get("over_cap") or [], plan.get("boilerplate") or []
        if over_cap:
            read = plan.get("kept") or []
            reason = (
                "the file gave no text, so the first pages were taken"
                if plan.get("basis") == "no_text_layer" else "they look like part of the document"
            )
            results.append(CheckResult(
                check_id=f"P-001-{document_id}", severity="WARN", focus_document=document_id,
                message=(
                    f"{label}: {len(over_cap)} of {plan.get('total')} pages were not read: pages {page_ranges(over_cap)} ({reason}, "
                    f"and at most {len(read)} pages of one document are read). Pages read: {page_ranges(read)}. "
                    "Values printed on the pages that were not read are not in this assessment."
                ),
            ))
        if boilerplate:
            results.append(CheckResult(
                check_id=f"P-002-{document_id}", severity="PASS", focus_document=document_id,
                message=(
                    f"{label}: {len(boilerplate)} of {plan.get('total')} pages were skipped as terms and conditions (no field names, "
                    f"no table of figures): pages {page_ranges(boilerplate)}."
                ),
            ))
    return results
