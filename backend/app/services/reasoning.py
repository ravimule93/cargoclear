"""Reasoning Delta service — before/after iteration differential builder.

Per v4.0 Specification (Epic 5, US 5.2 & hardening requirements):
  - Detects status transitions (e.g., MISSING_EVIDENCE -> COMPLIANT_FOR_SUBMISSION).
  - Pinpoints newly uploaded documents and cites their filename and doc_type.
  - Pinpoints satisfied missing evidence requirements with exact document provenance.
  - Highlights check severity improvements (e.g., MATERIAL -> PASS).
  - Synthesizes a transparent, human-readable narrative for the Custom House Agent.
"""

from __future__ import annotations

from typing import Any



# Missing-evidence ids are "ME-CORE-<DOCTYPE>" (baseline documents) or "ME-<DOCTYPE>" (tariff-driven).
_REQUIREMENT_PREFIXES = ("ME-CORE-", "ME-")  # longest first: "ME-CORE-X" also starts with "ME-"


def requirement_doc_type(requirement_id: str) -> str | None:
    """Exact document type a missing-evidence id asks for, or None if the id has no such form."""
    for prefix in _REQUIREMENT_PREFIXES:
        if requirement_id.startswith(prefix):
            return requirement_id[len(prefix):] or None
    return None


def refresh_doc_types(ctx: dict[str, Any]) -> None:
    """Copy each extracted document's doc_type onto the matching ctx["documents"] record.

    The records loaded at the start of a run say "UNKNOWN" until classification. In demo mode the
    in-memory store happens to share those dicts with the extractor's updates; on Firestore it does not,
    so the classification is applied here explicitly instead of relying on aliasing.
    """
    extracted_types = {
        getattr(d, "document_id", None): getattr(d, "doc_type", None) for d in ctx.get("extracted", [])
    }
    for doc in ctx.get("documents", []):
        if not isinstance(doc, dict):
            continue
        doc_type = extracted_types.get(doc.get("document_id"))
        if doc_type:
            doc["doc_type"] = doc_type


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
            explanations.append(f"Evidence requirement {field.replace('missing_evidence.', '')}: {because}")
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
      - ctx.get("documents") (list[dict])
      - ctx.get("extracted") (list[ExtractedDocument])

    Writes:
      - ctx["reasoning_delta"] (dict conforming to ReasoningDelta schema)
    """
    refresh_doc_types(ctx)

    prev: dict[str, Any] | None = ctx.get("previous_iteration")
    curr = _snapshot(ctx)
    curr_docs = ctx.get("documents", [])

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

        # Find newly added documents in this iteration
        prev_doc_ids = set(prev.get("documents", []))
        newly_added_docs = [
            d for d in curr_docs
            if isinstance(d, dict) and d.get("document_id") not in prev_doc_ids
        ]

        # 1. Missing evidence resolution check
        prev_missing = {m.get("id"): m for m in prev.get("missing_evidence", [])}
        curr_missing = {m.get("id"): m for m in curr.get("missing_evidence", [])}

        resolved_types: set[str] = set()
        for resolved_id, resolved_item in prev_missing.items():
            if resolved_id in curr_missing:
                continue
            label = resolved_item.get("document_label", "Requested document")
            hs = resolved_item.get("hs_code", "declared HS")

            # Credit a newly added document only if its type is exactly the type the requirement asks for.
            required_type = requirement_doc_type(str(resolved_id))
            if required_type:
                resolved_types.add(required_type)
            matching_new_doc = next(
                (d for d in newly_added_docs if required_type and d.get("doc_type") == required_type),
                None,
            )

            if matching_new_doc:
                fname = matching_new_doc.get("filename", "uploaded file")
                because_msg = f"Uploaded {fname} ({required_type}) satisfies requirement '{label}' for HS {hs}."
            else:
                because_msg = f"Requirement for {label} is no longer triggered."

            changes.append({
                "field": f"missing_evidence.{resolved_id}",
                "from": "REQUIRED",
                "to": "SATISFIED",
                "because": because_msg,
            })

        # 2. Status transition check
        prev_status = prev.get("status")
        curr_status = curr.get("status")
        if prev_status != curr_status:
            reason = ctx.get("status_reason")
            if not reason:
                # Cite new documents only if their type is one a resolved requirement asked for.
                cited_docs = [d for d in newly_added_docs if d.get("doc_type") in resolved_types]
                if curr_status == "MATERIAL_CONTRADICTION":
                    reason = "Mathematical discrepancy or entity conflict detected exceeding allowable tolerance."
                elif cited_docs:
                    doc_cites = ", ".join(f"{d.get('filename')} ({d.get('doc_type')})" for d in cited_docs)
                    reason = f"Uploaded new document(s) {doc_cites} resolved pending compliance issues."
                else:
                    reason = "Assessment inputs changed."

            changes.append({
                "field": "status",
                "from": str(prev_status),
                "to": str(curr_status),
                "because": reason,
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
