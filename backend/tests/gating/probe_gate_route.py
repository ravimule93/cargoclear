#!/usr/bin/env python3
"""The relevance gate as built (services/relevance.py), through the real upload route and the real Gemini endpoint. Run by a PERSON
with Google Cloud credentials, never by CI. A few small requests (about 1,900 tokens each; files the text layer names cost none).

    cd backend
    .venv/bin/python -I tests/gating/probe_gate_route.py

Each fixture is uploaded as an invoice into a fresh bundle; the output says the HTTP status, the message and what the gate's request
(if one was made) cost, from Gemini's own ``usage_metadata``. Storage and Firestore are the local stand-ins (nothing is written to a
Google Cloud project). Synthetic documents only.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core import mode  # noqa: E402
from app.core.config import settings  # noqa: E402
from tests.gating import harness  # noqa: E402
from tests.helpers import api_client  # noqa: E402

FILES = (
    "f01_clean/commercial_invoice.pdf", "f12_non_english_invoice.pdf", "f04c_invoice_terms_then_table.pdf",
    "f02a_resume_as_invoice.pdf", "f02b_bank_statement_as_invoice.pdf", "f11_scanned_invoice.pdf",
)


async def main_async() -> int:
    settings.app_mode = "demo"
    settings.local_storage_path = tempfile.mkdtemp(prefix="gate-route-")
    settings.rate_limit_writes_per_minute = 0
    meter = harness.install_meter(harness.real_vertex_client())
    async with api_client() as client:
        for name in FILES:
            before = len(meter.calls)
            created = await client.post("/api/v1/bundles", json={"reference": "GATE", "destination_country": "SG"})
            upload = await harness.upload(client, created.json()["id"], "commercial_invoice.pdf", harness.fixture(name))
            calls = meter.calls[before:]
            usage = [c.get("usage") or {} for c in calls]
            print("ROUTE " + json.dumps({
                "file": name, "status": upload.status, "message": upload.message, "requests": len(calls),
                "tokens": [(u.get("prompt_token_count"), u.get("candidates_token_count"), u.get("total_token_count")) for u in usage],
            }), flush=True)
    return 0


def main() -> int:
    if mode.credential_source() is None:
        print(mode.no_credentials_message())
        return 2
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
