"""Commercial Authentication & User Management API routes.

Provides:
- User existence check (/check?email=...)
- Commercial Signup with basic details and audit tracking (/signup)
- Password & SSO Signin with verification (/signin)
- User audit history (/audit)
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.domain.auth import UserIdentity, UserRole
from app.gateway.auth import get_current_user, get_optional_user
from app.gateway.errors import AuthenticationError, ConflictError, NotFoundError
from app.repo import firestore

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Secure PBKDF2-HMAC-SHA256 password hashing with salt."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return key.hex(), salt


def _verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Verify password against stored salt and hash."""
    expected_hash, _ = _hash_password(password, salt)
    return secrets.compare_digest(expected_hash, password_hash)


class CheckUserResponse(BaseModel):
    registered: bool
    email: str
    name: str | None = None
    tenant_id: str | None = None
    role: UserRole | None = None
    auth_provider: str | None = None


class SignUpRequest(BaseModel):
    email: str = Field(description="Corporate CHA or customs email")
    password: str = Field(min_length=6, description="User password")
    name: str = Field(description="Full name of customs agent")
    organization: str | None = Field(default=None, description="Company or Brokerage name")
    role: UserRole = Field(default="LICENSED_CHA", description="CargoClear role")


class SignInRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: UserIdentity
    message: str


@router.get(
    "/check",
    response_model=CheckUserResponse,
    summary="Check if a commercial user is already registered",
)
async def check_user(email: str = Query(..., description="Email to inspect")) -> CheckUserResponse:
    clean_email = email.strip().lower()
    user_record = await firestore.get_user(clean_email)
    if user_record:
        return CheckUserResponse(
            registered=True,
            email=clean_email,
            name=user_record.get("name"),
            tenant_id=user_record.get("tenant_id"),
            role=user_record.get("role"),
            auth_provider=user_record.get("auth_provider", "password"),
        )
    return CheckUserResponse(registered=False, email=clean_email)


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new commercial CHA user with audit trail",
)
async def signup(req: SignUpRequest) -> AuthResponse:
    clean_email = req.email.strip().lower()

    # Check if user already exists
    existing = await firestore.get_user(clean_email)
    if existing:
        raise ConflictError(
            f"User '{clean_email}' is already registered. Please sign in instead.",
            detail={"email": clean_email, "auth_provider": existing.get("auth_provider", "password")},
        )

    # Derive corporate tenancy from email domain
    domain = clean_email.split("@")[-1] if "@" in clean_email else "customs.com"
    pw_hash, salt = _hash_password(req.password)

    user_record = {
        "email": clean_email,
        "name": req.name.strip(),
        "organization": req.organization or domain,
        "tenant_id": domain,
        "role": req.role,
        "auth_provider": "password",
        "password_hash": pw_hash,
        "salt": salt,
        "status": "ACTIVE",
    }

    # Store user in Firestore
    saved = await firestore.create_user(user_record)

    # Record tamper-evident audit event
    await firestore.record_user_audit(
        clean_email,
        action="USER_REGISTERED",
        details={
            "role": req.role,
            "tenant_id": domain,
            "organization": req.organization,
            "registered_at": saved["created_at"],
        },
    )

    # Issue session token
    token = f"mock-jwt-{clean_email}-{req.role}"
    identity = UserIdentity(
        user_id=f"usr-{clean_email}",
        email=clean_email,
        name=req.name.strip(),
        tenant_id=domain,
        role=req.role,
    )

    return AuthResponse(
        token=token,
        user=identity,
        message=f"Registration successful for {clean_email} in organization {domain}.",
    )


@router.post(
    "/signin",
    response_model=AuthResponse,
    summary="Sign in registered user with email and password",
)
async def signin(req: SignInRequest) -> AuthResponse:
    clean_email = req.email.strip().lower()
    user_record = await firestore.get_user(clean_email)

    if not user_record:
        raise NotFoundError(
            f"No account found for '{clean_email}'. Please sign up first.",
            detail={"email": clean_email},
        )

    # Verify password if user registered with password
    if user_record.get("auth_provider") == "password" or "password_hash" in user_record:
        pw_hash = user_record.get("password_hash", "")
        salt = user_record.get("salt", "")
        if not _verify_password(req.password, pw_hash, salt):
            await firestore.record_user_audit(
                clean_email,
                action="USER_LOGIN_FAILED",
                details={"reason": "INVALID_PASSWORD"},
            )
            raise AuthenticationError("Invalid password. Please check your credentials.")

    now_iso = datetime.now(timezone.utc).isoformat()
    await firestore.update_user(clean_email, {"last_login_at": now_iso})

    # Record audit event
    await firestore.record_user_audit(
        clean_email,
        action="USER_LOGIN_SUCCESS",
        details={"tenant_id": user_record.get("tenant_id")},
    )

    role = user_record.get("role", "LICENSED_CHA")
    tenant_id = user_record.get("tenant_id", clean_email.split("@")[-1])
    token = f"mock-jwt-{clean_email}-{role}"

    identity = UserIdentity(
        user_id=f"usr-{clean_email}",
        email=clean_email,
        name=user_record.get("name", clean_email.split("@")[0].title()),
        tenant_id=tenant_id,
        role=role,
    )

    return AuthResponse(
        token=token,
        user=identity,
        message="Sign in successful.",
    )


@router.get(
    "/audit",
    summary="Get user audit trail and login history",
)
async def get_user_audit(
    current_user: UserIdentity = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve audit history for current authenticated user."""
    email = current_user.email.lower()
    client = firestore._get_firestore_client()
    events = []
    if client is not None:
        ref = client.collection("users").document(email).collection("audit").order_by("timestamp", direction="DESCENDING")
        events = [doc.to_dict() async for doc in ref.stream()]
    else:
        events = list(reversed(firestore._IN_MEMORY_USER_AUDIT.get(email, [])))

    return {
        "email": email,
        "tenant_id": current_user.tenant_id,
        "total_events": len(events),
        "audit_events": events,
    }
