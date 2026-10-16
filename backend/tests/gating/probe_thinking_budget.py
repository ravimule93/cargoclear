#!/usr/bin/env python3
"""Which thinking budgets a model accepts, and what they cost, measured with tiny text-only requests (Gemini's ``usage_metadata``).
Run by a PERSON with Google Cloud credentials, never by CI. A few hundred tokens in all.

    cd backend
    .venv/bin/python -I tests/gating/probe_thinking_budget.py [MODEL ...]      (default: the two models asia-south1 serves)

Per model and budget it sends the same small classification request with the response schema the relevance gate uses, once with a
roomy output cap and once with the gate's 24-token cap, and prints: accepted or the refusal, thinking tokens, output tokens, whether the
answer survived the cap. It answers two questions item 6 of docs/input-gating-audit.md depends on: which positive budget a model that
refuses 0 accepts, and whether ``max_output_tokens`` includes the thinking tokens. Synthetic text only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from google.genai import types  # noqa: E402

from app.core import mode  # noqa: E402
from app.services import relevance  # noqa: E402
from tests.gating import harness  # noqa: E402

BUDGETS = (0, 1, 128, 512, 1024, 2048)
CAPS = (1024, 24)
PROMPT = "Page text: 'COMMERCIAL INVOICE No. 17, seller Example Steel Co, buyer Example Importer, 10 MT seamless pipe'. " + relevance.GATE_INSTRUCTION


def main(argv: list[str]) -> int:
    if mode.credential_source() is None:
        print(mode.no_credentials_message())
        return 2
    client = harness.real_vertex_client()
    schema = {"type": "OBJECT", "properties": {"kind": {"type": "STRING", "enum": list(relevance.KINDS)}}, "required": ["kind"]}
    for model in argv or ["gemini-2.5-flash", "gemini-3.5-flash"]:
        for budget in BUDGETS:
            for cap in CAPS:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema, temperature=0.0, max_output_tokens=cap,
                    thinking_config=types.ThinkingConfig(thinking_budget=budget),
                )
                row = {"model": model, "budget": budget, "cap": cap}
                try:
                    response = client.models.generate_content(model=model, contents=PROMPT, config=config)
                    usage = harness.usage_of(response)
                    candidates = getattr(response, "candidates", None) or []
                    finish = getattr(getattr(candidates[0], "finish_reason", None), "name", None) if candidates else None
                    row.update(ok=True, thoughts=usage.get("thoughts_token_count"), out=usage.get("candidates_token_count"),
                               total=usage.get("total_token_count"), finish=finish, text=(response.text or "")[:60])
                except Exception as exc:  # noqa: BLE001
                    row.update(ok=False, code=getattr(exc, "code", None), error=str(getattr(exc, "message", None) or exc)[:140])
                print("PROBE " + json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
