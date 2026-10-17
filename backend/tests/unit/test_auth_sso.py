"""Unit tests for backend SSO authentication, JWT validation, and multi-tenancy."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.domain.auth import UserIdentity
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


def test_live_mode_refuses_mock_tokens_and_service_only_requests(monkeypatch):
    """A private API must not treat a demo token or its BFF service token as a person."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "live")

    app = create_app()
    client = TestClient(app)

    mock = client.post(
        "/api/v1/bundles",
        json={"reference": "TEST-LIVE-MOCK", "destination_country": "SG"},
        headers={"Authorization": "Bearer mock-jwt-demo-cha@customs.com-LICENSED_CHA"},
    )
    service_only = client.post(
        "/api/v1/bundles",
        json={"reference": "TEST-LIVE-SERVICE", "destination_country": "SG"},
        headers={"Authorization": "Bearer service.identity.token"},
    )

    assert mock.status_code == 401
    assert service_only.status_code == 401


def test_live_settings_require_a_real_identity_configuration():
    """A deployment cannot accidentally start live mode with demo identity defaults."""
    try:
        Settings(_env_file=None, APP_MODE="live")
    except ValidationError:
        pass
    else:  # pragma: no cover - this must remain fail-closed
        raise AssertionError("live settings unexpectedly accepted demo identity defaults")

    configured = Settings(
        _env_file=None,
        APP_MODE="live",
        AUTH_ENABLED="true",
        OAUTH_CLIENT_ID="test-client.apps.googleusercontent.com",
    )
    assert configured.auth_enabled is True


def test_live_mode_does_not_expose_legacy_password_or_mock_token_routes(monkeypatch):
    """Production uses Google SSO only; password routes cannot mint demo tokens."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "live")
    client = TestClient(create_app())

    for path, payload in (
        ("/api/v1/auth/check?email=agent@customs.com", None),
        (
            "/api/v1/auth/signup",
            {
                "email": "agent@customs.com",
                "password": "not-a-production-password",
                "name": "Agent",
            },
        ),
        (
            "/api/v1/auth/signin",
            {"email": "agent@customs.com", "password": "not-a-production-password"},
        ),
    ):
        response = client.get(path) if payload is None else client.post(path, json=payload)
        assert response.status_code == 404


def test_bundle_resources_do_not_cross_tenant_boundaries(monkeypatch):
    """Every bundle-derived route must conceal another tenant's data."""
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "app_mode", "demo")
    client = TestClient(create_app())

    created = client.post(
        "/api/v1/bundles",
        json={"reference": "TENANT-BOUNDARY", "destination_country": "SG"},
        headers={"X-Test-User-Email": "agent@customs.com"},
    )
    assert created.status_code == 201
    bundle_id = created.json()["id"]

    other_tenant = {"X-Test-User-Email": "agent@dhl.com"}
    protected_paths = (
        f"/api/v1/bundles/{bundle_id}",
        f"/api/v1/bundles/{bundle_id}/audit",
        f"/api/v1/bundles/{bundle_id}/status",
        f"/api/v1/bundles/{bundle_id}/extractions",
        f"/api/v1/bundles/{bundle_id}/assessment",
        f"/api/v1/bundles/{bundle_id}/iterations",
        f"/api/v1/bundles/{bundle_id}/corrections",
        f"/api/v1/bundles/{bundle_id}/prefill",
        f"/api/v1/bundles/{bundle_id}/documents/not-a-document/file",
    )
    for path in protected_paths:
        response = client.get(path, headers=other_tenant)
        assert response.status_code == 404, path
        assert response.json()["code"] == "NOT_FOUND"


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


def test_user_check_and_signup_flow():
    """Verify checking user existence, registering, and subsequent signin."""
    app = create_app()
    client = TestClient(app)

    # 1. Check unregistered user
    res_check = client.get("/api/v1/auth/check", params={"email": "new.broker@customs.com"})
    assert res_check.status_code == 200
    assert res_check.json()["registered"] is False

    # 2. Sign up
    signup_payload = {
        "email": "new.broker@customs.com",
        "password": "strongPassword123",
        "name": "Alex Broker",
        "organization": "Customs Clearing Ltd",
        "role": "LICENSED_CHA",
    }
    res_signup = client.post("/api/v1/auth/signup", json=signup_payload)
    assert res_signup.status_code == 201
    signup_data = res_signup.json()
    assert signup_data["user"]["email"] == "new.broker@customs.com"
    assert signup_data["user"]["tenant_id"] == "customs.com"
    token = signup_data["token"]
    assert token.startswith("mock-jwt-")

    # 3. Check now returns registered
    res_check_after = client.get("/api/v1/auth/check", params={"email": "new.broker@customs.com"})
    assert res_check_after.status_code == 200
    assert res_check_after.json()["registered"] is True
    assert res_check_after.json()["tenant_id"] == "customs.com"

    # 4. Duplicate signup returns 409 Conflict
    res_dup = client.post("/api/v1/auth/signup", json=signup_payload)
    assert res_dup.status_code == 409
    assert res_dup.json()["code"] == "CONFLICT"

    # 5. Sign in with correct password
    res_signin = client.post(
        "/api/v1/auth/signin",
        json={"email": "new.broker@customs.com", "password": "strongPassword123"},
    )
    assert res_signin.status_code == 200
    assert res_signin.json()["user"]["email"] == "new.broker@customs.com"

    # 6. Sign in with wrong password returns 401
    res_wrong = client.post(
        "/api/v1/auth/signin",
        json={"email": "new.broker@customs.com", "password": "wrongPassword!"},
    )
    assert res_wrong.status_code == 401
    assert res_wrong.json()["code"] == "UNAUTHORIZED"

    # 7. Audit trail records registration and login events
    res_audit = client.get("/api/v1/auth/audit", headers={"Authorization": f"Bearer {token}"})
    assert res_audit.status_code == 200
    audit_data = res_audit.json()
    assert audit_data["total_events"] >= 2
    actions = [ev["action"] for ev in audit_data["audit_events"]]
    assert "USER_REGISTERED" in actions
    assert "USER_LOGIN_SUCCESS" in actions


def test_service_account_caller_distinguished_from_end_user(monkeypatch):
    """The Cloud Run IAM caller (a service account) is never a person; only the end-user token the BFF forwards is."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "live")

    # The service identity and the person are told apart by their tokens; a live API verifies real Google tokens only
    sa_claims = {
        "email": "448522365737-compute@developer.gserviceaccount.com",
        "sub": "sa-12345",
        "iss": "https://accounts.google.com",
    }
    user_claims = {
        "email": "pandenikhil5@gmail.com",
        "sub": "user-67890",
        "iss": "https://accounts.google.com",
        "email_verified": True,
    }
    from app.gateway import auth

    monkeypatch.setattr(
        auth,
        "verify_bearer_token",
        lambda token, client_id=None: sa_claims if token == "google-iam-sa-token" else user_claims,
    )

    app = create_app()
    client = TestClient(app)

    # 1. Unauthenticated request from proxy: carries Cloud Run SA token, NO user token
    headers_unauth = {"Authorization": "Bearer google-iam-sa-token"}
    res_unauth = client.get("/api/v1/meta", headers=headers_unauth)
    assert res_unauth.status_code == 200
    assert res_unauth.json()["user"] is None

    # 2. Authenticated request from proxy: carries Cloud Run SA token AND the end user's token, bare or with a Bearer prefix
    for forwarded in ("google-end-user-id-token", "Bearer google-end-user-id-token"):
        headers_auth = {
            "Authorization": "Bearer google-iam-sa-token",
            "X-CargoClear-User-Token": forwarded,
        }
        res_auth = client.get("/api/v1/meta", headers=headers_auth)
        assert res_auth.status_code == 200
        assert res_auth.json()["user"] is not None
        assert res_auth.json()["user"]["email"] == "pandenikhil5@gmail.com"

    # 3. A demo token in the user header is not a session in live mode
    res_mock = client.get(
        "/api/v1/meta",
        headers={
            "Authorization": "Bearer google-iam-sa-token",
            "X-CargoClear-User-Token": "Bearer mock-jwt-pandenikhil5@gmail.com-LICENSED_CHA",
        },
    )
    assert res_mock.status_code == 200
    assert res_mock.json()["user"] is None


def test_verify_bearer_token_genuine_google_success(monkeypatch):
    """Genuine Google ID token verified with audience and claims."""
    from google.oauth2 import id_token
    from app.gateway.auth import verify_bearer_token

    expected_claims = {
        "iss": "https://accounts.google.com",
        "sub": "108429384920194820194",
        "email": "verified.broker@customs.com",
        "email_verified": True,
        "name": "Verified Broker",
        "aud": "cargoclear-test-client-id",
    }
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda tok, req, audience=None, clock_skew_in_seconds=10: expected_claims)

    claims = verify_bearer_token("genuine-signed-google-token", client_id="cargoclear-test-client-id")
    assert claims["sub"] == "108429384920194820194"
    assert claims["email"] == "verified.broker@customs.com"
    assert claims["email_verified"] is True


def test_verify_bearer_token_forged_signature_rejected(monkeypatch):
    """Tampered or unverified tokens must NOT fallback to insecure parsing: raises AuthenticationError."""
    from google.oauth2 import id_token
    from google.auth.exceptions import GoogleAuthError
    from app.gateway.auth import verify_bearer_token
    from app.gateway.errors import AuthenticationError

    # Simulate Google verification failure
    def mock_failure(*args, **kwargs):
        raise GoogleAuthError("Token signature verification failed.")

    monkeypatch.setattr(id_token, "verify_oauth2_token", mock_failure)

    # Forged token with plausible-looking claims
    forged_token = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NSIsImVtYWlsIjoidmljdGltQGN1c3RvbXMuY29tIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIn0.forged_sig"

    with pytest.raises(AuthenticationError) as exc_info:
        verify_bearer_token(forged_token, client_id="test-client-id")

    assert "Invalid or expired authentication token" in str(exc_info.value)


def test_verify_bearer_token_unverified_email_rejected(monkeypatch):
    """Google tokens with unverified email must be rejected."""
    from app.gateway.auth import get_current_user
    from app.gateway.errors import AuthenticationError
    from starlette.requests import Request

    monkeypatch.setattr(settings, "auth_enabled", True)

    unverified_claims = {
        "iss": "https://accounts.google.com",
        "sub": "google-user-9999",
        "email": "unverified@customs.com",
        "email_verified": False,
        "name": "Unverified User",
    }
    from app.gateway import auth
    monkeypatch.setattr(auth, "verify_bearer_token", lambda tok, client_id=None: unverified_claims)

    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer real-google-token-unverified-email")],
    }
    req = Request(scope)

    with pytest.raises(AuthenticationError) as exc_info:
        get_current_user(req)

    assert "not verified" in str(exc_info.value)


def test_preset_demo_account_customs_preserved(monkeypatch):
    """PRESET DEMO ACCOUNT: customs.com must work out of the box with zero regression."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "demo")

    app = create_app()
    client = TestClient(app)

    headers = {"Authorization": "Bearer mock-jwt-demo-cha@customs.com-LICENSED_CHA"}
    res = client.get("/api/v1/meta", headers=headers)
    assert res.status_code == 200
    user = res.json()["user"]
    assert user["email"] == "demo-cha@customs.com"
    assert user["tenant_id"] == "customs.com"
    assert user["role"] == "LICENSED_CHA"


def test_preset_demo_account_dhl_preserved(monkeypatch):
    """PRESET DEMO ACCOUNT: agent@dhl.com must work out of the box with zero regression."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "demo")

    app = create_app()
    client = TestClient(app)

    headers = {"Authorization": "Bearer mock-jwt-agent@dhl.com-LICENSED_CHA"}
    res = client.get("/api/v1/meta", headers=headers)
    assert res.status_code == 200
    user = res.json()["user"]
    assert user["email"] == "agent@dhl.com"
    assert user["tenant_id"] == "dhl.com"
    assert user["role"] == "LICENSED_CHA"


def test_preset_demo_account_fedex_preserved(monkeypatch):
    """PRESET DEMO ACCOUNT: broker@fedex.com must work out of the box with zero regression."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "app_mode", "demo")

    app = create_app()
    client = TestClient(app)

    headers = {"Authorization": "Bearer mock-jwt-broker@fedex.com-LICENSED_CHA"}
    res = client.get("/api/v1/meta", headers=headers)
    assert res.status_code == 200
    user = res.json()["user"]
    assert user["email"] == "broker@fedex.com"
    assert user["tenant_id"] == "fedex.com"
    assert user["role"] == "LICENSED_CHA"


