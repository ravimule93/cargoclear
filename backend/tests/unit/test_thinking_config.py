"""agents/extraction.py::thinking_config: the thinking knob is per model family, measured 2026-10-16 (docs/input-gating-audit.md,
section 13): gemini-2.5-flash takes a budget (0 = off), gemini-2.5-pro cannot go below 128, gemini-3.x refuses a budget of ANY value on
a request with an image and takes a level."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from google.genai import types
from pydantic import ValidationError

from app.agents import extraction
from app.core.config import Settings, settings
from app.services import relevance
from tests.helpers import REPO_ROOT

FLASH, PRO, THREE = "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.5-flash"


def shown(config) -> tuple:
    """(budget, level name) of a ThinkingConfig, or None."""
    if config is None:
        return None
    return config.thinking_budget, getattr(config.thinking_level, "name", config.thinking_level)


@pytest.mark.parametrize(("budget", "expected"), [(0, (0, None)), (1024, (1024, None)), (-1, None), (-5, None)])
def test_2_5_flash_takes_the_budget_as_configured(monkeypatch, budget, expected) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_budget", budget)

    assert shown(extraction.thinking_config(types, FLASH)) == expected


@pytest.mark.parametrize(("budget", "expected"), [(0, 128), (1, 128), (127, 128), (128, 128), (1024, 1024), (-1, None)])
def test_2_5_pro_cannot_switch_thinking_off_so_zero_becomes_its_floor(monkeypatch, budget, expected) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_budget", budget)

    config = extraction.thinking_config(types, PRO)

    assert (None if config is None else config.thinking_budget) == expected


@pytest.mark.parametrize(("level", "expected"), [("MINIMAL", "MINIMAL"), ("LOW", "LOW"), ("MEDIUM", "MEDIUM"), ("HIGH", "HIGH"), ("DEFAULT", None)])
def test_gemini_3_takes_a_level_and_default_sends_nothing(monkeypatch, level, expected) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_level", level)

    config = extraction.thinking_config(types, THREE)

    assert (None if config is None else config.thinking_level.name) == expected
    assert config is None or config.thinking_budget is None  # a budget is refused for this family, with any value


@pytest.mark.parametrize("budget", [0, 256, 1024, -1])
def test_gemini_3_never_gets_a_budget_whatever_is_configured(monkeypatch, budget) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_budget", budget)

    config = extraction.thinking_config(types, "gemini-3.5-flash-preview")

    assert config.thinking_budget is None and config.thinking_level.name == "MINIMAL"


def test_the_default_for_gemini_3_is_the_minimal_level() -> None:
    assert Settings(_env_file=None).gemini_thinking_level == "MINIMAL"


def test_a_level_outside_the_list_is_a_startup_error() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, GEMINI_THINKING_LEVEL="EXTREME")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("model", "budget", "level", "expected"),
    [
        (FLASH, 1024, "HIGH", (0, None)), (FLASH, -1, "HIGH", None), (PRO, 1024, "HIGH", (128, None)),
        (THREE, 1024, "HIGH", (None, "MINIMAL")),
    ],
)
def test_minimal_is_as_little_as_the_model_allows_and_still_respects_not_sending(monkeypatch, model, budget, level, expected) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_budget", budget)
    monkeypatch.setattr(settings, "gemini_thinking_level", level)

    assert shown(extraction.thinking_config(types, model, minimal=True)) == expected


def test_the_extraction_request_uses_the_configured_models_knob(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_live_model", THREE)

    assert shown(extraction._request_config(types).thinking_config) == (None, "MINIMAL")


@pytest.mark.parametrize(
    ("model", "budget", "level", "text"),
    [
        (FLASH, 0, "MINIMAL", "thinking_budget=0"), (FLASH, -1, "MINIMAL", "thinking_budget=-1  (field not sent)"),
        (PRO, 0, "MINIMAL", "thinking_budget=128"), (THREE, 0, "LOW", "thinking_level=LOW"),
        (THREE, 0, "DEFAULT", "thinking_level=DEFAULT  (field not sent)"),
    ],
)
def test_the_scripts_can_say_what_is_sent(monkeypatch, model, budget, level, text) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_budget", budget)
    monkeypatch.setattr(settings, "gemini_thinking_level", level)

    assert extraction.describe_thinking(types, model) == text


# --- the relevance gate asks for as little thinking as the model allows, and leaves room for it ---


class Recorder:
    def __init__(self) -> None:
        self.configs: list = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, **kwargs):
        self.configs.append(kwargs["config"])
        return SimpleNamespace(text=json.dumps({"kind": "COMMERCIAL_INVOICE"}))


@pytest.fixture
def gate_client(monkeypatch):
    client = Recorder()
    monkeypatch.setattr(relevance, "_first_page_png", lambda _data: b"png")
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: client)
    return client


@pytest.mark.parametrize(
    ("model", "cap", "thinking"),
    [(FLASH, 24, (0, None)), (PRO, 24 + 128, (128, None)), (THREE, 24, (None, "MINIMAL"))],
)
async def test_the_gate_cap_includes_the_thinking_the_model_cannot_do_without(monkeypatch, gate_client, model, cap, thinking) -> None:
    """Thinking tokens count toward the output cap (measured): a 24-token cap with a 128-token floor would cut off the answer."""
    monkeypatch.setattr(settings, "gemini_live_model", model)
    monkeypatch.setattr(settings, "gemini_thinking_budget", 2048)
    monkeypatch.setattr(settings, "gemini_thinking_level", "HIGH")

    assert await relevance.classify_first_page(b"%PDF-") == "COMMERCIAL_INVOICE"

    [config] = gate_client.configs
    assert config.max_output_tokens == cap and shown(config.thinking_config) == thinking


# --- the deploy script and the preflight ---


def test_the_deploy_script_does_not_raise_the_output_cap() -> None:
    script = (REPO_ROOT / "infra" / "deploy_api.sh").read_text(encoding="utf-8")

    assert "65536" not in script
    assert re.search(r'^GEMINI_MAX_OUTPUT_TOKENS="\$\{GEMINI_MAX_OUTPUT_TOKENS:-16384\}"$', script, re.MULTILINE)


def test_the_preflight_sends_an_image_like_every_real_request() -> None:
    from tests.helpers import load_script

    preflight = load_script("preflight_gcp.py")

    assert preflight._BLANK_PNG.startswith(b"\x89PNG")
    source = (REPO_ROOT / "scripts" / "preflight_gcp.py").read_text(encoding="utf-8")
    assert 'Part.from_bytes(data=_BLANK_PNG, mime_type="image/png")' in source
