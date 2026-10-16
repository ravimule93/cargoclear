"""What the model calls of a run cost, per document, as the API reported it: the answer to "where did the tokens go?" after the fact.

Every request to Gemini is recorded as an ATTEMPT, whatever became of it:

  ok               the answer was read
  refused: <why>   the model answered and the answer was not used (cut off at the output cap, empty, not JSON, failed validation,
                   blocked): the tokens were spent all the same, which is the cost this record exists to show
  error: <why>     the call failed before an answer (429, 5xx, timeout, dropped connection): the API reports nothing, so the attempt is
                   counted but its tokens are unknown (``unknown_requests``); a timed-out request may still have been billed
  cancelled        the run was cancelled, or a sibling document failed, while the request was in flight: likewise unknown

A document whose answer was read again from the extraction cache (agents/extraction.py) made no request: it is listed as cached with
what its first read cost (``saved_tokens``). The relevance gate's request at upload (services/relevance.py) is recorded on the document
(``gate_usage``) and shown per document, once: it is not part of any run's totals.

Counts are what Gemini reports (``usage_metadata``): prompt, candidates (output), thoughts (thinking) and its own total. No price is
computed here: a price per token is not something this repository verifies.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any

NOTE = (
    "Counts are what the API reported for each request. A request that failed before an answer (timeout, 429, 5xx) or was cancelled "
    "reports nothing: it is counted in unknown_requests, and a timed-out request may still have been billed. A cached document made no "
    "request; saved_tokens is what its first read cost. gate_tokens is the relevance check at upload, spent once and not part of a run."
)

# The log of the run that is extracting right now; the extraction code appends to it without being handed it.
CURRENT: contextvars.ContextVar[UsageLog | None] = contextvars.ContextVar("token_usage_log", default=None)


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def usage_of(response: Any) -> dict[str, int] | None:
    """The usage a Gemini response reports, or None when it reports none. ``total`` is Gemini's own total when it gives one."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    prompt = _count(getattr(meta, "prompt_token_count", None))
    output = _count(getattr(meta, "candidates_token_count", None))
    thinking = _count(getattr(meta, "thoughts_token_count", None))
    reported_total = getattr(meta, "total_token_count", None)
    total = _count(reported_total) if isinstance(reported_total, int) else prompt + output + thinking
    return {"prompt_tokens": prompt, "output_tokens": output, "thinking_tokens": thinking, "total_tokens": total}


def empty_gate_usage() -> dict[str, int]:
    return {"requests": 0, "unknown_requests": 0, "prompt_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "total_tokens": 0}


@dataclass
class UsageLog:
    """The attempts of one run (and the documents it did not have to read), appended to as they happen so that a run that fails or is
    cancelled still has its record."""

    attempts: list[dict[str, Any]] = field(default_factory=list)
    saved: dict[str, int] = field(default_factory=dict)  # document id -> what its first read cost (a document served from the cache)

    def record(
        self, document_id: str, attempt: int, outcome: str, usage: dict[str, int] | None, finish_reason: str | None = None
    ) -> None:
        self.attempts.append({
            "document_id": document_id, "attempt": attempt, "outcome": outcome, "finish_reason": finish_reason,
            "usage_reported": usage is not None,
            **(usage or {"prompt_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "total_tokens": 0}),
        })

    def record_cached(self, document_id: str, saved_tokens: int) -> None:
        self.saved[document_id] = saved_tokens

    def summary(self, *, model: str | None, documents: list[dict[str, Any]], mode: str | None) -> dict[str, Any]:
        """The record in the shape of ``TokenUsage`` (domain/schemas.py). ``documents`` are the bundle's document records, in order."""
        order = [str(d["document_id"]) for d in documents if d.get("document_id")]
        order += [doc for doc in dict.fromkeys([a["document_id"] for a in self.attempts] + list(self.saved)) if doc not in order]
        by_id = {str(d["document_id"]): d for d in documents if d.get("document_id")}
        rows: list[dict[str, Any]] = []
        for document_id in order:
            made = [a for a in self.attempts if a["document_id"] == document_id]
            if not made and document_id not in self.saved and not (by_id.get(document_id) or {}).get("gate_usage"):
                continue  # a document this run neither asked about nor served from the cache, with no gate request: nothing to say
            gate = (by_id.get(document_id) or {}).get("gate_usage") or None
            rows.append({
                "document_id": document_id,
                "filename": (by_id.get(document_id) or {}).get("filename"),
                "cached": document_id in self.saved and not made,
                "requests": len(made),
                "failed_requests": sum(1 for a in made if a["outcome"] != "ok"),
                "unknown_requests": sum(1 for a in made if not a["usage_reported"]),
                "prompt_tokens": sum(a["prompt_tokens"] for a in made),
                "output_tokens": sum(a["output_tokens"] for a in made),
                "thinking_tokens": sum(a["thinking_tokens"] for a in made),
                "total_tokens": sum(a["total_tokens"] for a in made),
                "saved_tokens": self.saved.get(document_id, 0) if not made else 0,
                "gate_tokens": gate["total_tokens"] if gate else None,
                "attempts": [
                    {k: a[k] for k in ("attempt", "outcome", "finish_reason", "usage_reported", "prompt_tokens", "output_tokens",
                                       "thinking_tokens", "total_tokens")}
                    for a in made
                ],
            })
        ask = [row for row in rows if row["requests"]]
        return {
            "model": model if (self.attempts or self.saved) else None,
            "mode": mode,
            "requests": sum(r["requests"] for r in rows),
            "failed_requests": sum(r["failed_requests"] for r in rows),
            "unknown_requests": sum(r["unknown_requests"] for r in rows),
            "cached_documents": sum(1 for r in rows if r["cached"]),
            "prompt_tokens": sum(r["prompt_tokens"] for r in ask),
            "output_tokens": sum(r["output_tokens"] for r in ask),
            "thinking_tokens": sum(r["thinking_tokens"] for r in ask),
            "total_tokens": sum(r["total_tokens"] for r in ask),
            "saved_tokens": sum(r["saved_tokens"] for r in rows),
            "documents": rows,
            "note": NOTE,
        }


TOTAL_KEYS = ("requests", "failed_requests", "unknown_requests", "cached_documents", "prompt_tokens", "output_tokens", "thinking_tokens",
              "total_tokens", "saved_tokens")


def totals_of(summary: dict[str, Any] | None) -> dict[str, int] | None:
    """The run's totals without the per-document rows (small enough for an audit event), or None when the run made no request and
    served nothing from the cache."""
    if not summary or not (summary.get("requests") or summary.get("cached_documents")):
        return None
    return {key: int(summary.get(key) or 0) for key in TOTAL_KEYS}
