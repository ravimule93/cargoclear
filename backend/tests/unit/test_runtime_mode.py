"""Unit tests for Requirement A: Runtime AI Model and Execution Mode Switching.

Verifies:
- GET /api/v1/mode returns active_mode, supported_modes, model, provider, region, and availability.
- POST /api/v1/mode switches between demo and live mode at runtime without server restart.
- Invalid modes (e.g. 'unsupported_mode') are rejected with validation error.
- Switching to live mode without credentials returns an actionable UpstreamError and does not claim live.
- Mode preference is persisted via cookie and honored on subsequent requests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import mode
from app.core.config import settings
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_get_mode_returns_status_and_configured_model(client: TestClient) -> None:
    response = client.get("/api/v1/mode")
    assert response.status_code == 200
    data = response.json()
    assert data["active_mode"] in ("demo", "live")
    assert "demo" in data["supported_modes"]
    assert "live" in data["supported_modes"]
    assert data["provider"] == "Google Cloud Vertex AI"
    assert data["model"] == settings.gemini_live_model
    assert data["region"] == settings.gemini_live_location


def test_get_mode_reports_active_model_and_connectivity(client: TestClient) -> None:
    response = client.get("/api/v1/mode")
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == settings.gemini_live_model
    assert "active_mode" in data
    assert "supported_modes" in data


def test_switch_to_demo_mode_succeeds_and_sets_cookie(client: TestClient) -> None:
    response = client.post("/api/v1/mode", json={"mode": "demo"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_mode"] == "demo"
    assert "cargoclear_execution_mode=demo" in response.headers.get("set-cookie", "")


def test_switch_to_invalid_mode_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/mode", json={"mode": "invalid_mode"})
    assert response.status_code in (400, 422)


def test_switch_to_live_mode_without_credentials_fails_actionably_and_never_fakes_live(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mode, "credential_source", lambda: None)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)

    response = client.post("/api/v1/mode", json={"mode": "live"})
    # Must fail with an upstream error explaining missing credentials
    assert response.status_code == 502
    data = response.json()
    assert "Cannot activate Live AI Mode" in data.get("message", "")
    assert "detail" in data
    assert data["detail"]["requested_mode"] == "live"


def test_switch_to_live_mode_with_credentials_succeeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mode, "credential_source", lambda: "mock_test_credentials")

    response = client.post("/api/v1/mode", json={"mode": "live"})
    assert response.status_code == 200
    data = response.json()
    assert data["active_mode"] == "live"
    assert data["live_available"] is True
    assert "cargoclear_execution_mode=live" in response.headers.get("set-cookie", "")


def test_cookie_mode_is_honored_on_subsequent_get(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = client.get("/api/v1/mode", cookies={"cargoclear_execution_mode": "demo"})
    assert response.status_code == 200
    assert response.json()["active_mode"] == "demo"
