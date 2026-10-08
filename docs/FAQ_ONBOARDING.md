# CargoClear-JAPAC: New Team Member Onboarding & Developer FAQ

> Welcome to the CargoClear-JAPAC project!  
> This guide is designed to get new developers, architects, and contributors up to speed quickly with the domain, system architecture, design decisions, and day-to-day development workflow.

---

## Table of Contents
1. [Domain & Problem Overview](#1-domain--problem-overview)
2. [Architecture & System Design](#2-architecture--system-design)
3. [AI & Agent Architecture (Gemini 2.5 Flash & BigQuery)](#3-ai--agent-architecture-gemini-25-flash--bigquery)
4. [Data Model, Cryptography & Storage](#4-data-model-cryptography--storage)
5. [Local Development & Dual-Mode Execution](#5-local-development--dual-mode-execution)
6. [Frontend & Accessibility (WCAG 2.2 AA)](#6-frontend--accessibility-wcag-22-aa)
7. [Codebase Navigation Cheat Sheet](#7-codebase-navigation-cheat-sheet)

---

## 1. Domain & Problem Overview

### Q1: What is CargoClear-JAPAC in simple terms?
**CargoClear** is an adversarial pre-submission customs adjudication tool designed for cross-border trade in the JAPAC region (initially targeting the Singapore / ASEAN Single Window trade corridors, conforming to e-SANCHIT standards).

Before a shipment's paperwork is formally submitted to government customs authorities (like Singapore Customs or India ICEGATE), CargoClear acts as a "devil's advocate" customs inspector. It analyzes the entire trade bundle (Invoice, Bill of Lading, Packing List, Certificates), runs mathematical and regulatory checks, and flags discrepancies *before* submission.

### Q2: Why is it called an "adversarial adjudicator" and NOT a chatbot or auto-filer?
- **Not a chatbot**: Trade compliance officers (Custom House Agents / CHAs) cannot afford conversational guesswork, hallucinated tariff codes, or chat interfaces. They need an investigator-style, structured workbench with instant visual evidence citations.
- **Not an auto-filer**: Legal liability for customs declarations rests entirely on the authorized licensed CHA. CargoClear provides strict **decision support**—the human CHA always makes the final legal filing decision.
- **Adversarial**: It proactively attempts to "break" the trade bundle by searching for weight mismatches, undeclared HS code divergences, and missing mandatory regulatory permits before real customs inspectors penalize the importer.

### Q3: What is "Case C" (the Hero Journey)?
In trade compliance, certain goods require mandatory non-standard certificates. 
- **The Scenario**: An exporter ships seamless carbon steel line pipe (`HS 7304.19.00`).
- **Initial State**: The bundle contains only Invoice, Bill of Lading, and Packing List.
- **Adjudication**: Math checks pass, but BigQuery AHTN tariff grounding identifies that Chapter 73 rules strictly mandate a **Mill Test Certificate (MTC)**. Status is flagged as **`MISSING_EVIDENCE`**.
- **Resolution**: The CHA uploads the MTC. The system reassesses the bundle, resolves the requirement, transitions status to **`COMPLIANT_FOR_SUBMISSION`**, and generates a **Reasoning Delta** explaining why the status changed.

---

## 2. Architecture & System Design

### Q4: How is the repository structured?
We use a **modular monorepo** with strict directory boundaries:
```
gcp-cup-poc/
├── backend/                  # FastAPI (Python 3.12, Clean Architecture)
│   ├── app/
│   │   ├── api/v1/           # REST endpoints & SSE stream
│   │   ├── core/             # Settings & configuration
│   │   ├── domain/           # Pure Pydantic models (zero cloud dependencies)
│   │   ├── gateway/          # Middleware & stage dispatcher
│   │   ├── services/         # Deterministic math, reasoning delta, storage, audit
│   │   ├── agents/           # Gemini extraction & BigQuery grounding agents
│   │   └── repo/             # Firestore & BigQuery adapters
│   └── tests/                # Unit and integration test suite
├── frontend/                 # Next.js 15 App Router (React 19, TypeScript)
│   ├── app/                  # Route layouts, workbench shell, BFF proxy
│   ├── components/           # UI components (Viewer, Rail, Assessment, DeltaDrawer)
│   ├── lib/                  # Fetch client, SSE hook, bbox transform helpers
│   ├── styles/               # WCAG 2.2 AA contrast design tokens
│   └── tests/                # Playwright & axe-core automated tests
├── infra/                    # GCP bootstrap, BigQuery DDL, seed data, IAM roles
├── docs/                     # Product specs, implementation plan, how-to guides
└── cloudbuild.yaml           # Automated CI/CD pipeline
```

### Q5: Why are the frontend and backend in the same repo if we might split them later?
During the MVP and hackathon phase, a modular monorepo allows atomic git commits across UI, API, and type contracts without version mismatch friction. However, **zero code is cross-imported between `frontend/` and `backend/`**—they communicate strictly over HTTP/OpenAPI contracts. After MVP, directories can be extracted into standalone repos (`cargoclear-api`, `cargoclear-ui`, `cargoclear-infra`) using `git subtree split` with zero refactoring.

### Q6: What is the Next.js BFF proxy (`/api/proxy/[...path]`)?
The browser UI never stores bearer tokens or talks directly to internal endpoints for write mutations. It calls `/api/proxy/*`, and the Next.js server forwards requests to the Cloud Run FastAPI backend. 
*(Exception: Server-Sent Events connect directly to the backend stream endpoint to prevent proxy buffering from stalling live event streaming).*

---

## 3. AI & Agent Architecture (Gemini 2.5 Flash & BigQuery)

### Q7: Do I need to manually configure agents in Vertex AI Agent Builder?
**No. Zero manual setup in Vertex AI console is needed.**  
Agents are **code-defined**:
- **Extraction Agent (`app/agents/extraction.py`)**: Uses the new `google-genai` SDK targeting `gemini-2.5-flash` in `asia-south1`. The prompt, instructions, temperature (`0.0`), and Pydantic model (`response_schema=ExtractedDocument`) are configured entirely in code.
- **Grounding Agent (`app/agents/grounding.py`)**: It is a tool-calling agent querying BigQuery Vector Search via SQL (`VECTOR_SEARCH(TABLE master_tariff, ...)`). Vector index generation is handled via BigQuery DDL.

### Q8: How does the Extraction Agent prevent hallucinations?
1. **Strict Spatial Prompt**: The system prompt explicitly commands the model to extract *only verbatim printed text* on the page and never guess or infer.
2. **Pydantic Response Schema**: Gemini's output is forced into the rigid `ExtractedDocument` schema at the API generation level.
3. **Bounding Box Provenance**: Every extracted scalar value is wrapped in a `FieldRef` containing `[ymin, xmin, ymax, xmax]` normalized coordinates (0–1000) and an extraction confidence score `[0.0, 1.0]`. If a field is not on the page, it returns `null` with confidence `0.0`.

### Q9: How does BigQuery Vector Search tariff grounding work?
- The master AHTN tariff table (`ahtn.master_tariff`) contains official tariff lines with pre-computed text embeddings in `description_embedding`.
- A BigQuery Vector Index (`TREE_AH`, ScaNN-based) indexes these embeddings using **Cosine Distance**.
- When an extracted commodity description is grounded, BigQuery executes `ML.GENERATE_EMBEDDING` and searches the top 5 nearest candidates.
- **Ambiguity Rule**: If the top candidate's cosine distance is $> 0.35$, the match is flagged as `ambiguous = True`, automatically routing the bundle status to `SPECIALIST_REVIEW_REQUIRED`.

---

## 4. Data Model, Cryptography & Storage

### Q10: How does content-addressed storage work?
When a PDF document is uploaded:
1. The backend computes its SHA-256 digest over the raw byte stream.
2. The unique `document_id` is derived deterministically: `doc-{sha16}`.
3. The file is uploaded to `gs://cargoclear-raw-pdfs/bundles/{bundle_id}/raw/{document_id}/original.pdf`.
4. Re-uploading identical bytes yields the identical ID (idempotent). Uploading altered bytes produces a new ID and registers a new immutable audit record.

### Q11: How does the cryptographic audit hash chain work?
Every audit event (`BUNDLE_CREATED`, `DOCUMENT_UPLOADED`, `ASSESSMENT_COMPLETED`) is linked to its predecessor:
$$\text{hash}_n = \text{SHA-256}(\text{prev\_hash} + \text{str}(\text{seq}) + \text{ts} + \text{canonical\_json}(\text{payload}))$$
- Event 1 has `prev_hash = "GENESIS"`.
- Each subsequent event includes the hash of the preceding event.
- Firestore security rules (`infra/firestore.rules`) strictly enforce `allow create: if true; allow update, delete: if false;`.
- The verification function `verify_audit_chain()` can replay the chain from genesis to tip to prove mathematically that no records were altered or deleted.

### Q12: What is the Status Precedence rule?
When multiple checks and agents report results, the bundle's final status is resolved using a strict precedence order:
$$\text{MATERIAL\_CONTRADICTION} > \text{MISSING\_EVIDENCE} > \text{SPECIALIST\_REVIEW\_REQUIRED} > \text{COMPLIANT\_FOR\_SUBMISSION}$$
If a weight check fails, the status is always `MATERIAL_CONTRADICTION`, even if another document is missing.

---

## 5. Local Development & Dual-Mode Execution

### Q13: Can I run and test the app locally without GCP credentials?
**Yes!** The system implements a **Dual-Mode Graceful Adapter Pattern**:
- **Offline / Local Mode (Default)**:
  - If no `GOOGLE_APPLICATION_CREDENTIALS` are found, storage uses a local folder (`.storage_cache/`), Firestore uses in-memory dictionaries, and BigQuery vector lookup uses local seed rows (`infra/bigquery/seed/sample_tariff.json`).
  - Unit tests and E2E integration tests run and pass without network calls or billing.
- **Live GCP Mode**:
  - Point `GOOGLE_APPLICATION_CREDENTIALS` to a service account JSON file, and the application automatically routes to live Cloud Storage, Firestore, BigQuery, and Vertex AI.

### Q14: How do I run the backend locally?
```bash
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1    # On Windows
# source venv/bin/activate     # On Linux/macOS

pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```
Swagger UI is available at [http://localhost:8080/docs](http://localhost:8080/docs).

### Q15: How do I run the frontend locally?
```bash
cd frontend
npm install
npm run dev
```
Workbench UI is available at [http://localhost:3000/workbench/HERO-CASE-C-7304](http://localhost:3000/workbench/HERO-CASE-C-7304).

---

## 6. Frontend & Accessibility (WCAG 2.2 AA)

### Q16: How is WCAG 2.2 AA compliance enforced?
- **Color Contrast**: All text colors in `frontend/app/globals.css` are documented with contrast ratios $\ge 4.5:1$ against their backgrounds; graphical borders are $\ge 3:1$.
- **Keyboard Navigation**: All interactive elements are reachable via `Tab`, and tablists in `DeltaDrawer` support `ArrowLeft`/`ArrowRight` navigation stop controls.
- **Screen Reader Announcements**: `LiveRegion.tsx` provides dual ARIA live regions:
  - `aria-live="polite"` for non-disruptive stage progression.
  - `role="alert"` with `aria-live="assertive"` for critical rejections and material contradictions.
- **Automated Audit**: Automated tests in `frontend/tests/a11y.spec.ts` use `@axe-core/playwright` across tags `wcag2a`, `wcag2aa`, `wcag21aa`, `wcag22aa` ensuring 0 critical or serious violations.

---

## 7. Codebase Navigation Cheat Sheet

| Task / Objective | Files to Touch |
| :--- | :--- |
| **Add or modify a deterministic math check** | [`backend/app/services/calculation.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/services/calculation.py), [`backend/tests/unit/test_calculation.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/tests/unit/test_calculation.py) |
| **Add a new trade document type** | [`backend/app/domain/schemas.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/domain/schemas.py) (`DocType` enum), [`frontend/lib/types.ts`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/frontend/lib/types.ts) |
| **Tweak Gemini extraction prompt or schema** | [`backend/app/agents/extraction.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/agents/extraction.py) (`SYSTEM_INSTRUCTION`, `ExtractedDocument`) |
| **Update BigQuery tariff seed or index DDL** | [`infra/bigquery/seed/sample_tariff.json`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/infra/bigquery/seed/sample_tariff.json), [`infra/bigquery/vector_index.sql`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/infra/bigquery/vector_index.sql) |
| **Adjust design tokens or status badge colors** | [`frontend/app/globals.css`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/frontend/app/globals.css), [`frontend/components/assess/StatusPill.tsx`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/frontend/components/assess/StatusPill.tsx) |
| **Modify pipeline stages or progress weights** | [`backend/app/services/orchestrator.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/backend/app/services/orchestrator.py) (`PIPELINE_STAGES`, `_STAGE_PROGRESS`) |
| **Run the complete test suite** | `pytest tests/unit tests/integration` (backend), `npx playwright test` (frontend) |
