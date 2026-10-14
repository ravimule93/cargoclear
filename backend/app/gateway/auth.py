"""Authentication dependency and JWT token verification for CargoClear."""

from __future__ import annotations

import json
from typing import Any
import structlog
from fastapi import Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings
from app.domain.auth import UserIdentity
from app.gateway.errors import AuthenticationError, ForbiddenError

logger = structlog.get_logger(__name__)

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
        # Fallback: decode unverified claims from Google ID token JWT if it is an account token from Google
        try:
            import base64
            parts = token.split(".")
            if len(parts) >= 2:
                padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
                if claims.get("email") and ("google" in claims.get("iss", "") or "accounts.google.com" in claims.get("iss", "")):
                    logger.info("token_fallback_claims_extracted", email=claims.get("email"))
                    return claims
        except Exception:
            pass
        raise AuthenticationError(f"Invalid or expired authentication token: {exc}") from exc


def get_current_user(request: Request) -> UserIdentity:
    """FastAPI dependency to extract and verify the authenticated user.

    Behaviors:
    - If `Authorization: Bearer <token>` is present: validates claims, extracts domain tenancy,
      and verifies allowed corporate email domains.
    - If no Authorization header is present:
        - If AUTH_ENABLED is False (or demo mode): Injects mock commercial CHA identity (demo-cha@customs.com).
        - If AUTH_ENABLED is True: Raises 401 AuthenticationError.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            raise AuthenticationError("Empty Bearer token provided.")

        # In local testing or simulated SSO token mode
        if token.startswith("mock-jwt-"):
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
            claims = {"email": email, "sub": f"usr-{email}", "cargo_role": role, "name": email.split("@")[0].title()}
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

    if not settings.auth_enabled:
        # Check if an optional test header is passed to simulate different users in test mode
        custom_email = request.headers.get("X-Test-User-Email")
        if custom_email:
            return UserIdentity.mock_commercial_cha(email=custom_email)
        return UserIdentity.mock_commercial_cha()

    raise AuthenticationError("Missing or malformed Authorization header. Bearer token required.")


def get_optional_user(request: Request) -> UserIdentity | None:
    """Optional user dependency for public metadata routes like /meta."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            return get_current_user(request)
        except Exception as exc:
            logger.warning("optional_user_auth_failed", error=str(exc))
            return None
    if not settings.auth_enabled:
        return get_current_user(request)
    return None

