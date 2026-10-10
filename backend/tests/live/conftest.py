"""Fixtures for the live smoke test.

tests/conftest.py's autouse ``hermetic_test_env`` forces APP_MODE=demo and strips every credential, which is exactly
right for the offline suite and exactly wrong here: this directory talks to the real Gemini endpoint, so it must see
the environment as the person running it set it. The same-named fixture below replaces the hermetic one for this
directory only.
"""

import pytest


@pytest.fixture(autouse=True)
def hermetic_test_env():
    yield
