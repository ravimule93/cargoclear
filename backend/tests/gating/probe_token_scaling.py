#!/usr/bin/env python3
"""How the prompt tokens of ONE extraction request grow with the number of page images in it, measured with Gemini's ``count_tokens``
(no generation, no output tokens). Run by a PERSON with Google Cloud credentials, never by CI.

    cd backend
    .venv/bin/python -I tests/gating/probe_token_scaling.py

The pages are the product's own: ``preprocess.run`` renders a fixture exactly as the pipeline does, and the request parts are built
by the product's own ``extraction._build_parts`` (a "Page N of M." label before each image, the instruction after). Counts for 1, 2,
4, 8, 16 and 30 pages of the same fixture, and for the 30 distinct pages of the dense-table fixture.

    synthetic documents only
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parents[1]
FIXTURES = HERE.parent / "fixtures" / "gating"
sys.path.insert(0, str(BACKEND_DIR))

from google.genai import types  # noqa: E402

from app.agents import extraction  # noqa: E402
from app.core import mode  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import preprocess  # noqa: E402
from tests.gating import harness  # noqa: E402


def count(client, pages: list[dict]) -> dict:
    parts, _ = extraction._build_parts(types, pages)
    config = types.CountTokensConfig(system_instruction=extraction.SYSTEM_INSTRUCTION)
    result = client.models.count_tokens(model=settings.gemini_live_model, contents=[types.Content(role="user", parts=parts)], config=config)
    details = {}
    for item in getattr(result, "prompt_tokens_details", None) or []:
        details[getattr(item.modality, "name", str(item.modality))] = item.token_count
    return {"total_tokens": result.total_tokens, "by_modality": details}


async def render(name: str) -> list[dict]:
    result = await preprocess.run({"raw_bytes": (FIXTURES / name).read_bytes(), "document_id": name})
    return result["processed_pages"]


def main() -> int:
    if mode.credential_source() is None:
        print(mode.no_credentials_message())
        return 2
    client = harness.real_vertex_client()
    rows = []
    invoice = asyncio.run(render("f01_clean/commercial_invoice.pdf"))
    for n in (1, 2, 4, 8, 16, 30):
        pages = [{**invoice[0], "page": i, "source_page": i} for i in range(1, n + 1)]
        row = {"pages": n, "fixture": "the same invoice page repeated", **count(client, pages)}
        rows.append(row)
        print("COUNT " + json.dumps(row), flush=True)
    dense = asyncio.run(render("f16_worst_case_30_dense_pages.pdf"))
    row = {"pages": len(dense), "fixture": "f16 dense tables, 30 distinct pages", **count(client, dense)}
    rows.append(row)
    print("COUNT " + json.dumps(row), flush=True)
    terms = asyncio.run(render("f04b_invoice_plus_15_pages_terms.pdf"))
    row = {"pages": len(terms), "fixture": "f04b invoice + 15 pages of terms", **count(client, terms)}
    rows.append(row)
    print("COUNT " + json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
