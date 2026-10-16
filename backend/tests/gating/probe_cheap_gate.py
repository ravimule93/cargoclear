#!/usr/bin/env python3
"""What a cheap vision gate would cost, measured: ONE small request per fixture that sees only page 1 at 100 DPI and may answer
only with a document type from a fixed list (max 24 output tokens, no thinking). Run by a PERSON with Google Cloud credentials,
never by CI. Prototype for docs/input-gating-audit.md; nothing in ``app/`` is changed.

    cd backend
    .venv/bin/python -I tests/gating/probe_cheap_gate.py

It answers two questions the audit's fix list depends on: how many tokens does the gate itself spend (``usage_metadata``, per
request), and does it keep the legitimate documents (the four clean ones, the scan, the Chinese invoice) while turning the
irrelevant ones (resume, bank statement) away. A fixture's own page 1 only: a prompt injection on it can at most pick another word
from the list.

    synthetic documents only
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parents[1]
FIXTURES = HERE.parent / "fixtures" / "gating"
sys.path.insert(0, str(BACKEND_DIR))

from google.genai import types  # noqa: E402
from pdf2image import convert_from_bytes  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.core import mode  # noqa: E402
from app.core.config import settings  # noqa: E402
from tests.gating import harness  # noqa: E402

KINDS = ("COMMERCIAL_INVOICE", "BILL_OF_LADING", "PACKING_LIST", "MILL_TEST_CERTIFICATE", "CERTIFICATE_OF_ORIGIN", "PHYTOSANITARY", "OTHER")
INSTRUCTION = "Which kind of shipping document is the page? Answer with one word from the list. OTHER if it is none of them."
FILES = (
    "f01_clean/commercial_invoice.pdf", "f01_clean/bill_of_lading.pdf", "f01_clean/packing_list.pdf", "f01_clean/mtc_pipe_test_cert.pdf",
    "f02a_resume_as_invoice.pdf", "f02b_bank_statement_as_invoice.pdf", "f11_scanned_invoice.pdf", "f12_non_english_invoice.pdf",
    "f04b_invoice_plus_15_pages_terms.pdf", "f05_visible_injection.pdf",
)


class Gate(BaseModel):
    kind: str


def page_one(name: str) -> bytes:
    image = convert_from_bytes((FIXTURES / name).read_bytes(), dpi=100, first_page=1, last_page=1, fmt="png")[0].convert("L")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def main() -> int:
    if mode.credential_source() is None:
        print(mode.no_credentials_message())
        return 2
    client = harness.real_vertex_client()
    schema = {"type": "OBJECT", "properties": {"kind": {"type": "STRING", "enum": list(KINDS)}}, "required": ["kind"]}
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.0,
                                         max_output_tokens=24, thinking_config=types.ThinkingConfig(thinking_budget=0))
    for name in FILES:
        png = page_one(name)
        contents = [types.Part.from_bytes(data=png, mime_type="image/png"), types.Part.from_text(text=INSTRUCTION)]
        response = client.models.generate_content(model=settings.gemini_live_model, contents=contents, config=config)
        usage = harness.usage_of(response)
        try:
            answer = json.loads(response.text)["kind"]
        except Exception:  # noqa: BLE001
            answer = f"unreadable: {response.text!r}"
        print("GATE " + json.dumps({"file": name, "answer": answer, "page_png_bytes": len(png), **usage}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
