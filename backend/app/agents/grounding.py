"""Grounding agent — BigQuery AHTN Vector Search tariff validation & missing evidence detection.

Per v4.0 Specification (Epic 4, US 4.1):
  - Validates declared 8-digit HS codes against official master tariffs via Vector Search.
  - Zero-hallucination constraint: required documents are strictly driven by official
    AHTN regulations and BigQuery tariff entries.
  - Distance > 0.35 flagged as AMBIGUOUS -> routes to SPECIALIST_REVIEW_REQUIRED.
  - Detects missing mandatory trade certificates (e.g., Mill Test Certificate for HS 7304).
"""

from __future__ import annotations

from typing import Any

import structlog

from app.agents.tools.bq_tariff import AMBIGUITY_THRESHOLD, lookup_tariff
from app.domain.schemas import ExtractedDocument, GroundingFinding

logger = structlog.get_logger(__name__)


async def run_grounding_agent(ctx: dict[str, Any]) -> dict[str, Any]:
    """Execute tariff vector grounding and verify evidence completeness.

    Reads:
      - ctx["extracted"] (list[ExtractedDocument])
      - ctx.get("destination_country", "SG")

    Writes:
      - ctx["grounding"] (list[dict])
      - ctx["required_documents"] (list[str])
      - ctx["missing_evidence"] (list[dict])
      - ctx["grounding_ambiguous"] (bool)
    """
    extracted: list[ExtractedDocument] = ctx.get("extracted", [])
    destination: str = ctx.get("destination_country", "SG")

    # Collect all doc_types currently present in the bundle
    present_doc_types = {d.doc_type for d in extracted}

    findings: list[GroundingFinding] = []
    required_doc_types: set[str] = set()
    missing_items: list[dict[str, Any]] = []

    for doc in extracted:
        for item in doc.line_items:
            desc_val = str(item.description.value).strip() if (item.description and item.description.value) else ""
            hs_val = str(item.hs_code_declared.value).strip() if (item.hs_code_declared and item.hs_code_declared.value) else None

            if not desc_val and not hs_val:
                continue

            query_text = f"{desc_val} {hs_val or ''}".strip()
            hits = lookup_tariff(query_text, destination_country=destination)

            top_hit = hits[0] if hits else None
            distance = top_hit["distance"] if top_hit else 1.0
            is_ambiguous = (top_hit is None) or (distance > AMBIGUITY_THRESHOLD)

            req_docs = top_hit.get("required_documents", []) if top_hit else []
            for r in req_docs:
                required_doc_types.add(r)
                if r not in present_doc_types:
                    item_id = f"ME-{r}"
                    if not any(m["id"] == item_id for m in missing_items):
                        missing_items.append({
                            "id": item_id,
                            "document_label": r.replace("_", " ").title(),
                            "hs_code": hs_val or (top_hit["hs_code"] if top_hit else "7304"),
                            "reason": f"Mandatory compliance certificate required by official tariff regulation for {desc_val[:40]}.",
                            "regulation_ref": "AHTN 2022 Master Tariff",
                        })

            findings.append(
                GroundingFinding(
                    document_id=doc.document_id,
                    declared_hs=hs_val,
                    top_candidate_hs=top_hit["hs_code"] if top_hit else None,
                    top_candidate_description=top_hit["description"] if top_hit else None,
                    distance=distance,
                    ambiguous=is_ambiguous,
                    required_documents=req_docs,
                )
            )

    ctx["grounding"] = [f.model_dump() for f in findings]
    ctx["required_documents"] = list(required_doc_types)
    ctx["missing_evidence"] = missing_items
    ctx["grounding_ambiguous"] = any(f.ambiguous for f in findings)
    return ctx
