"""Authentication dependency and JWT token verification for CargoClear."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings
from app.domain.auth import UserIdentity
from app.gateway.errors import AuthenticationError, ForbiddenError

logger = structlog.get_logger(__name__)

# Only the private UI BFF sets this header. In live mode its Cloud Run service
# identity is authenticated separately in Authorization; the browser's Google
# ID token arrives here in this distinct header and is verified as the person
# who is acting. A service identity must never become a customs user.
END_USER_TOKEN_HEADER = "X-CargoClear-User-Token"  # noqa: S105

# Reusable transport request session for Google public cert verification
_REQUEST_SESSION: google_requests.Request | None = None


def _get_request_session() -> google_requests.Request:
    global _REQUEST_SESSION
    if _REQUEST_SESSION is None:
        _REQUEST_SESSION = google_requests.Request()
    return _REQUEST_SESSION


def verify_bearer_token(token: str, client_id: str | None = None) -> dict[str, Any]:
    """Verify a Google/OIDC ID token cryptographically.

    Returns claims dict on success, or raises AuthenticationError on failure.
    """
    try:
        req = _get_request_session()
        # If client_id is not configured or in testing, verify without audience restriction
        claims = id_token.verify_oauth2_token(
            token,
            req,
            audience=client_id,
            clock_skew_in_seconds=10,
        )
        return claims
    except Exception as exc:
        logger.warning("token_verification_failed", error=str(exc))
        raise AuthenticationError(f"Invalid or expired authentication token: {exc}") from exc


def get_current_user(request: Request) -> UserIdentity:
    """FastAPI dependency to extract and verify the authenticated user.

    Behaviors:
    In live mode, an end-user Google ID token must be supplied in the private
    BFF header. Authorization carries the BFF's service identity and cannot
    authenticate a person. Demo mode permits mock identities for local flows.
    """
    end_user_token = request.headers.get(END_USER_TOKEN_HEADER)
    auth_header = request.headers.get("Authorization")
    token: str | None = end_user_token
    if (
        token is None
        and settings.app_mode != "live"
        and auth_header
        and auth_header.startswith("Bearer ")
    ):
        # Direct bearer authentication is for local/test development only. A
        # live private API receives the BFF's service token here, not a user.
        token = auth_header.split(" ", 1)[1].strip()

    if token is not None:
        if not token:
            raise AuthenticationError("Empty Bearer token provided.")

        # In local testing or simulated SSO token mode
        if token.startswith("mock-jwt-"):
            if settings.app_mode != "demo":
                raise AuthenticationError("Demo session tokens are not accepted outside demo mode.")
            payload = token[len("mock-jwt-"):]
            possible_roles = {"LICENSED_CHA", "OPERATOR", "AUDITOR", "SYSTEM"}
            email = payload
            role = "LICENSED_CHA"
            if "-" in payload:
                prefix_part, maybe_role = payload.rsplit("-", 1)
                if maybe_role in possible_roles:
                    email = prefix_part
                    role = maybe_role
            elif ":" in payload:
                prefix_part, maybe_role = payload.rsplit(":", 1)
                if maybe_role in possible_roles:
                    email = prefix_part
                    role = maybe_role
            if not email:
                email = "demo-cha@customs.com"
            claims = {
                "email": email,
                "sub": f"usr-{email}",
                "cargo_role": role,
                "name": email.split("@")[0].title(),
            }
        else:
            claims = verify_bearer_token(token, client_id=settings.oauth_client_id)

        user = UserIdentity.from_claims(claims)

        # Check allowed corporate email domains
        allowed_domains = settings.allowed_domains_list
        if "*" not in allowed_domains:
            domain = user.email.split("@")[-1].lower() if "@" in user.email else ""
            if domain not in allowed_domains:
                raise ForbiddenError(
                    f"Domain '{domain}' is not authorized for this customs portal.",
                    detail={"email": user.email, "allowed_domains": allowed_domains},
                )

        return user

    if settings.app_mode == "demo" and not settings.auth_enabled:
        # Check if an optional test header is passed to simulate different users in test mode
        custom_email = request.headers.get("X-Test-User-Email")
        if custom_email:
            return UserIdentity.mock_commercial_cha(email=custom_email)
        return UserIdentity.mock_commercial_cha()

    raise AuthenticationError("A verified end-user session is required.")


def get_optional_user(request: Request) -> UserIdentity | None:
    """Optional user dependency for public metadata routes like /meta."""
    has_end_user_token = bool(request.headers.get(END_USER_TOKEN_HEADER))
    has_demo_bearer = (
        settings.app_mode == "demo"
        and request.headers.get("Authorization", "").startswith("Bearer ")
    )
    if has_end_user_token or has_demo_bearer:
        try:
            return get_current_user(request)
        except Exception as exc:
            logger.warning("optional_user_auth_failed", error=str(exc))
            return None
    if settings.app_mode == "demo" and not settings.auth_enabled:
        return get_current_user(request)
    return None

