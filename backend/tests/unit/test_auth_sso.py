"""Unit tests for backend SSO authentication, JWT validation, and multi-tenancy."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.auth import UserIdentity
from app.gateway.auth import get_current_user
from app.main import create_app


def test_user_identity_from_claims():
    """Verify tenant derivation from email domain."""
    claims = {
        "email": "agent.smith@customs.com",
        "sub": "google-sub-12345",
        "name": "Smith Agent",
        "iss": "https://accounts.google.com",
    }
    user = UserIdentity.from_claims(claims)
    assert user.email == "agent.smith@customs.com"
    assert user.tenant_id == "customs.com"
    assert user.role == "LICENSED_CHA"
    assert user.name == "Smith Agent"


def test_user_identity_mock():
    """Verify mock commercial CHA identity."""
    mock_user = UserIdentity.mock_commercial_cha(email="broker@dhl.com")
    assert mock_user.email == "broker@dhl.com"
    assert mock_user.tenant_id == "dhl.com"
    assert mock_user.role == "LICENSED_CHA"


def test_meta_endpoint_includes_auth_info(monkeypatch):
    """Verify GET /meta exposes auth configuration and current user context when auth_enabled=True."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "demo")

    app = create_app()
    client = TestClient(app)

    # Without token: auth config is exposed, user is None
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    data = response.json()
    assert "auth" in data
    assert data["auth"]["enabled"] is True
    assert data["user"] is None

    # With token: user is populated
    headers = {"Authorization": "Bearer mock-jwt-demo-cha@customs.com-LICENSED_CHA"}
    auth_resp = client.get("/api/v1/meta", headers=headers)
    assert auth_resp.status_code == 200
    auth_data = auth_resp.json()
    assert auth_data["user"] is not None
    assert auth_data["user"]["email"] == "demo-cha@customs.com"
    assert auth_data["user"]["tenant_id"] == "customs.com"



def test_bundle_creation_tags_tenant_and_user(monkeypatch):
    """Verify POST /bundles stores tenant_id and created_by."""
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "app_mode", "demo")

    app = create_app()
    client = TestClient(app)

    headers = {"X-Test-User-Email": "priya@customs.com"}
    response = client.post(
        "/api/v1/bundles",
        json={"reference": "TEST-SSO-REF", "destination_country": "SG"},
        headers=headers,
    )
    assert response.status_code == 201
    bundle = response.json()
    assert bundle["tenant_id"] == "customs.com"
    assert bundle["created_by"] == "priya@customs.com"


def test_auth_enabled_requires_bearer_token(monkeypatch):
    """When AUTH_ENABLED=True, missing Authorization header returns 401."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "demo")

    app = create_app()
    client = TestClient(app)

    # Missing header -> 401
    resp_no_token = client.post("/api/v1/bundles", json={"reference": "TEST-1", "destination_country": "SG"})
    assert resp_no_token.status_code == 401
    envelope = resp_no_token.json()
    assert envelope["code"] == "UNAUTHORIZED"

    # Simulated valid mock token for testing
    headers = {"Authorization": "Bearer mock-jwt-clerk@customs.com-LICENSED_CHA"}
    resp_with_token = client.post(
        "/api/v1/bundles",
        json={"reference": "TEST-1", "destination_country": "SG"},
        headers=headers,
    )
    assert resp_with_token.status_code == 201
    assert resp_with_token.json()["tenant_id"] == "customs.com"


def test_domain_restriction_enforcement(monkeypatch):
    """When ALLOWED_EMAIL_DOMAINS is restricted, unauthorized domains return 403."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "demo")
    monkeypatch.setattr(settings, "allowed_email_domains", "customs.com,genpact.com")

    app = create_app()
    client = TestClient(app)

    # Authorized domain
    resp_allowed = client.post(
        "/api/v1/bundles",
        json={"reference": "TEST-ALLOWED", "destination_country": "SG"},
        headers={"Authorization": "Bearer mock-jwt-user@customs.com-LICENSED_CHA"},
    )
    assert resp_allowed.status_code == 201

    # Unauthorized domain
    resp_forbidden = client.post(
        "/api/v1/bundles",
        json={"reference": "TEST-BLOCKED", "destination_country": "SG"},
        headers={"Authorization": "Bearer mock-jwt-bad@unauthorized.org-LICENSED_CHA"},
    )
    assert resp_forbidden.status_code == 403
    assert resp_forbidden.json()["code"] == "FORBIDDEN"

