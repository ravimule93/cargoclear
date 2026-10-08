"""Grounding agent — BigQuery AHTN Vector Search tariff validation.

Uses BigQuery VECTOR_SEARCH with TreeAH index (v4.0 Appendix D) to
ground extracted commodity descriptions against official AHTN tariffs.

No hallucination rule: this agent can ONLY call lookup_tariff().
It has no free-text authority over HS codes or required-document lists.

Phase 3: Uncomment BigQuery client code.
Skeleton: Returns a synthetic grounding result.
"""

from __future__ import annotations

import structlog

from app.domain.schemas import ExtractedDocument, GroundingFinding, MissingEvidence

logger = structlog.get_logger(__name__)

# Known required documents per HS chapter (deterministic lookup — NOT LLM)
_HS_REQUIRED_DOCS: dict[str, list[str]] = {
    "7304": ["MILL_TEST_CERTIFICATE"],
    "7306": ["MILL_TEST_CERTIFICATE"],
    "1001": ["PHYTOSANITARY"],
    "0901": ["PHYTOSANITARY", "CERTIFICATE_OF_ORIGIN"],
}

AMBIGUITY_THRESHOLD = 0.35  # cosine distance above this → AMBIGUOUS


def _collect_required(findings: list[GroundingFinding]) -> list[str]:
    """Collect the union of required document types across all findings."""
    required: set[str] = set()
    for f in findings:
        required.update(f.required_documents)
    return list(required)


def _diff_against_uploaded(
    required: list[str],
    uploaded_types: list[str],
) -> list[dict]:
    """Return required document types that have NOT been uploaded."""
    uploaded_set = set(uploaded_types)
    missing = []
    for doc_type in required:
        if doc_type not in uploaded_set:
            missing.append({
                "id": f"ME-{doc_type}",
                "document_label": doc_type.replace("_", " ").title(),
                "hs_code": "7304",
                "reason": f"Required by AHTN for the declared commodity.",
                "regulation_ref": "AHTN 2022",
            })
    return missing


async def run_grounding_agent(ctx: dict) -> dict:
    """Ground extracted documents against BigQuery AHTN tariffs.

    Reads:  ctx["extracted"]            (list[ExtractedDocument])
            ctx["destination_country"]  (str — ISO alpha-2, default "SG")
            ctx["uploaded_types"]       (list[str] — already-uploaded doc types)
    Writes: ctx["grounding"]            (list[GroundingFinding])
            ctx["required_documents"]   (list[str] — union of all required types)
            ctx["missing_evidence"]     (list[dict] — required but not uploaded)
            ctx["grounding_ambiguous"]  (bool — True if any finding is AMBIGUOUS)
    """
    extracted: list[ExtractedDocument] = ctx.get("extracted", [])
    destination = ctx.get("destination_country", "SG")
    uploaded_types: list[str] = ctx.get("uploaded_types", [])

    findings: list[GroundingFinding] = []

    for doc in extracted:
        for item in doc.line_items:
            desc_ref = item.description
            if not desc_ref or not desc_ref.value:
                continue

            desc = str(desc_ref.value)
            declared_hs = str(item.hs_code_declared.value) if item.hs_code_declared.value else None

            # ---- Phase 3: uncomment BigQuery Vector Search ----
            # from app.agents.tools.bq_tariff import lookup_tariff
            # hits = lookup_tariff(desc, destination)
            # ---------------------------------------------------

            # Skeleton: return a synthetic hit
            hits = _synthetic_hits(desc, declared_hs)

            top = hits[0] if hits else None
            ambiguous = (not hits) or (top and top["distance"] > AMBIGUITY_THRESHOLD)

            # Determine required documents from HS chapter (deterministic)
            req_docs: list[str] = []
            if declared_hs:
                for prefix, docs in _HS_REQUIRED_DOCS.items():
                    if declared_hs.startswith(prefix):
                        req_docs = docs
                        break

            findings.append(GroundingFinding(
                document_id=doc.document_id,
                declared_hs=declared_hs,
                top_candidate_hs=top["hs_code"] if top else None,
                top_candidate_description=top["description"] if top else None,
                distance=top["distance"] if top else None,
                ambiguous=bool(ambiguous),
                required_documents=req_docs,
            ))

    required = _collect_required(findings)
    missing = _diff_against_uploaded(required, uploaded_types)

    ctx["grounding"] = [f.model_dump() for f in findings]
    ctx["required_documents"] = required
    ctx["missing_evidence"] = missing
    ctx["grounding_ambiguous"] = any(f.ambiguous for f in findings)
    return ctx


def _synthetic_hits(desc: str, declared_hs: str | None) -> list[dict]:
    """Return a synthetic BigQuery Vector Search hit for skeleton mode."""
    hs = declared_hs or "73041900"
    return [{
        "hs_code": hs,
        "description": "Steel pipes, seamless, for industrial use (AHTN 7304.19.00)",
        "distance": 0.08,
        "required_documents": ["MILL_TEST_CERTIFICATE"],
    }]
