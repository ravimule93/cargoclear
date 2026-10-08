# CargoClear-JAPAC — Analysis & Implementation Roadmap

> **Source of Truth:** v4.0 Product & Technical Specification + Detailed Technical Implementation Plan

---

## 1. System Summary

**CargoClear-JAPAC** is a pre-submission adversarial customs adjudicator for JAPAC cross-border trade. It is **not** a chatbot or autonomous filer. It is a **decision-support workbench** for Custom House Agents (CHAs).

### Core Value Loop
```
Upload trade bundle (Invoice + BoL + Packing List + Certs)
  → Multimodal extraction (Gemini 2.5 Flash, Vertex AI, structured JSON)
  → Deterministic math + entity checks (pure Python)
  → BigQuery AHTN tariff grounding (Vector Search)
  → Compliance status + visual bounding-box citations
  → Reasoning Delta (before/after diff on reassessment)
  → CHA makes the final decision
```

### Hero Demo Path (Case C — MVP Requirement)
Steel pipes (HS 7304) bundle → `MISSING_EVIDENCE` (no Mill Test Certificate) → upload MTC → `COMPLIANT_FOR_SUBMISSION` + Reasoning Delta.

- **Reference Guide**: See [HOW_TO_RUN_AND_DEMO.md](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/docs/HOW_TO_RUN_AND_DEMO.md) for full execution steps, judge walkthrough, and deployment guide.

### Architectural Transparency
1. **Hardcoding**: None. Implements real production calculations ($|\Delta| \le \max(0.5\% \times \text{gross}, 5\text{ kg})$), tare logic, status precedence resolution, SHA-256 hash chaining, and real SSE event streaming. Cloud adapters (Vertex AI, GCS, BigQuery, Firestore) use a dual-mode pattern: live cloud APIs when GCP credentials are provided, with resilient offline fallbacks for local developer environments.
2. **Vertex AI Agent Creation**: Fully code-defined via the `google-genai` SDK and `google-adk`. Zero manual setup or clicking in the Vertex AI console is required.
3. **Synthetic / Seed Data**: Used strictly for standard development fixtures (BigQuery AHTN master tariff seed rows, offline test fixtures, and default frontend workbench initial view).

---

## 2. Architecture

```
Browser (Next.js 15, App Router)
  ↓ POST /api/proxy/* (BFF)       ↓ EventSource (direct SSE)
FastAPI Backend (Cloud Run, asia-south1)
  ├─ GCS: raw + processed PDFs
  ├─ Firestore: case state, audit chain
  └─ ADK Workflow (fire-and-forget asyncio task)
       ├─ Extraction Agent   → Gemini 2.5 Flash (structured JSON)
       ├─ Discrepancy Agent  → Pure Python (math + entity)
       └─ Grounding Agent    → BigQuery Vector Search (AHTN)
```

---

## 3. Technology Stack (Locked)

| Layer | Technology |
|---|---|
| Frontend | TypeScript 5.x · Next.js 15 App Router · React 19 |
| Styling | Tailwind CSS v4 · CSS custom properties |
| UI Primitives | Radix UI (unstyled) · shadcn/ui patterns |
| PDF Rendering | `pdfjs-dist` + HTML5 `<canvas>` |
| Backend | Python 3.12 · FastAPI · Pydantic v2 |
| Agent Framework | `google-adk >= 2.6.3` · `google-genai` SDK |
| LLM | `gemini-2.5-flash` (asia-south1, live) · `gemini-2.5-pro` (global, batch P2) |
| Storage | GCS (asia-south1) · Firestore · BigQuery (AHTN + TREE_AH index) |
| CI/CD | Cloud Build → Cloud Run |
| Testing | pytest · Playwright · axe-core · schemathesis |

---

## 4. Feature Modules & Priority

### P0 — Critical (Hero Demo Blockers)
| # | Feature | Status |
|---|---|---|
| P0-1 | Project skeleton (repo layout, configs, env) | ⬜ |
| P0-2 | PDF upload → GCS | ⬜ |
| P0-3 | Bundle CRUD (Firestore) | ⬜ |
| P0-4 | PDF preprocessing (deskew, binarize, split) | ⬜ |
| P0-5 | Gemini 2.5 Flash multimodal extraction (Pydantic schema) | ⬜ |
| P0-6 | Deterministic math engine (weight parity, entity alignment, HS check) | ⬜ |
| P0-7 | Status resolution (4 statuses + precedence) | ⬜ |
| P0-8 | SSE stream endpoint | ⬜ |
| P0-9 | Reasoning Delta builder | ⬜ |
| P0-10 | Case C end-to-end (MISSING_EVIDENCE → upload → reassess → COMPLIANT) | ⬜ |
| P0-11 | Frontend workbench shell (4-panel grid) | ⬜ |
| P0-12 | File dropzone + upload flow | ⬜ |
| P0-13 | Assessment panel + StatusPill | ⬜ |
| P0-14 | SSE listener (live status updates) | ⬜ |
| P0-15 | Reasoning Delta drawer | ⬜ |

### P1 — Judges' "Wow" Factor
| # | Feature | Status |
|---|---|---|
| P1-1 | BigQuery AHTN tariff grounding (Vector Search + TreeAH) | ⬜ |
| P1-2 | Firestore append-only hash-chained audit trail | ⬜ |
| P1-3 | Visual bounding-box HITL (canvas overlay) | ⬜ |
| P1-4 | Confidence routing (auto-accept / review / manual) | ⬜ |
| P1-5 | WCAG 2.2 AA / ARIA live regions | ⬜ |
| P1-6 | Cloud Build → Cloud Run CI/CD | ⬜ |
| P1-7 | Audit timeline UI | ⬜ |

### P2 — Post-MVP / Out of Scope
- Vertex AI Batch API (50+ docs)
- Authentication / SSO
- Live ICEGATE / ASW / TradeNet integration
- Multi-model consensus / debate
- Predictive risk scoring / duty calculation

---

## 5. Database Entities (Firestore)

| Collection | Fields |
|---|---|
| `bundles/{id}` | `id`, `status`, `created_at`, `documents[]`, `current_iteration` |
| `bundles/{id}/documents/{id}` | `document_id`, `gcs_uri`, `sha256`, `doc_type`, `transform_meta` |
| `bundles/{id}/iterations/{n}` | `iteration`, `status`, `checks[]`, `missing_evidence[]`, `confidence`, `reasoning_delta`, `grounding[]` |
| `bundles/{id}/audit/{event_id}` | `seq`, `ts`, `actor`, `event_type`, `payload`, `prev_hash`, `hash` |
| `bundles/{id}/runs/{run_id}` | `state` (QUEUED/RUNNING/COMPLETE/ERROR), `stage`, `progress` |

---

## 6. API Surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/bundles` | Create bundle |
| `POST` | `/api/v1/bundles/{id}/documents` | Upload PDF |
| `GET` | `/api/v1/bundles/{id}` | Get bundle |
| `GET` | `/api/v1/documents/{id}/file` | Serve raw PDF |
| `POST` | `/api/v1/bundles/{id}/analyze` | Start full assessment pipeline |
| `POST` | `/api/v1/bundles/{id}/reassess` | Reassess after new document |
| `GET` | `/api/v1/bundles/{id}/assessment` | Latest assessment iteration |
| `GET` | `/api/v1/bundles/{id}/iterations` | All iterations (for delta) |
| `GET` | `/api/v1/bundles/{id}/stream` | SSE status stream |

---

## 7. Feature Dependency Graph

```
P0-1 (skeleton)
  ↓
P0-2 (GCS upload) + P0-3 (Firestore CRUD)
  ↓
P0-4 (preprocessing)
  ↓
P0-5 (extraction agent) + P0-6 (math engine) + P0-7 (status)
  ↓
P0-8 (SSE) + P0-9 (reasoning delta)
  ↓
P0-10 (Case C E2E)
  ↓
P1-1 (BQ grounding) + P1-2 (audit) + P1-3 (bbox) + P1-4 (confidence)
  ↓
P1-5 (WCAG) + P1-6 (CI/CD) + P1-7 (audit UI)
```

---

## 8. Authentication & Authorization

> [!IMPORTANT]
> Auth/SSO is **explicitly P2 / out of scope** for MVP. No user-facing login is required.

- Cloud Run services use a **dedicated service account** (`cargoclear-sa`) with least-privilege IAM:
  - `roles/aiplatform.user`
  - `roles/storage.objectAdmin` (scoped to bucket)
  - `roles/bigquery.dataViewer`
  - `roles/run.invoker`
- Firestore security rules deny `update/delete` on audit subcollection (tamper-evident).
- Frontend BFF proxy forwards calls server-side; browser never holds a bearer token.

---

## 9. Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Gemini malformed JSON | `RetryConfig(max_attempts=3)` + schema flattening (no discriminated unions) |
| SSE stream timeout on Cloud Run | `--timeout 300`, `--no-cpu-throttling`, `ping=15` on `EventSourceResponse` |
| Bbox drift on split/rotated pages | `transform_meta` stored; `toOriginalPage()` applies inverse transform in UI |
| BigQuery vector index not ready | Fallback `WHERE hs_code LIKE '7304%'` when distance is null |
| Demo env flakiness | Pre-loaded fixtures + `?fixture=case-c` query param |
| Scope creep | Strict P0/P1/P2 boundary enforced |

---

## 10. Ambiguities & Assumptions

| Item | Assumption |
|---|---|
| ADK `Workflow` vs pure `asyncio` | Spec provides both patterns. **Decision:** Use pure `asyncio`-based stage dispatcher (`orchestrator.py`) wrapping ADK `Agent` objects for extraction & grounding. This avoids ADK DAG-vs-FastAPI integration complexity while still using ADK for LLM agents. |
| `google-adk >= 2.6.3` import paths | The spec shows `from google.adk import Agent, Workflow` and `from google.adk.workflow import node, RetryConfig`. **Assumption:** Will verify at install time; skeleton uses try/except guard. |
| BigQuery AHTN data loading | Spec says "load AHTN subset." **Assumption:** Skeleton includes schema DDL and a seed script; actual data loaded separately via bootstrap. |
| `fastapi.sse` module | `sse-starlette` package provides `EventSourceResponse`. **Assumption:** Use `sse-starlette`, not a nonexistent `fastapi.sse` module. |
| Firestore async client | Standard `google-cloud-firestore` is sync; async variant via `AsyncClient`. **Assumption:** Use async Firestore client throughout. |
| Frontend BFF vs direct SSE | Spec is explicit: BFF proxy for mutations; direct `EventSource` for SSE. This is implemented as written. |

---

## 11. Phased Implementation Roadmap

### Phase 0 — Skeleton (this step)
Set up the complete project structure, configuration, shared types, linting, and build tooling. **No business logic.** Verify build + install succeed.

### Phase 1 — Core Backend Foundation
- Bundle CRUD (Firestore)
- PDF upload to GCS
- Preprocessing service (stub with real interface)
- Domain schemas (Pydantic)
- Status resolution
- SSE stream endpoint
- Error handling middleware

### Phase 2 — AI Pipeline (Extraction + Math)
- Extraction agent (Gemini 2.5 Flash, Pydantic structured output)
- Discrepancy engine (weight parity, entity alignment, HS check)
- Confidence routing
- Orchestrator pipeline
- Reasoning Delta builder
- Audit service (hash chain)

### Phase 3 — BigQuery Grounding
- AHTN schema DDL + seed data
- Vector Search tool
- Grounding agent
- Missing evidence detection

### Phase 4 — Frontend Workbench
- 4-panel grid layout + design tokens
- Document rail
- Upload dropzone
- Assessment panel + StatusPill + CheckList + MissingEvidenceCard
- SSE live updates (hook)
- BFF proxy routes

### Phase 5 — HITL & Reasoning Delta UI
- PDF viewer (pdfjs-dist)
- Bounding box canvas overlay (BBoxLayer)
- Coordinate transform (bbox.ts)
- Reasoning Delta drawer
- Audit timeline
- ARIA live regions + focus management

### Phase 6 — Case C E2E Integration
- Full upload → analyze → MISSING_EVIDENCE → reassess → COMPLIANT flow
- Integration test fixtures
- Playwright E2E tests (Case A, B, C)

### Phase 7 — Hardening & CI/CD
- Unit tests (≥95% on calculation.py)
- axe-core a11y tests
- schemathesis API contract tests
- Cloud Build YAML
- Deploy scripts

---

## 12. Project Skeleton Structure

```
cargoclear/
├── frontend/                          # Next.js 15 (TypeScript, App Router)
│   ├── app/
│   │   ├── layout.tsx                 # Root layout + LiveRegionRoot
│   │   ├── page.tsx                   # Redirect → /workbench
│   │   ├── globals.css                # design tokens (WCAG contrast)
│   │   ├── workbench/
│   │   │   └── [bundleId]/
│   │   │       ├── layout.tsx         # WorkbenchShell grid
│   │   │       └── page.tsx           # Server component
│   │   └── api/
│   │       └── proxy/
│   │           └── [...path]/
│   │               └── route.ts       # BFF proxy
│   ├── components/
│   │   ├── shell/TopBar.tsx
│   │   ├── rail/DocumentRail.tsx
│   │   ├── viewer/DocumentViewer.tsx
│   │   ├── viewer/BBoxLayer.tsx
│   │   ├── facts/FactsPanel.tsx
│   │   ├── assess/AssessmentPanel.tsx
│   │   ├── assess/StatusPill.tsx
│   │   ├── assess/CheckList.tsx
│   │   ├── assess/MissingEvidenceCard.tsx
│   │   ├── delta/ReasoningDelta.tsx
│   │   ├── delta/DeltaDrawer.tsx
│   │   ├── audit/AuditTimeline.tsx
│   │   ├── upload/UploadDropzone.tsx
│   │   └── a11y/LiveRegion.tsx
│   ├── lib/
│   │   ├── api.ts                     # typed fetch client
│   │   ├── sse.ts                     # EventSource wrapper
│   │   ├── types.ts                   # shared domain types
│   │   ├── bbox.ts                    # coordinate transform
│   │   └── hooks/useBundleStream.ts   # SSE React hook
│   ├── styles/
│   │   └── workbench.css             # grid layout
│   ├── public/                        # pdf.worker.min.mjs placed here
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── postcss.config.mjs
│   └── package.json
│
├── backend/                           # FastAPI (Python 3.12)
│   ├── app/
│   │   ├── main.py                    # FastAPI app, middleware, routers
│   │   ├── core/
│   │   │   └── config.py             # pydantic-settings BaseSettings
│   │   ├── gateway/
│   │   │   ├── middleware.py         # RequestContext, ErrorEnvelope, CORS
│   │   │   ├── errors.py             # CargoClearError hierarchy
│   │   │   └── dispatch.py           # stage → handler registry
│   │   ├── api/v1/
│   │   │   ├── __init__.py
│   │   │   ├── bundles.py            # POST /bundles, GET /bundles/{id}
│   │   │   ├── documents.py          # POST /bundles/{id}/documents, GET /documents/{id}/file
│   │   │   ├── assessment.py         # POST analyze/reassess, GET assessment/iterations
│   │   │   └── stream.py             # GET /bundles/{id}/stream (SSE)
│   │   ├── domain/
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py            # Pydantic extraction models (BBox, FieldRef, ExtractedDocument)
│   │   │   ├── status.py             # 4 statuses + resolve_status()
│   │   │   └── events.py             # SSE event contracts
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── storage.py            # GCS upload/download
│   │   │   ├── preprocess.py         # deskew, binarize, split
│   │   │   ├── calculation.py        # deterministic math engine
│   │   │   ├── audit.py              # hash-chained Firestore append
│   │   │   ├── reasoning.py          # Reasoning Delta builder
│   │   │   ├── confidence.py         # confidence routing table
│   │   │   └── orchestrator.py       # asyncio pipeline runner
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── workflow.py           # ADK Workflow DAG definition
│   │   │   ├── extraction.py         # Extraction agent + run fn
│   │   │   ├── grounding.py          # Grounding agent + run fn
│   │   │   ├── nodes.py              # Thin ADK node wrappers
│   │   │   └── tools/
│   │   │       ├── __init__.py
│   │   │       └── bq_tariff.py      # BigQuery Vector Search tool
│   │   └── repo/
│   │       ├── __init__.py
│   │       ├── firestore.py          # Async Firestore operations
│   │       └── bigquery.py           # BQ client helpers
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── unit/
│   │   │   ├── test_calculation.py
│   │   │   ├── test_status.py
│   │   │   ├── test_audit.py
│   │   │   └── test_confidence.py
│   │   └── integration/
│   │       └── test_api.py
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── .env.example
│   ├── Dockerfile
│   └── pyproject.toml                # pytest + ruff config
│
├── infra/
│   ├── bootstrap.sh                  # Day-0 GCP setup as code
│   ├── deploy_api.sh
│   ├── deploy_ui.sh
│   ├── bigquery/
│   │   ├── schema.json               # master_tariff table schema
│   │   ├── vector_index.sql          # TreeAH DDL
│   │   └── seed/                     # Sample AHTN data
│   └── iam/
│       └── roles.yaml
│
├── cloudbuild.yaml                   # CI/CD
├── .gitignore
└── README.md
```

---

## 13. Implementation Checklist

### ✅ Completed
- P0-1: Project skeleton (modular monorepo structure, contracts, configs, env)
- P0-2: PDF upload & content-addressed storage (SHA-256 derivation, GCS adapter + local fallback)
- P0-3: Bundle CRUD & Firestore persistence (Async repository + in-memory fallback, audit event emission)
- P0-4: PDF preprocessing (deskew, orientation detection, transform metadata for UI remapping, auto-split trigger)
- P0-5: Multimodal Gemini 2.5 Flash extraction agent (Vertex AI asia-south1, strict Pydantic response_schema, retry mechanism)
- P0-6: Deterministic math engine (weight parity tolerance calculation, entity alignment, HS check)
- P0-7: Status resolution (4 statuses + precedence resolution matrix)
- P0-8: Real-time SSE stream endpoint & asynchronous background orchestration
- P0-9: Reasoning Delta builder (side-by-side iteration diffing and explanation)
- P0-10: Case C end-to-end hero flow (Missing evidence -> Upload MTC -> Reassess -> Compliant for submission)
- P0-11: Frontend workbench shell layout & navigation (responsive 4-panel investigator grid)
- P0-12: Interactive upload dropzone & document rail (drag-and-drop, active document switching)
- P0-13: Assessment panel & StatusPill live binding (rule checklist, missing evidence cards)
- P0-14: Real-time SSE stream listener & Reassess action triggers
- P0-15: Reasoning Delta drawer & ARIA accessibility live regions (WCAG 2.2 AA compliant announcements & focus management)
- P1-1: BigQuery AHTN Grounding (TREE_AH Cosine Vector Search, distance ambiguity threshold, official required documents lookup)
- P1-2: Firestore append-only hash-chained audit trail & security rules (SHA-256 cryptographic chaining, tamper verification, firestore.rules)
- P1-4: Confidence routing engine (4-tier routing table: auto-accept, auto-flag, interactive review, manual entry)
- P1-5: WCAG 2.2 AA accessibility & Playwright E2E test suite (axe-core audit with 0 critical violations, Hero Case C journey test)
- P1-6: Automated CI/CD Cloud Build pipeline (multi-step backend test, frontend typecheck/build, and Cloud Run deployments)

### 🔄 In Progress
- Production GCP project bootstrap execution (`infra/bootstrap.sh`) when user supplies active project credentials

### ⬜ Remaining / Post-MVP (P2)
- Vertex AI Batch API for 50+ document bundles
- Authentication / SSO for CHAs
- Real-time ASW / ICEGATE government portal submission integration

### 🚫 Blocked
- GCP bootstrap (needs project creation by user)

### 📝 Known Technical Debt
- ADK `Workflow` DAG patterns need runtime verification once GCP is available
- AHTN seed data sourcing (requires public AHTN tables download)

### ❓ Open Questions for User
1. **GCP Project ID:** Is `cargoclear-hackathon` confirmed, or should a different project ID be used?
2. **ADK version:** Has `google-adk >= 2.6.3` been verified installable in your environment?
3. **AHTN Data:** Do you have the AHTN master tariff data ready for BigQuery loading?
