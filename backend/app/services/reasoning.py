"""Reasoning Delta builder.

Computes a structured before/after diff between consecutive assessment
iterations and generates a human-readable narrative.

Per v4.0 §5 (Epic 5, US 5.2):
  Side-by-side view with explicit "Changed because…" explanation.
  Example: "DOC-04 Mill Test Certificate satisfies AHTN requirement for HS 7304"
"""

from __future__ import annotations


def _snapshot(ctx: dict) -> dict:
    """Extract a comparable snapshot from the current pipeline context."""
    return {
        "status": ctx.get("final_status", "COMPLIANT_FOR_SUBMISSION"),
        "checks": ctx.get("checks", []),
        "documents": [d for d in ctx.get("documents", [])],
        "missing_evidence": ctx.get("missing_evidence", []),
    }


def _narrate(changes: list[dict]) -> str:
    """Build a human-readable narrative from a list of field changes."""
    if not changes:
        return "No material change between iterations."
    parts = []
    for c in changes:
        parts.append(f"{c['field']}: {c['from']} → {c['to']} because {c['because']}")
    return " | ".join(parts)


async def build(ctx: dict) -> dict:
    """Build the Reasoning Delta and attach it to the context.

    Reads:  ctx["previous_iteration"]  (dict | None — previous snapshot)
            ctx["final_status"]
            ctx["checks"]
            ctx["missing_evidence"]
            ctx.get("status_reason")   (optional human-readable reason for status change)
    Writes: ctx["reasoning_delta"]     (dict conforming to ReasoningDelta schema)
    """
    prev: dict | None = ctx.get("previous_iteration")
    curr = _snapshot(ctx)

    if prev is None:
        delta = {
            "kind": "INITIAL",
            "changes": [],
            "narrative": "First assessment of this bundle.",
        }
    else:
        changes: list[dict] = []

        # Status change
        if prev["status"] != curr["status"]:
            changes.append({
                "field": "status",
                "from": prev["status"],
                "to": curr["status"],
                "because": ctx.get(
                    "status_reason",
                    "New evidence or calculation result changed the compliance status.",
                ),
            })

        # Check severity changes
        prev_checks = {c["check_id"]: c for c in prev.get("checks", [])}
        for check in curr["checks"]:
            prev_check = prev_checks.get(check["check_id"])
            if prev_check and prev_check["severity"] != check["severity"]:
                changes.append({
                    "field": check["check_id"],
                    "from": prev_check["severity"],
                    "to": check["severity"],
                    "because": check.get("message", ""),
                })

        # Missing evidence resolved
        prev_missing = {m.get("id") for m in prev.get("missing_evidence", [])}
        curr_missing = {m.get("id") for m in curr["missing_evidence"]}
        for resolved_id in prev_missing - curr_missing:
            changes.append({
                "field": f"missing_evidence.{resolved_id}",
                "from": "REQUIRED",
                "to": "SATISFIED",
                "because": "Document was uploaded and validated.",
            })

        delta = {
            "kind": "REASSESSMENT",
            "changes": changes,
            "narrative": _narrate(changes),
        }

    ctx["reasoning_delta"] = delta
    return ctx
