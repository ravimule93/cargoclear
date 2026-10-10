"""F1: the request, abuse and exposure settings: defaults from the brief, and validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.helpers import asgi_call


def make(**env: object) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[arg-type]


def test_defaults() -> None:
    fresh = make()

    assert fresh.max_upload_mb == 50 and fresh.max_upload_bytes == 50 * 1024 * 1024
    assert fresh.max_json_body_kb == 256
    assert fresh.max_documents_per_bundle == 20
    assert fresh.max_reference_chars == 200
    assert fresh.rate_limit_writes_per_minute == 60
    assert fresh.rate_limit_runs_per_minute == 10
    assert fresh.max_concurrent_runs == 4
    assert fresh.trust_forwarded_for is False
    assert fresh.enable_api_docs is None


def test_values_come_from_the_documented_environment_names() -> None:
    fresh = make(
        MAX_UPLOAD_MB=10, MAX_JSON_BODY_KB=64, MAX_DOCUMENTS_PER_BUNDLE=5, MAX_REFERENCE_CHARS=80,
        RATE_LIMIT_WRITES_PER_MINUTE=30, RATE_LIMIT_RUNS_PER_MINUTE=3, MAX_CONCURRENT_RUNS=2,
        TRUST_FORWARDED_FOR="true", ENABLE_API_DOCS="false",
    )

    assert (fresh.max_upload_mb, fresh.max_json_body_kb, fresh.max_documents_per_bundle, fresh.max_reference_chars) == (10, 64, 5, 80)
    assert (fresh.rate_limit_writes_per_minute, fresh.rate_limit_runs_per_minute, fresh.max_concurrent_runs) == (30, 3, 2)
    assert fresh.trust_forwarded_for is True and fresh.enable_api_docs is False


@pytest.mark.parametrize("name", ["MAX_UPLOAD_MB", "MAX_JSON_BODY_KB"])
@pytest.mark.parametrize("value", [0, -1, -0.5])
def test_sizes_must_be_positive(name, value) -> None:
    with pytest.raises(ValidationError):
        make(**{name: value})


@pytest.mark.parametrize("name", ["MAX_DOCUMENTS_PER_BUNDLE", "MAX_REFERENCE_CHARS"])
@pytest.mark.parametrize("value", [0, -3])
def test_counts_must_be_at_least_one(name, value) -> None:
    with pytest.raises(ValidationError):
        make(**{name: value})


@pytest.mark.parametrize("name", ["RATE_LIMIT_WRITES_PER_MINUTE", "RATE_LIMIT_RUNS_PER_MINUTE", "MAX_CONCURRENT_RUNS"])
def test_zero_is_allowed_to_switch_a_limit_off_but_negative_is_not(name) -> None:
    assert make(**{name: 0}) is not None
    with pytest.raises(ValidationError):
        make(**{name: -1})


def test_the_env_example_lists_every_new_setting() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    for name in (
        "MAX_UPLOAD_MB=50", "MAX_JSON_BODY_KB=256", "MAX_DOCUMENTS_PER_BUNDLE=20", "MAX_REFERENCE_CHARS=200",
        "RATE_LIMIT_WRITES_PER_MINUTE=60", "RATE_LIMIT_RUNS_PER_MINUTE=10", "MAX_CONCURRENT_RUNS=4",
        "TRUST_FORWARDED_FOR=false", "# ENABLE_API_DOCS=",
    ):
        assert name in text, name


@pytest.mark.asyncio
async def test_errors_raised_by_the_guards_still_carry_the_cors_headers(monkeypatch) -> None:
    """The guards sit inside CORS, so a browser on an allowed origin can read the 404 / 413 / 429 it gets."""
    from app.core.config import settings

    origin = {"origin": "http://localhost:3000"}
    monkeypatch.setattr(settings, "max_json_body_kb", 1)
    monkeypatch.setattr(settings, "rate_limit_writes_per_minute", 2)  # the refused-as-too-large request spends one

    not_found = await asgi_call("GET", "/api/v1/bundles/bnd-nope", headers=origin)
    too_large = await asgi_call("POST", "/api/v1/bundles", body=b"x" * 2048, headers={**origin, "content-type": "application/json"})
    allowed = await asgi_call("POST", "/api/v1/bundles", body=b"{}", headers={**origin, "content-type": "application/json"})
    limited = await asgi_call("POST", "/api/v1/bundles", body=b"{}", headers={**origin, "content-type": "application/json"})

    assert (not_found.status, too_large.status, allowed.status, limited.status) == (404, 413, 201, 429)
    for result in (not_found, too_large, allowed, limited):
        assert result.headers["access-control-allow-origin"] == "http://localhost:3000"
