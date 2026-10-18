"""Normal local startup requires sign-in; anonymous fixture access is an explicit opt-out."""

from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import create_app


def test_default_configuration_reports_authentication_and_blocks_unsigned_bundle_creation(monkeypatch):
    # The hermetic fixture deliberately opts out. Remove only that environment override
    # when checking the application default; do not read the developer's .env file.
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    configured = Settings(_env_file=None)
    assert configured.auth_enabled is True
    monkeypatch.setattr(settings, "auth_enabled", configured.auth_enabled)

    client = TestClient(create_app())
    metadata = client.get("/api/v1/meta")
    assert metadata.status_code == 200
    assert metadata.json()["auth"]["enabled"] is True
    assert metadata.json()["user"] is None

    response = client.post(
        "/api/v1/bundles",
        json={"reference": "AUTH-DEFAULT-REGRESSION", "destination_country": "SG"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert response.json()["message"] == "A verified end-user session is required."


def test_explicit_authentication_opt_out_preserves_anonymous_demo_fixture_workflows(monkeypatch):
    configured = Settings(_env_file=None, AUTH_ENABLED="false")
    assert configured.auth_enabled is False
    monkeypatch.setattr(settings, "auth_enabled", configured.auth_enabled)

    client = TestClient(create_app())
    metadata = client.get("/api/v1/meta")
    assert metadata.status_code == 200
    assert "auth" not in metadata.json()

    response = client.post(
        "/api/v1/bundles",
        json={"reference": "EXPLICIT-ANONYMOUS-FIXTURE", "destination_country": "SG"},
    )
    assert response.status_code == 201
    assert response.json()["reference"] == "EXPLICIT-ANONYMOUS-FIXTURE"
