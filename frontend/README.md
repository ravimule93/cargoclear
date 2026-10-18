# CargoClear Frontend UI

> **Google Cloud AI Builder Cup 2026** | Next.js 15 Customs Assessment Workbench

The CargoClear frontend is a modern, responsive web application engineered with **Next.js 15 (App Router)**, **React 19**, and **Tailwind CSS**. It provides customs brokers, agents, and trade compliance officers with an evidence-grounded workbench for inspecting multi-document trade bundles, reviewing automated compliance analyses, making audited in-place corrections, and generating pre-fill customs packs.

---

## Architecture & Security Highlights

### 1. Backend-for-Frontend (BFF) Proxy Architecture
Browser clients never communicate directly with the private Cloud Run API. All API calls and Server-Sent Events (SSE) route through the same-origin Next.js server route:

$$\text{Browser Client} \xrightarrow{\text{Same-Origin HTTPS}} \text{Next.js BFF (/api/proxy/...)} \xrightarrow{\text{Google ID Token}} \text{Private Cloud Run API}$$

- **Zero Credential Leakage**: Service account tokens and private backend URLs exist only in server memory.
- **Header Sanitization**: The BFF automatically attaches client IP tracking (`x-cargoclear-client-ip`) while stripping spoofed client-supplied security headers.
- **Dual Session Cookie Support**: Seamlessly reconciles session tokens across standard Cloud Run domains and Firebase Hosting CDN rewrites.

### 2. Evidence Grounding & Bounding Box Viewer
- **PDF.js Canvas Rendering**: Renders multi-page trade documents locally with high visual fidelity.
- **Bounding Box Overlay**: Maps extracted facts directly to their exact physical pixel coordinates on the source document ("What the model saw").
- **Visual Confidence Indicators**: Flags low-confidence extractions with visual cues to prioritize human review.

### 3. Real-Time Streaming with Server-Sent Events (SSE)
- Streams granular pipeline stages (`UPLOADING`, `EXTRACTING`, `VERIFYING_METALLURGY`, `GROUNDING_HS_CODES`, `AUDITING`) directly to the UI without client polling.
- Live progress bars and status updates guide the user through asynchronous processing.

### 4. Human-in-the-Loop Agent Corrections
- Authorized agents can click **Edit** on any extracted evidence row (e.g., correcting an MTC chromium value from $0.35\%$ to $0.28\%$).
- All edits require a justification reason and are recorded in the cryptographic audit chain.
- Clicking **Recompute with corrections** invokes deterministic compliance rules instantly without calling the LLM again.

---

## Key Features & User Journeys

| Feature | Description |
| :--- | :--- |
| **Multi-File Bundle Upload** | Drag-and-drop upload for Invoices, Bills of Lading, Packing Lists, and Mill Test Certificates with automated document type classification. |
| **Case C Demo (India $\to$ Singapore)** | Missing document journey: Starts with 3 documents (`MISSING_EVIDENCE`), loads sample MTC, and achieves `COMPLIANT_FOR_SUBMISSION`. |
| **Case D Demo (India Import)** | Contradiction journey: 4 documents with MTC alloy chemistry contradicting declared non-alloy HS code (`MATERIAL_CONTRADICTION`), triggering anti-dumping duty warnings. |
| **Reasoning Delta** | Side-by-side differential view illustrating exactly what changed between consecutive assessment iterations. |
| **Declaration Pre-Fill Pack** | Instant export of customs declaration pre-fill packages in JSON and printable PDF formats. |
| **Google OAuth 2.0 / SSO** | Secure Google OIDC authentication with CSRF state cookies, tokeninfo verification, and 1-click demo login presets. |

---

## Directory Structure

```
frontend/
├── app/
│   ├── api/
│   │   ├── auth/                # Google OAuth callback, signin, and logout routes
│   │   └── proxy/[...path]/     # BFF server proxy forwarding requests to private API
│   ├── auth/                    # Sign-in page with Google SSO and demo presets
│   ├── workbench/[bundleId]/    # Main assessment workbench (split viewer, evidence, delta)
│   ├── layout.tsx               # Root application layout with navigation header
│   └── page.tsx                 # Landing page with demo case launchers and upload zone
├── components/
│   ├── workbench/               # Split-screen PDF viewer, analysis cards, and reasoning tabs
│   ├── pdf/                     # PDF.js canvas viewer with bounding box overlay renderer
│   ├── evidence/                # Evidence chips, verification tables, and correction modals
│   └── ui/                      # Reusable UI primitives (buttons, modals, badges, alerts)
├── lib/
│   ├── hooks/                   # React hooks (e.g., useBundleStream for SSE consumption)
│   ├── server/                  # Server-side proxy implementation and Google ID token fetcher
│   └── types.ts                 # Shared TypeScript interfaces and domain types
├── public/                      # Static assets, logos, and PDF.js worker files
├── scripts/                     # Helper build scripts (copy-pdf-worker.mjs)
├── Dockerfile                   # Multi-stage production container image (node:22-slim)
└── package.json                 # Next.js and frontend dependencies
```

---

## Local Setup & Development

### 1. Prerequisites
- Node.js 22+
- npm 10+

### 2. Installation
```bash
cd frontend
npm ci --legacy-peer-deps
```

### 3. Local Development Server
Connect the frontend to a locally running backend (`http://127.0.0.1:8080`):

```bash
API_BASE=http://127.0.0.1:8080 npm run dev
```

Open `http://localhost:3000` in your browser.

---

## Testing & Quality Assurance

CargoClear enforces strict linting, type safety, and unit test suites before any production deployment:

```bash
# Typecheck TypeScript codebase:
npm run typecheck

# Lint with ESLint:
npm run lint

# Run unit tests (server proxy, header sanitization):
npm run test:unit

# Build production bundle:
npm run build
```

---

## Environment Variables

| Variable | Scope | Description |
| :--- | :--- | :--- |
| `API_BASE` | Server-Only | URL of the backend API (e.g., `https://cargoclear-api-5ho4zmc74q-el.a.run.app`). |
| `API_AUTH_MODE` | Server-Only | Set to `google-id-token` in Cloud Run to fetch metadata tokens. |
| `GOOGLE_CLIENT_ID` | Public / Client | Google OAuth 2.0 Web Client ID for user sign-in. |
| `GOOGLE_CLIENT_SECRET` | Server-Only | Secret for Google OAuth code-to-token exchange. |
| `NEXT_PUBLIC_APP_MODE` | Client & Server| `demo` for offline demo fixtures; `live` for GCP services. |
| `PUBLIC_URL` | Server-Only | Public canonical URL (e.g., `https://cargoclear-app.web.app`). |
| `TRUSTED_PROXY_HOPS` | Server-Only | Number of upstream reverse proxies for client IP extraction (`1`). |

---

## Containerization

The production Dockerfile uses a 3-stage build (`deps`, `builder`, `runner`) on `node:22-slim` and runs as a non-privileged user:

```dockerfile
USER node
EXPOSE 8080
```
This guarantees compliance with enterprise container security benchmarks.
