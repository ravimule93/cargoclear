"""LIVE smoke test: the real Gemini endpoint reads the four Case C sample PDFs. Run by a PERSON, never by CI.

    cd backend
    RUN_LIVE_SMOKE=1 APP_MODE=live .venv/bin/python -m pytest tests/live -m live -o addopts="" -v -s

It costs a few cents and needs Google Cloud credentials (GOOGLE_APPLICATION_CREDENTIALS, or
`gcloud auth application-default login`, or a Cloud Run identity). Without RUN_LIVE_SMOKE=1 it is skipped, and
`pytest tests/unit tests/integration` never collects it. The check itself is scripts/live_smoke_extraction.py
(which prints the full field-by-field table with -s); this is the same check as an assertion.

    synthetic Case C documents only: do not run it on real customer documents
"""

from __future__ import annotations

import os

import pytest

from tests.helpers import load_script

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_SMOKE") != "1",
        reason="live test: set RUN_LIVE_SMOKE=1 (and APP_MODE=live with Google Cloud credentials) to run it",
    ),
]


@pytest.mark.asyncio
async def test_gemini_reads_the_case_c_documents_correctly() -> None:
    script = load_script("live_smoke_extraction.py")
    reason = script.refusal_reason()
    if reason is not None:
        pytest.fail(f"RUN_LIVE_SMOKE=1 was set but the environment is not live: {reason}")

    report, code = await script.run_smoke(script.parse_args([]))

    assert code == 0, "live extraction did not meet the Case C expectations:\n  - " + "\n  - ".join(report["failures"])
