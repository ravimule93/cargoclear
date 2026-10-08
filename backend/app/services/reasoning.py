"""Reasoning Delta service — before/after iteration differential builder.

Per v4.0 Specification (Epic 5, US 5.2):
  - Detects status transitions (e.g., MISSING_EVIDENCE -> COMPLIANT_FOR_SUBMISSION).
  - Pinpoints satisfied missing evidence requirements and cites the exact resolving document.
  - Highlights check severity improvements (e.g., MATERIAL -> PASS).
  - Synthesizes a transparent, human-readable narrative for the Custom House Agent.
"""

from __future__ import annotations

from typing import Any

from app.domain.schemas import ReasoningDelta


def _snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
    """Capture a comparable snapshot of the current iteration state."""
    docs = ctx.get("documents", [])
    doc_ids = [d.get("document_id") for d in docs if isinstance(d, dict)]

    extracted = ctx.get("extracted", [])
    extracted_types = [getattr(d, "doc_type", "UNKNOWN") for d in extracted]

    return {
        "status": ctx.get("final_status", "COMPLIANT_FOR_SUBMISSION"),
        "checks": ctx.get("checks", []),
        "documents": doc_ids,
        "extracted_types": extracted_types,
        "missing_evidence": ctx.get("missing_evidence", []),
    }


def _narrate(changes: list[dict[str, Any]]) -> str:
    """Build a concise, professional explanation narrative from structured changes."""
    if not changes:
        return "No material changes detected between assessment iterations."

    explanations = []
    for c in changes:
        field = c.get("field", "")
        from_val = c.get("from", "")
        to_val = c.get("to", "")
        because = c.get("because", "")

        if field == "status":
            explanations.append(f"Compliance status updated from {from_val} to {to_val} ({because}).")
        elif "missing_evidence" in field:
            explanations.append(f"Required evidence requirement {field.replace('missing_evidence.', '')} was satisfied ({because}).")
        else:
            explanations.append(f"Check {field} changed from {from_val} to {to_val}: {because}.")

    return " ".join(explanations)


async def build(ctx: dict[str, Any]) -> dict[str, Any]:
    """Build the Reasoning Delta and attach to the context.

    Reads:
      - ctx.get("previous_iteration") (dict | None)
      - ctx.get("final_status") (str)
      - ctx.get("checks") (list[dict])
      - ctx.get("missing_evidence") (list[dict])
      - ctx.get("extracted") (list[ExtractedDocument])

    Writes:
      - ctx["reasoning_delta"] (dict conforming to ReasoningDelta schema)
    """
    prev: dict[str, Any] | None = ctx.get("previous_iteration")
    curr = _snapshot(ctx)

    if prev is None:
        delta = {
            "kind": "INITIAL",
            "changes": [],
            "narrative": (
                f"Initial baseline assessment completed. Evaluated {len(curr['documents'])} trade documents. "
                f"Status: {curr['status']}."
            ),
        }
    else:
        changes: list[dict[str, Any]] = []

        # 1. Status transition check
        prev_status = prev.get("status")
        curr_status = curr.get("status")
        if prev_status != curr_status:
            reason = ctx.get("status_reason")
            if not reason:
                if prev_status == "MISSING_EVIDENCE" and curr_status == "COMPLIANT_FOR_SUBMISSION":
                    reason = "Uploaded corrective document satisfied all mandatory regulatory tariff requirements."
                elif curr_status == "MATERIAL_CONTRADICTION":
                    reason = "Mathematical discrepancy or entity conflict detected exceeding allowable tolerance."
                else:
                    reason = "Document evidence modified assessment result."

            changes.append({
                "field": "status",
                "from": str(prev_status),
                "to": str(curr_status),
                "because": reason,
            })

        # 2. Missing evidence resolution check
        prev_missing = {m.get("id"): m for m in prev.get("missing_evidence", [])}
        curr_missing = {m.get("id"): m for m in curr.get("missing_evidence", [])}

        for resolved_id, resolved_item in prev_missing.items():
            if resolved_id not in curr_missing:
                doc_name = resolved_item.get("document_label", "Requested document")
                hs = resolved_item.get("hs_code", "declared HS")
                changes.append({
                    "field": f"missing_evidence.{resolved_id}",
                    "from": "REQUIRED",
                    "to": "SATISFIED",
                    "because": f"Uploaded {doc_name} satisfies AHTN regulatory requirements for HS {hs}.",
                })

        # 3. Check severity changes
        prev_checks = {c.get("check_id"): c for c in prev.get("checks", [])}
        for check in curr.get("checks", []):
            cid = check.get("check_id")
            prev_check = prev_checks.get(cid)
            if prev_check and prev_check.get("severity") != check.get("severity"):
                changes.append({
                    "field": cid,
                    "from": prev_check.get("severity"),
                    "to": check.get("severity"),
                    "because": check.get("message", "Rule evaluation result changed."),
                })

        delta = {
            "kind": "REASSESSMENT",
            "changes": changes,
            "narrative": _narrate(changes),
        }

    ctx["reasoning_delta"] = delta
    return ctx
