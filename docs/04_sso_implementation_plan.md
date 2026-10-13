# CargoClear: Single Sign-On (SSO) Architecture & Implementation Plan

**Target Goal**: Implement enterprise-grade Single Sign-On (SSO) for CargoClear, establishing multi-tenant broker authentication, role-based access control (RBAC), and session security across the FastAPI backend and Next.js frontend workbench.

---

## 1. Architecture Overview & Design Principles

CargoClear operates in high-liability, regulated customs adjudication. Every assessment, document view, and reasoning override must be attributable to an authenticated, licensed Customs House Agent (CHA) or customs officer.

```
+--------------------------------------------------------------------------------------------------+
|                                  CARGOCLEAR SSO ARCHITECTURE                                     |
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|   [ Browser Client ]                     [ Next.js BFF Proxy ]              [ Identity Provider ] |
|   - Login View                           - NextAuth / Google OAuth          - Google Identity /  |
|   - Session Cookie                       - Session Token Exchange           - Workspace / OIDC   |
|   - Auth Headers                         - Server-side Cookie Guard         - Azure AD / Okta    |
|            │                                      │                                  │           |
|            │ (1) User Logs in via OAuth           │                                  │           |
|            ├─────────────────────────────────────►│ (2) Exchange Auth Code          │           |
|            │                                      ├─────────────────────────────────►│           |
|            │                                      │◄─────────────────────────────────┤           |
|            │                                      │ (3) Return ID Token / JWT        │           |
|            │◄─────────────────────────────────────┤                                              |
|            │ (4) Set Encrypted Session Cookie     │                                              |
|            │                                      │                                              |
|            │ (5) API Requests (/api/proxy/...)    │                                              |
|            ├─────────────────────────────────────►│                                              |
|            │                                      │ (6) Forward Bearer JWT                       |
|            │                                      ├─────────────────────────┐                    |
|                                                                             │                    |
|                                                                             ▼                    |
|                                                                    [ FastAPI Backend ]           |
|                                                                    - AuthMiddleware              |
|                                                                    - JWT Cryptographic Verify    |
|                                                                    - Tenant / Role Extraction    |
|                                                                    - Audit Trail Attribution     |
+--------------------------------------------------------------------------------------------------+
```

### Key Design Tenets
1. **Zero-Trust Backend**: The FastAPI backend never trusts client assertions blindly. It validates JWT signatures cryptographically using the identity provider's public keys (JWKS).
2. **Seamless Local Demo Support**: To ensure local automated testing (`APP_MODE=demo`, unit tests, Playwright) continues passing without requiring real Google Cloud client secrets, an automatic **Mock Dev Identity** will be provided when `AUTH_ENABLED=false` or in demo mode.
3. **Audit Trail Attribution**: Every audit event in Firestore (`services/audit.py`) currently records `actor_id="system"`. With SSO, audit events will be explicitly tagged with the authenticated user (`actor_id="cha:john.doe@brokerage.com"`, `actor_role="SENIOR_CHA"`).
4. **BFF Security**: The browser never handles long-lived refresh tokens or raw identity secrets. The Next.js BFF proxy maintains an `HttpOnly, Secure, SameSite=Lax` encrypted session cookie and forwards standard `Authorization: Bearer <JWT>` headers to the backend.

---

## 2. Technical Stack & Implementation Components

| Layer | Technology | Key Responsibility |
|---|---|---|
| **Identity Provider (IdP)** | Google OAuth 2.0 / Google Identity Services (OIDC) | Enterprise single sign-on with domain restrictions (e.g., `@brokerage.com`, `@customs.gov`). |
| **Frontend Auth Layer** | NextAuth.js (`next-auth` v5 / Auth.js) + React Context | Login modal/page, user profile avatar, protected routes, session cookies. |
| **Proxy / BFF Gateway** | `frontend/app/api/proxy/[...path]/route.ts` | Attaches validated Bearer token to all upstream requests to FastAPI. |
| **Backend Gateway** | `backend/app/gateway/auth.py` | FastAPI ASGI middleware & dependency verifying JWT signature, expiry, and issuer. |
| **Domain & Audit** | `backend/app/domain/auth.py` & `services/audit.py` | User context model (`UserIdentity`), Tenant ID, and actor attribution in hash chain. |

---

## 3. Detailed Phase-by-Phase Execution Plan

### Phase 1: Backend Auth Gateway & JWT Verification
* **Step 1.1**: Add Configuration Settings in `backend/app/core/config.py`:
  - `AUTH_ENABLED: bool = True` (Default `False` when `APP_MODE=demo`).
  - `OAUTH_CLIENT_ID: str`
  - `OAUTH_ISSUER: str = "https://accounts.google.com"`
  - `ALLOWED_EMAIL_DOMAINS: list[str] = ["*"]` (Optional domain restriction for enterprise brokerages).
* **Step 1.2**: Implement `backend/app/domain/auth.py`:
  - Pydantic models: `UserIdentity(user_id, email, name, role, tenant_id)`.
  - Roles: `CHA_OPERATOR` (view & upload), `LICENSED_CUSTOMS_BROKER` (adjudicate & override), `AUDITOR` (read-only audit trail).
* **Step 1.3**: Implement `backend/app/gateway/auth.py`:
  - `get_current_user(request: Request) -> UserIdentity`: FastAPI dependency extracting `Authorization: Bearer <token>`.
  - Verify token using `google-auth` / PyJWT with cached Google public certs (`JWKS`).
  - Fallback in demo mode: Return mock licensed broker (`demo-cha@cargoclear.internal`).
* **Step 1.4**: Wire into `backend/app/services/audit.py`:
  - Replace hardcoded `"actor_id": "system"` with `user.email`.

### Phase 2: Frontend Authentication & BFF Integration
* **Step 2.1**: Install Frontend Dependencies:
  - Add `next-auth` (or lightweight session management).
* **Step 2.2**: Implement Auth Route & Session Provider:
  - `frontend/app/api/auth/[...nextauth]/route.ts`: Configures Google Provider and JWT session callbacks.
  - `frontend/components/auth/SessionProvider.tsx`: Wrap app root for reactive session state.
* **Step 2.3**: Update BFF Proxy (`frontend/app/api/proxy/[...path]/route.ts`):
  - Read active session on incoming requests.
  - Inject `Authorization: Bearer <session.idToken>` header when proxying to FastAPI.
* **Step 2.4**: Implement Login UI & User Indicator:
  - Add `UserMenu.tsx` to `TopBar`: shows avatar, user name, role badge (`Licensed CHA`), and Sign Out button.
  - If unauthenticated, redirect to `/login` or prompt the clean Google SSO modal.

### Phase 3: Route Protection & Multi-Tenant Scoping
* **Step 3.1**: Next.js Middleware Route Protection (`frontend/middleware.ts`):
  - Protect `/workbench/*` routes, redirecting unauthenticated sessions to `/login`.
* **Step 3.2**: Backend Bundle Scoping:
  - Tag bundle creation (`POST /api/v1/bundles`) with `tenant_id` and `created_by`.
  - Validate that users can only access bundles belonging to their brokerage organization.

### Phase 4: Verification, Automated Tests & CI
* **Step 4.1**: Backend Unit & Integration Tests:
  - Test valid Google JWT verification.
  - Test expired or tampered token returns 401 with standard error envelope (`{"code": "UNAUTHORIZED"}`).
  - Test domain restriction filtering (`@unauthorized.com` returns 403).
  - Verify demo mode bypass functions seamlessly without network calls.
* **Step 4.2**: Frontend Typecheck & Build:
  - Run `npm run typecheck && npm run lint && npm run build`.
* **Step 4.3**: End-to-End Verification:
  - Verify login $\rightarrow$ bundle creation $\rightarrow$ audit log shows the logged-in user email $\rightarrow$ logout.

---

## 4. Rollback & Fail-Safe Strategy

* **Zero-Downtime Feature Flag**: The entire auth layer is controlled by `AUTH_ENABLED`. If Google OAuth credentials are not supplied or if running in local sandbox, the system cleanly defaults to open access with the demo identity.
* **Regression Guard**: All existing 1,581 backend tests will run with `AUTH_ENABLED=False` to ensure backward compatibility.

---

## 5. Review & Approval

Once this plan is approved, we will begin implementation starting with **Phase 1 (Backend Core & Auth Gateway)**.
