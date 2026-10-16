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

---

## 5. Implementation Progress & Verification Tracker

| Phase | Component / Task | File / Path | Status | Verification Detail |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1** | Auth Settings & Config | [`backend/app/core/config.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/core/config.py) | **Completed** | Added `auth_enabled`, `oauth_client_id`, `oauth_issuer`, `allowed_email_domains`, and `allowed_domains_list`. Defaults to open commercial access (`["*"]`). |
| **Phase 1** | Identity Domain Model | [`backend/app/domain/auth.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/domain/auth.py) | **Completed** | Created `UserIdentity` and `UserRole`. Automatically derives `tenant_id` from corporate email domain (e.g. `clerk@customs.com` -> `customs.com`). Supports `mock_commercial_cha`. |
| **Phase 1** | Gateway Auth Dependency | [`backend/app/gateway/auth.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/gateway/auth.py) | **Completed** | Implemented `get_current_user` and `get_optional_user`. Supports Google ID token cryptographic validation, corporate domain filtering, and local testing tokens (`mock-jwt-*`). |
| **Phase 1** | Error Hierarchy | [`backend/app/gateway/errors.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/gateway/errors.py) | **Completed** | Added `AuthenticationError` (HTTP 401 `UNAUTHORIZED`) and `ForbiddenError` (HTTP 403 `FORBIDDEN`) adhering to CargoClear JSON error envelope. |
| **Phase 2** | Frontend Auth Types | [`frontend/lib/types.ts`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/frontend/lib/types.ts) | **Completed** | Added `UserRole`, `UserIdentity`, `AuthConfig`, and updated `Meta` and `Bundle` with multi-tenant fields (`tenant_id`, `created_by`, `auth`, `user`). |
| **Phase 2** | BFF Proxy Header Injection | [`frontend/app/api/proxy/[...path]/route.ts`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/frontend/app/api/proxy/[...path]/route.ts) | **Completed** | Forwards `cargoclear_session_token` cookie as `Authorization: Bearer <token>` to backend FastAPI gateway. |
| **Phase 2** | User Profile & SSO Shell UI | [`frontend/components/shell/UserMenu.tsx`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/frontend/components/shell/UserMenu.tsx) | **Completed** | Implemented dynamic corporate user pill, tenant domain indicator (`customs.com`), role badge (`Licensed CHA`), sign-in modal supporting Google Workspace & commercial email tokens, and sign-out. |
| **Phase 2** | TopBar & Shell Integration | [`frontend/components/shell/TopBar.tsx`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/frontend/components/shell/TopBar.tsx), [`frontend/app/workbench/[bundleId]/page.tsx`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/frontend/app/workbench/[bundleId]/page.tsx) | **Completed** | Mounted `UserMenu` in global header and workbench top navigation. Preserves existing layout and demo indicators. |
| **Phase 3** | Multi-Tenant Data Isolation | [`backend/app/api/v1/bundles.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/api/v1/bundles.py) | **Completed** | `POST /bundles` tags `tenant_id` and `created_by`. `GET /bundles/{id}` verifies tenant isolation. Users from other domains cannot inspect alien bundles. |
| **Phase 3** | Metadata Endpoint Context | [`backend/app/api/v1/meta.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/api/v1/meta.py) | **Completed** | Exposes system `auth` configuration and active `user` identity when token is provided, while maintaining zero breakages for unauthenticated callers. |
| **Phase 4** | Automated Unit Test Suite | [`backend/tests/unit/test_auth_sso.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/tests/unit/test_auth_sso.py) | **Completed** | **6/6 tests passing (100%)**: Validated claims extraction, mock CHA identity, `/meta` auth context, bundle tenant tagging, missing Bearer token (401), and unauthorized domain filtering (403). |
| **Phase 4** | Regression Suite | [`backend/tests/unit/test_bundles.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/tests/unit/test_bundles.py), [`backend/tests/unit/test_api_docs.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/tests/unit/test_api_docs.py) | **Completed** | Core routes and OpenAPI documentation verified without regressions. Backward compatibility in demo mode intact. |
| **Phase 5** | Cloud Run API Deployment | Google Cloud Run `cargoclear-api` (`asia-south1`) | **Completed & Verified** | Revision `cargoclear-api-00017-j7g` serving 100% traffic. Configured with `AUTH_ENABLED=true` and `ALLOWED_EMAIL_DOMAINS=*`. |
| **Phase 5** | Cloud Run UI Deployment | Google Cloud Run `cargoclear-ui` (`asia-south1`) | **Completed & Verified** | Revision `cargoclear-ui-00016-nqd` serving 100% traffic at `https://cargoclear-ui-448522365737.asia-south1.run.app`. BFF proxy configured with `API_BASE`. |
| **Phase 5** | Live Multi-Tenant Cloud Verification | Cloud Run Production URLs | **Completed & Verified** | Verified live via curl & BFF: (1) Unauthenticated `/meta` returns `user: null`, (2) Authenticated session returns `user: {tenant_id: "customs.com"}`, (3) Bundle created with `tenant_id: "customs.com"`, (4) Cross-tenant access from `dhl.com` returned HTTP 403 Forbidden, (5) Unauthenticated access returned HTTP 401 Unauthorized. |
| **Phase 6** | PDF Worker & Google OAuth Redirection | Google Cloud Run & Frontend UI | **Completed & Verified** | (1) Bundled `pdf.worker.min.mjs` directly in image (serving 200 OK, 1.37MB), resolving PDF viewer module fetch error; (2) Implemented live OAuth 2.0 / OIDC provider redirection (`/api/auth/signin/google` -> `https://accounts.google.com/o/oauth2/v2/auth`) and callback handler (`/api/auth/callback/google`) with automatic tenant onboarding. |
| **Phase 7** | User Registration, Password Auth & Audit Ledger | Backend API & Firestore | **Completed & Verified** | Implemented `users` and `users/{email}/audit` subcollection in Firestore. Added endpoints: `/check` (user existence), `/signup` (PBKDF2 salted hash password creation, 409 conflict handling, `USER_REGISTERED` audit), `/signin` (hash verification, `USER_LOGIN_SUCCESS`/`USER_LOGIN_FAILED` audit), and `/audit` (user audit log retrieval). |
| **Phase 7** | Server-Side Logout & Host Origin Resolution | Frontend BFF & Cloud Run | **Completed & Verified** | Fixed Cloud Run internal container reverse proxy origin resolution (`getPublicOrigin`) so redirects never target `localhost:8080`. Added `/api/auth/logout` route issuing `Set-Cookie: cargoclear_session_token=; Max-Age=0` and wired to all client logout triggers. |
| **Phase 7** | Dual-Tab Auth Portal & Landing Page Entry | Frontend UI | **Completed & Verified** | Updated `/auth/signin` with "🔑 Sign In" and "📝 Sign Up (New User)" tabs, live error switching, Google SSO buttons, password verification, and tamper-evident audit badge. Added explicit "Sign In" and "Register" buttons in landing page header and portal card. |
| **Phase 7** | Cloud Deployment Revisions | Google Cloud Run (`asia-south1`) | **Completed & Live** | `cargoclear-api` revision `cargoclear-api-00018-68t` and `cargoclear-ui` revision `cargoclear-ui-00017-r66` deployed and serving 100% of production traffic. |

---

## 6. What is Pending / External Configuration

1. **Google Cloud Console OAuth 2.0 Client Credentials (One-time GCP configuration)**:
   - The application code, routing, and token handling for Google SSO are 100% complete and deployed.
   - For live 1-click Google login without manual client ID entry, an administrator needs to:
     - Register an OAuth 2.0 Web Client in GCP Console under project `cargoclear-hackathon`.
     - Whitelist the redirect URI:
       `https://cargoclear-ui-448522365737.asia-south1.run.app/api/auth/callback/google`
     - Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in Cloud Run env vars.
   - *Fallback already operational*: Until those env vars are set, the UI displays dynamic client ID entry, full Email + Password registration & login, and 1-click demo presets.
2. **Git Branch Merge**:
   - All changes are currently committed and pushed to `feature/sso-authentication`. Ready for merge to `development` or `main`.
