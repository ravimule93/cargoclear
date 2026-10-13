# CargoClear: Commercial Multi-Tenant Single Sign-On (SSO) Architecture & Plan

**Target Goal**: Implement enterprise-grade, commercial Single Sign-On (SSO) and Multi-Tenant Isolation for CargoClear. Ensure Custom House Agent (CHA) brokerages of any corporate domain (e.g. `customs.com`, `dhl.com`, `fedex.com`, `genpact.com`) can seamlessly log in, access their company's workspace, and maintain compliance attribution without locking out commercial users.

---

## 1. Commercial User Access: How a User from `customs.com` Operates

In cross-border trade, Custom House Agents (CHAs) and freight forwarders operate across disparate corporate identity systems:
* **Company A (`customs.com`)**: Uses Google Workspace or Microsoft Azure AD for enterprise email.
* **Company B (`dhl.com` / `fedex.com`)**: Uses Microsoft Entra ID (Office 365) or corporate Okta SAML.
* **Independent Licensed Brokers**: Use professional email addresses.

To prevent blocking commercial users, CargoClear employs **Dynamic Multi-Tenant Domain Derivation**:

```
                                [ Commercial Login Screen ]
                                             │
             ┌───────────────────────────────┼───────────────────────────────┐
             ▼                               ▼                               ▼
   [ Sign in with Google ]        [ Sign in with Microsoft ]        [ Corporate SAML / OIDC ]
 (Any company using Google       (Any company using Azure AD/      (Enterprise brokers using 
    Workspace or Gmail)           Office 365, e.g. customs.com)       Okta / Ping Identity)
             │                               │                               │
             └───────────────────────────────┼───────────────────────────────┘
                                             ▼
                                  [ OpenID Connect (OIDC) ]
                                             │
                                             ▼
                                [ Standard Verified Payload ]
                                • email: "john@customs.com"
                                • domain: "customs.com"  ──► [ Auto-Assigned Tenant ID: "tenant-customs" ]
                                • name: "John Doe"
                                • role: "LICENSED_CHA"
                                             │
                                             ▼
                          [ Workspace & Bundle Scoping ]
                          • Sees only bundles for customs.com
                          • Cannot see bundles for dhl.com
                          • Audit trail stamped: "cha:john@customs.com"
```

### The 3 Core Tenets of Commercial Access
1. **Open Commercial Access (`ALLOWED_EMAIL_DOMAINS = ["*"]`)**:
   - Any legitimate user from `customs.com` or any corporate domain can authenticate and create their company's workspace immediately.
   - Enterprise administrators have the optional capability to restrict domains to specific partner brokerages when deployed in private tenancy mode.
2. **Dynamic Multi-Tenant Isolation**:
   - The user's corporate domain (`customs.com`) is derived as their `tenant_id`.
   - All trade bundles, documents, and assessments created by John are scoped to `tenant-customs.com`.
   - Colleagues within `customs.com` can collaborate on the same shipping files, while competitors cannot inspect or access their trade data.
3. **Forensic Non-Repudiation**:
   - Every adjudication decision, reasoning override, and file upload in the Firestore hash chain is stamped with the verified user: `actor_id="cha:john@customs.com"`.

---

## 2. Technical Stack & Implementation Components

| Layer | Technology | Key Responsibility |
|---|---|---|
| **Identity Protocols** | OpenID Connect (OIDC) / OAuth 2.0 | Standard identity layer supported by Google Workspace, Microsoft Azure AD / Entra ID, and Okta. |
| **Frontend Auth Layer** | NextAuth.js (`next-auth` v5 / Auth.js) | Universal multi-provider buttons (Google Workspace, Microsoft Work Accounts), session tokens, user avatar, and role pill. |
| **BFF Proxy Gateway** | `frontend/app/api/proxy/[...path]/route.ts` | Next.js server-side route handler reading session cookies and injecting verified `Authorization: Bearer <JWT>` to backend API. |
| **Backend Gateway** | `backend/app/gateway/auth.py` | FastAPI ASGI middleware & dependency cryptographically verifying JWT signatures, issuer, and token expiry. |
| **Multi-Tenant Domain** | `backend/app/domain/auth.py` | Models `UserIdentity(user_id, email, tenant_id, role)` and enforces tenant bundle isolation. |
| **Audit Integration** | `backend/app/services/audit.py` | Binds authenticated identity into the immutable SHA-256 hash chain. |

---

## 3. Detailed Phase-by-Phase Execution Plan

### Phase 1: Backend Auth Gateway & Multi-Tenant Core
* **Step 1.1: Configuration Settings** (`backend/app/core/config.py`):
  - `AUTH_ENABLED: bool = True` (Default `False` when `APP_MODE=demo`).
  - `OAUTH_CLIENT_ID: str | None = None`
  - `OAUTH_ISSUER: str = "https://accounts.google.com"`
  - `ALLOWED_EMAIL_DOMAINS: list[str] = ["*"]` (Wildcard allows any commercial company like `customs.com`).
* **Step 1.2: Multi-Tenant Identity Model** (`backend/app/domain/auth.py`):
  - Model `UserIdentity`:
    ```python
    class UserIdentity(BaseModel):
        user_id: str
        email: str
        name: str
        tenant_id: str  # Automatically derived from email domain (e.g. "customs.com")
        role: Literal["LICENSED_CHA", "OPERATOR", "AUDITOR"] = "LICENSED_CHA"
    ```
* **Step 1.3: Token Verification Dependency** (`backend/app/gateway/auth.py`):
  - `get_current_user(request: Request) -> UserIdentity`:
    - Reads `Authorization: Bearer <token>`.
    - Cryptographically validates JWT signature using public key sets (JWKS).
    - Extracts email and derives `tenant_id = email.split("@")[-1]`.
    - Checks `ALLOWED_EMAIL_DOMAINS`: permits any commercial domain when set to `["*"]`.
    - **Demo Mode Seam**: If `AUTH_ENABLED=False` or running in `APP_MODE=demo`, injects `demo-cha@customs.com` with zero network dependency.
* **Step 1.4: Audit Trail Binding** (`backend/app/services/audit.py`):
  - Injects `user.email` into `actor_id` across all audit events in the Firestore hash chain.

### Phase 2: Frontend Multi-Provider SSO & BFF Integration
* **Step 2.1: Multi-Provider Auth Handler** (`frontend/app/api/auth/[...nextauth]/route.ts`):
  - Configure Google Workspace and Microsoft Azure AD OIDC providers.
  - Return standardized JWT session payload containing email, name, image, and token.
* **Step 2.2: BFF Proxy Header Injection** (`frontend/app/api/proxy/[...path]/route.ts`):
  - The Next.js BFF proxy reads the server-side session cookie.
  - Attaches `Authorization: Bearer <session.idToken>` before proxying to FastAPI.
* **Step 2.3: TopBar User Profile & Tenant Badge**:
  - Displays authenticated user avatar, company name (`customs.com`), role pill (`Licensed CHA`), and Sign Out action.
  - In Demo Mode: Displays `● Demo Mode (Unauthenticated Workspace)`.

### Phase 3: Multi-Tenant Data Isolation
* **Step 3.1: Bundle Tenancy Tagging**:
  - When a user from `customs.com` creates a bundle (`POST /api/v1/bundles`), tag `bundle.tenant_id = "customs.com"`.
* **Step 3.2: Access Enforcement**:
  - `GET /api/v1/bundles/{id}` verifies `bundle.tenant_id == user.tenant_id` (or superadmin).
  - Users from `customs.com` cannot view, stream, or reassess bundles belonging to `other-broker.com`.

### Phase 4: Automated Testing & Verification
* **Step 4.1: Backend Tests**:
  - Unit test valid token decoding and tenant derivation (`customs.com` $\rightarrow$ `tenant_id="customs.com"`).
  - Test expired and tampered tokens return HTTP 401 with standard error envelope.
  - Test multi-tenant isolation (user A cannot access user B's bundle $\rightarrow$ HTTP 403/404).
  - Verify all 1,581 existing tests pass cleanly with `AUTH_ENABLED=False`.
* **Step 4.2: Frontend Build & Typecheck**:
  - Run `npm run typecheck && npm run lint && npm run build`.

---

## 4. Rollback & Fail-Safe Strategy

* **Zero-Downtime Feature Flag**: The auth layer is completely decoupled via `AUTH_ENABLED`.
* **Demo Integrity**: Running with `APP_MODE=demo` automatically switches to the mock commercial identity (`demo-cha@customs.com`), ensuring hackathon live demos and offline evaluators are never blocked by missing OAuth credentials.
