"""Shared pieces for the ADK tests. Every module here starts with ``require_adk()``, so in the default venv (which does
not have google-adk) the module is skipped with a clear reason instead of failing to import."""

from __future__ import annotations

import pytest

SKIP_REASON = (
    "google-adk is not installed in this interpreter: run these with the ADK lock "
    "(backend/.venv-adk/bin/python -m pytest tests/adk; see requirements-adk.txt)"
)


def require_adk() -> None:
    pytest.importorskip("google.adk", reason=SKIP_REASON)
