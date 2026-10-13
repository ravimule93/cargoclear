"""Authentication and Multi-Tenant Identity domain models."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


UserRole = Literal["LICENSED_CHA", "OPERATOR", "AUDITOR", "SYSTEM"]


class UserIdentity(BaseModel):
    """Authenticated user identity with company tenancy and role."""

    user_id: str = Field(description="Unique subject or user identifier from IdP")
    email: str = Field(description="Corporate email address of the user")
    name: str = Field(default="Customs Agent", description="Display name of the user")
    tenant_id: str = Field(description="Organization identifier derived from corporate domain")
    role: UserRole = Field(default="LICENSED_CHA", description="Access role for customs operations")
    issuer: str = Field(default="https://accounts.google.com", description="Identity provider issuer")

    @classmethod
    def from_claims(
        cls,
        claims: dict,
        *,
        default_role: UserRole = "LICENSED_CHA",
    ) -> "UserIdentity":
        """Construct UserIdentity from verified JWT claims."""
        email = (claims.get("email") or claims.get("upn") or "unknown@customs.internal").lower()
        sub = str(claims.get("sub") or claims.get("oid") or email)
        name = claims.get("name") or claims.get("preferred_username") or email.split("@")[0].title()
        issuer = claims.get("iss") or "https://accounts.google.com"

        # Derive tenant from corporate domain (e.g. john@customs.com -> customs.com)
        domain = email.split("@")[-1] if "@" in email else "default"
        tenant_id = domain

        # Role can be specified in claims or fallback to default
        role = claims.get("cargo_role") or default_role

        return cls(
            user_id=sub,
            email=email,
            name=name,
            tenant_id=tenant_id,
            role=role,
            issuer=issuer,
        )

    @classmethod
    def mock_commercial_cha(
        cls,
        email: str = "demo-cha@customs.com",
        name: str = "Demo Customs House Agent",
        role: UserRole = "LICENSED_CHA",
    ) -> "UserIdentity":
        """Pre-authenticated commercial mock identity for demo and local development."""
        domain = email.split("@")[-1] if "@" in email else "customs.com"
        return cls(
            user_id=f"usr-{domain}-{email.split('@')[0]}",
            email=email,
            name=name,
            tenant_id=domain,
            role=role,
            issuer="mock://cargoclear.internal",
        )
