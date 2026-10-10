"""Grounding agent — tariff grounding of declared HS codes, required-document derivation and the G-001 check.

Each commodity line is grounded in three steps:

  1. QUERY   the vector / seed query is the line's DESCRIPTION ONLY. The declared HS code is never part of it,
             otherwise the claim would bias its own retrieval. A line without a description is not looked up.
  2. MATCH   the declared code is compared (digits only, via app.domain.hs) with EVERY returned candidate; the best
             match level wins, ties go to the lowest vector distance. That candidate is the GOVERNING row.
  3. POLICY  what the match level allows:

     | match level / situation               | hs_mismatch | ambiguous | required documents          |
     |---------------------------------------|-------------|-----------|-----------------------------|
     | exact8, governing distance <= thresh. | False       | False     | from the GOVERNING row      |
     | exact8, governing distance > thresh.  | False       | True      | from the GOVERNING row      |
     |   and NO other row within threshold   |             |           | (weak, but nothing fits     |
     |                                       |             |           | better: the claim stands)   |
     | exact8, governing distance > thresh.  | True        | True      | none; better_match_hs names |
     |   and a row with a DIFFERENT 8-digit  |             |           | the row that fits better    |
     |   code within threshold (CONTRADICTED)|             |           | (inclusive: == threshold)   |
     | subheading6                           | False       | True      | none (8-digit unconfirmed)  |
     | heading4 / none                       | True        | True      | none (never from a row that |
     |                                       |             |           | does not match the code)    |
     | not_declared (no or short code, or    | False       | True      | none                        |
     | no description)                       |             |           |                             |

     No candidates at all is unverifiable rather than a mismatch: level "none", hs_mismatch False, ambiguous True.
     A contradicted line keeps hs_match_level "exact8" (the code does exist in the tariff) and its governing row.

Certificates (MILL_TEST_CERTIFICATE, CERTIFICATE_OF_ORIGIN, PHYTOSANITARY) describe a test or an origin, not the
goods ("Chemical & mechanical test report ..."), so their lines are not grounded: a description like that can never
retrieve a tariff row, and it must not turn a satisfied requirement back into specialist review.

Requirements come from a curated DEMO rule set, never from an official source: every requirement states its
``rule_set`` and ``regulation_ref`` (prototype wording in app.domain.provenance).

After grounding one check is appended to ``ctx["checks"]``: G-001 "HS classification" (PASS iff every line is
exact8, not ambiguous and had a description; otherwise WARN, never MATERIAL). It makes the grounding outcome visible
next to the other checks; status resolution is unchanged (``grounding_ambiguous`` already routes to specialist review).

Core trade document completeness: COMMERCIAL_INVOICE, BILL_OF_LADING and PACKING_LIST are always expected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.agents.tools.bq_tariff import AMBIGUITY_THRESHOLD, lookup_tariff_with_source
from app.domain.hs import (
    CERTIFICATE_DOC_TYPES,
    HS_FULL_DIGITS,
    HS_MIN_DIGITS,
    HsMatchLevel,
    hs_digits,
    hs_evidence_entry,
    hs_match_level,
    hs_text,
)
from app.domain.provenance import CORE_DOC_REASON, CORE_DOC_REF, REGULATION_REF_DEMO, RULE_SET_DEMO
from app.domain.schemas import CheckResult, ExtractedDocument, FieldRef, GroundingFinding

logger = structlog.get_logger(__name__)

CORE_TRADE_DOCUMENTS = [
    ("COMMERCIAL_INVOICE", "Commercial Invoice"),
    ("BILL_OF_LADING", "Bill of Lading"),
    ("PACKING_LIST", "Packing List"),
]

# Documents whose line items describe a test report / an origin rather than the goods themselves.
NON_COMMODITY_DOC_TYPES = frozenset(CERTIFICATE_DOC_TYPES)

_LEVEL_RANK: dict[str, int] = {"exact8": 4, "subheading6": 3, "heading4": 2, "none": 1, "not_declared": 0}
_DESCRIPTION_CHARS = 60


@dataclass
class _Line:
    """One grounded commodity line: what was declared, what governs it, and the verdict."""

    doc: ExtractedDocument
    index: int
    declared: str                 # the declared code as printed ('' when none)
    declared_ref: FieldRef | None
    description: str
    level: HsMatchLevel
    governing: dict[str, Any] | None   # best-matching candidate (the row required documents come from)
    closest: dict[str, Any] | None     # row to name in messages: the governing row, else the top-ranked one
    looked_up: bool
    hs_mismatch: bool
    ambiguous: bool
    better_match: dict[str, Any] | None = None   # set when the exact8 claim is CONTRADICTED by the description

    @property
    def confirmed(self) -> bool:
        return self.level == "exact8" and not self.ambiguous and bool(self.description)

    @property
    def derives_requirements(self) -> bool:
        """Only an exact 8-digit match that nothing contradicts may require documents."""
        return self.level == "exact8" and self.governing is not None and self.better_match is None


def _distance(candidate: dict[str, Any]) -> float:
    return float(candidate.get("distance", 1.0))


def _best_candidate(declared: str, hits: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, HsMatchLevel]:
    """The candidate with the best match level (ties: lowest distance, then retrieval order)."""
    best: dict[str, Any] | None = None
    best_level: HsMatchLevel = "none"
    best_key: tuple[int, float] | None = None
    for candidate in hits:
        level = hs_match_level(declared, candidate["hs_code"])
        key = (_LEVEL_RANK[level], -_distance(candidate))
        if best_key is None or key > best_key:
            best, best_level, best_key = candidate, level, key
    return best, best_level


def _better_match(governing: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The row that contradicts a weak exact8 claim, if any.

    A weak governing row (distance > threshold) is contradicted when ANOTHER retrieved row with a different 8-digit
    code lies within the threshold (inclusive): the description fits that row better than the declared one. The
    closest such row wins; ties go to the one retrieved first.
    """
    if _distance(governing) <= AMBIGUITY_THRESHOLD:
        return None
    own = hs_digits(governing["hs_code"])[:HS_FULL_DIGITS]
    alternatives = [
        c for c in hits
        if hs_digits(c["hs_code"])[:HS_FULL_DIGITS] != own and _distance(c) <= AMBIGUITY_THRESHOLD
    ]
    return min(alternatives, key=_distance, default=None)


def _text(ref: FieldRef | None) -> str:
    return hs_text(ref.value).strip() if ref is not None and ref.value is not None else ""


def _ground_line(
    doc: ExtractedDocument,
    index: int,
    destination: str,
    lookup_sources: set[str],
) -> _Line | None:
    item = doc.line_items[index]
    description = _text(item.description)
    declared = hs_text(item.hs_code_declared.value) if item.hs_code_declared is not None else ""
    if not description and not declared:
        return None

    hits: list[dict[str, Any]] = []
    if description:
        hits, source = lookup_tariff_with_source(description, destination_country=destination)
        lookup_sources.add(source)

    top_hit = hits[0] if hits else None
    governing: dict[str, Any] | None = None
    if not description:
        level: HsMatchLevel = "not_declared"
    elif len(hs_digits(declared)) < HS_MIN_DIGITS:
        level = "not_declared"  # no code, or fewer than 6 digits: nothing to match
    else:
        governing, level = _best_candidate(declared, hits)

    better = _better_match(governing, hits) if level == "exact8" and governing is not None else None
    hs_mismatch = better is not None or (level in ("heading4", "none") and bool(hits))
    if level == "exact8" and governing is not None:
        ambiguous = _distance(governing) > AMBIGUITY_THRESHOLD
    else:
        ambiguous = True

    return _Line(
        doc=doc, index=index, declared=declared, declared_ref=item.hs_code_declared, description=description,
        level=level, governing=governing, closest=governing or top_hit, looked_up=bool(description),
        hs_mismatch=hs_mismatch, ambiguous=ambiguous, better_match=better,
    )


# ---------------------------------------------------------------------------
# G-001
# ---------------------------------------------------------------------------


def _row_text(row: dict[str, Any] | None) -> str:
    if row is None:
        return "none (no tariff candidate was retrieved)"
    return f"{row['hs_code']} ('{str(row['description'])[:_DESCRIPTION_CHARS]}', distance {_distance(row):.2f})"


def _problem_sentence(line: _Line) -> str:
    code = f"declared code '{line.declared}'" if line.declared else "no HS code is declared;"
    if not line.description:
        return f"{code} has no description, so the line could not be classified" if line.declared else (
            "the line has no description and no HS code, so it could not be classified"
        )
    if line.level == "not_declared":
        return (
            f"declared code '{line.declared}' gives no usable HS code (at least 6 digits are needed)"
            if line.declared
            else "no HS code is declared, so there is no usable code to check"
        )
    if line.better_match is not None:
        return (
            f"declared code '{line.declared}' exists in the tariff, but the description matches HS "
            f"{_row_text(line.better_match)} much better (declared row distance {_distance(line.governing or {}):.2f})"
        )
    if line.level == "exact8":
        return (
            f"{code} matches a tariff row at 8 digits, but the description is only a weak match "
            f"(distance {_distance(line.governing or {}):.2f} > {AMBIGUITY_THRESHOLD})"
        )
    if line.level == "subheading6":
        return f"{code} matches a tariff row at 6 digits only, so the 8-digit code is unconfirmed"
    if line.level == "heading4":
        return f"{code} matches only the 4-digit heading of a tariff row (another subheading), so it is treated as a mismatch"
    return f"{code} matches no retrieved tariff candidate"


def _build_g001(lines: list[_Line]) -> CheckResult:
    evidence = [
        hs_evidence_entry(line.doc.document_id, "hs_code_declared", line.declared_ref, line_item=line.index)
        for line in lines
    ]
    if not lines:
        return CheckResult(
            check_id="G-001",
            severity="WARN",
            message="HS classification not performed: no line item with a description or a declared HS code was found.",
            evidence=evidence,
        )

    problems = [line for line in lines if not line.confirmed]
    if not problems:
        codes = sorted({str(line.governing["hs_code"]) for line in lines if line.governing})
        rule_sets = sorted({str(line.governing.get("rule_set") or RULE_SET_DEMO) for line in lines if line.governing})
        worst = max(_distance(line.governing) for line in lines if line.governing)
        return CheckResult(
            check_id="G-001",
            severity="PASS",
            message=(
                f"HS classification confirmed: declared code(s) {', '.join(codes)} match the "
                f"{' / '.join(rule_sets)} tariff at 8 digits (distance {worst:.2f}, ambiguity threshold "
                f"{AMBIGUITY_THRESHOLD})."
            ),
            evidence=evidence,
        )

    first = problems[0]
    # A contradicted line already names both rows; for the others say which row came closest.
    closest = "" if first.better_match is not None else f" Closest tariff candidate: {_row_text(first.closest)}."
    return CheckResult(
        check_id="G-001",
        severity="WARN",
        message=f"HS classification not confirmed: {_problem_sentence(first)}.{closest} Other problem lines: {len(problems) - 1}.",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------


async def run_grounding_agent(ctx: dict[str, Any]) -> dict[str, Any]:
    """Execute tariff grounding, derive required documents and verify evidence completeness.

    Reads:
      - ctx["extracted"] (list[ExtractedDocument])
      - ctx.get("destination_country", "SG")

    Writes:
      - ctx["grounding"] (list[dict], one GroundingFinding per grounded line)
      - ctx["required_documents"] (list[str]; only from lines whose declared code matches a row at 8 digits
        and is not contradicted by the description)
      - ctx["missing_evidence"] (list[dict])
      - ctx["grounding_ambiguous"] (bool)
      - ctx["grounding_source"] ("seed" if any tariff lookup used the local seed, "bigquery" if all came
        from BigQuery, None if no lookup ran)
      - ctx["checks"]: gains exactly one G-001 "HS classification" check (an existing one is replaced)

    A finding's ``top_candidate_*`` and ``distance`` describe the row the line was judged against: the governing
    row, or the top-ranked row when none governs.
    """
    extracted: list[ExtractedDocument] = ctx.get("extracted", [])
    destination: str = ctx.get("destination_country", "SG")

    # Collect all doc_types currently present in the bundle
    present_doc_types = {d.doc_type for d in extracted}

    findings: list[GroundingFinding] = []
    lines: list[_Line] = []
    lookup_sources: set[str] = set()
    required_doc_types: set[str] = set()
    missing_items: list[dict[str, Any]] = []

    # T2.7: Check core trade document completeness
    for core_type, label in CORE_TRADE_DOCUMENTS:
        if core_type not in present_doc_types:
            missing_items.append({
                "id": f"ME-CORE-{core_type}",
                "document_label": label,
                "hs_code": "GENERAL",
                "reason": CORE_DOC_REASON,
                "regulation_ref": CORE_DOC_REF,
                "rule_set": RULE_SET_DEMO,
            })

    for doc in extracted:
        if doc.doc_type in NON_COMMODITY_DOC_TYPES:
            continue
        for index in range(len(doc.line_items)):
            line = _ground_line(doc, index, destination, lookup_sources)
            if line is None:
                continue
            lines.append(line)

            governing = line.governing
            required_docs: list[str] = []
            rule_set = (governing.get("rule_set") or RULE_SET_DEMO) if governing else None
            regulation_ref = (governing.get("regulation_ref") or REGULATION_REF_DEMO) if governing else None

            # Required documents come only from the GOVERNING row, only for an exact 8-digit match, and never
            # when the description contradicts the declared code.
            if governing is not None and line.derives_requirements:
                required_docs = list(governing.get("required_documents", []))
                for required in required_docs:
                    required_doc_types.add(required)
                    item_id = f"ME-{required}"
                    if required in present_doc_types or any(m["id"] == item_id for m in missing_items):
                        continue
                    label = required.replace("_", " ").title()
                    missing_items.append({
                        "id": item_id,
                        "document_label": label,
                        "hs_code": str(governing["hs_code"]),
                        "reason": (
                            f"Required by the {rule_set} rule set for HS {governing['hs_code']} "
                            f"({str(governing['description'])[:_DESCRIPTION_CHARS]}); no {label} is in the bundle."
                        ),
                        "regulation_ref": regulation_ref,
                        "rule_set": rule_set,
                    })

            judged = line.closest
            findings.append(
                GroundingFinding(
                    document_id=doc.document_id,
                    declared_hs=line.declared or None,
                    top_candidate_hs=str(judged["hs_code"]) if judged else None,
                    top_candidate_description=str(judged["description"]) if judged else None,
                    distance=_distance(judged) if judged else (1.0 if line.looked_up else None),
                    ambiguous=line.ambiguous,
                    hs_mismatch=line.hs_mismatch,
                    required_documents=required_docs,
                    hs_match_level=line.level,
                    governing_hs=str(governing["hs_code"]) if governing else None,
                    rule_set=rule_set,
                    regulation_ref=regulation_ref,
                    better_match_hs=str(line.better_match["hs_code"]) if line.better_match else None,
                )
            )

    ctx["grounding"] = [f.model_dump() for f in findings]
    ctx["required_documents"] = sorted(required_doc_types)
    ctx["missing_evidence"] = missing_items
    ctx["grounding_ambiguous"] = any(f.ambiguous for f in findings)
    if not lookup_sources:
        ctx["grounding_source"] = None
    else:
        ctx["grounding_source"] = "seed" if "seed" in lookup_sources else "bigquery"

    checks = [c for c in ctx.get("checks", []) if c.get("check_id") != "G-001"]
    checks.append(_build_g001(lines).model_dump())
    ctx["checks"] = checks
    return ctx
