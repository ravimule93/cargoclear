# CargoClear-JAPAC: Complete How-To, Deployment & Demonstration Guide

> **Project**: CargoClear-JAPAC — Pre-submission adversarial customs adjudicator for cross-border trade.
> **Competition**: Google Cloud AI Builder Cup 2026.

---

## Table of Contents
1. [Architecture & Design Transparency](#1-architecture--design-transparency)
   - [Q1: Is there any hardcoding done for the demo?](#q1-is-there-any-hardcoding-done-for-the-demo)
   - [Q2: Is there any need to create agents manually in Vertex AI?](#q2-is-there-any-need-to-create-agents-manually-in-vertex-ai)
   - [Q3: Is there any synthetic data generated?](#q3-is-there-any-synthetic-data-generated)
2. [Prerequisites](#2-prerequisites)
3. [Running Locally](#3-running-locally)
   - [Option A: Offline / Local Mode (Zero GCP setup)](#option-a-offline--local-mode-zero-gcp-setup)
   - [Option B: Live GCP Mode (Connected to Vertex AI & Cloud Run)](#option-b-live-gcp-mode-connected-to-vertex-ai--cloud-run)
4. [Deploying to Google Cloud](#4-deploying-to-google-cloud)
   - [Step 1: Day-0 Environment Bootstrap](#step-1-day-0-environment-bootstrap)
   - [Step 2: Automated Deployment via Cloud Build](#step-2-automated-deployment-via-cloud-build)
   - [Step 3: Direct Manual Deploy via Scripts](#step-3-direct-manual-deploy-via-scripts)
5. [Step-by-Step Demo Script for Judges (Hero Case C)](#5-step-by-step-demo-script-for-judges-hero-case-c)
6. [Testing & Verification](#6-testing--verification)

---

## 1. Architecture & Design Transparency

### Q1: Is there any hardcoding done for the demo?
**No.** The application is built using the **Graceful Dual-Mode Adapter Pattern**:
- **Deterministic Math Engine (`calculation.py`)**: 100% production code. Calculates weight parity using the exact specification formula:
  $$\sum w_{\text{net}} + w_{\text{tare}} \stackrel{?}{=} W_{\text{gross}} \quad (\text{tolerance: } |\Delta| \le \max(0.5\% \times W_{\text{gross}}, 5\text{ kg}))$$
  Checks HS code consistency and entity alignment across all documents.
- **Status Resolution (`status.py`)**: 100% production code. Strictly enforces the 4-status precedence hierarchy:
  $$\text{MATERIAL\_CONTRADICTION} > \text{MISSING\_EVIDENCE} > \text{SPECIALIST\_REVIEW\_REQUIRED} > \text{COMPLIANT\_FOR\_SUBMISSION}$$
- **Cryptographic Audit Trail (`audit.py`)**: 100% production code. Every event generates a real SHA-256 hash chaining to the previous block from `GENESIS`.
- **Reasoning Delta (`reasoning.py`)**: 100% production code. Evaluates real field-level diffs between iteration $N$ and $N-1$.
- **Adapters (GCS, Firestore, BigQuery, Vertex AI)**: When active GCP service credentials are provided, the system executes live API calls. If running locally without GCP credentials, it gracefully falls back to local caching and seed data so developers and CI/CD pipelines can run tests without crashes.

---

### Q2: Is there any need to create agents manually in Vertex AI?
**No. Zero manual agent creation in the Vertex AI console is required.**
- **Code-Defined Agents**: Agents are implemented programmatically via the `google-genai` SDK and `google-adk` framework.
- **Extraction Agent (`app/agents/extraction.py`)**: Calls `gemini-2.5-flash` in `asia-south1` dynamically. It passes the system prompt, instructions, temperature (`0.0`), and Pydantic response schema (`response_schema=ExtractedDocument`) at runtime.
- **Grounding Agent (`app/agents/grounding.py`)**: Direct BigQuery Vector Search tool (`VECTOR_SEARCH(...)` on `master_tariff`). Model embedding is handled via BigQuery ML (`ML.GENERATE_EMBEDDING`).
- **No Agent Builder UI**: You do not need to click or configure anything in the Vertex AI Agent Builder console.

---

### Q3: Is there any synthetic data generated?
Yes, for three clear engineering purposes:
1. **BigQuery AHTN Master Tariff Seed Data (`infra/bigquery/seed/sample_tariff.json`)**: Contains 4 official AHTN tariff entries (HS 7304, 7306, 1001, 0901) used to seed BigQuery during Day-0 setup and as an offline lookup fallback.
2. **Offline Extraction Fixtures (`app/agents/extraction.py`)**: Realistic typed `ExtractedDocument` objects used exclusively when running tests offline without an active Vertex AI billing account.
3. **Frontend Initial Demo State (`frontend/app/workbench/[bundleId]/page.tsx`)**: Default state representing trade bundle `EXP-SG-7304-001` so that the workbench UI renders immediately when opened in a browser before files are uploaded.

---

## 2. Prerequisites

- **Python**: $\ge 3.10$ (recommended: Python 3.12)
- **Node.js**: $\ge 18$ (recommended: Node.js 22 LTS)
- **Git**: Installed and configured
- **Google Cloud SDK (`gcloud`)**: (Optional, only required for Live GCP mode and deployment)

---

## 3. Running Locally

### Option A: Offline / Local Mode (Zero GCP setup)

You can run the full application on your laptop with zero cloud setup or credentials:

#### 1. Start the FastAPI Backend
```bash
cd backend

# Create and activate virtual environment
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run server on port 8080
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```
The API documentation will be available at [http://localhost:8080/docs](http://localhost:8080/docs).

#### 2. Start the Next.js Frontend
In a separate terminal:
```bash
cd frontend

# Install dependencies
npm install

# Start development server on port 3000
npm run dev
```

#### 3. Open the Workbench
Open your browser and navigate to:
[http://localhost:3000/workbench/HERO-CASE-C-7304](http://localhost:3000/workbench/HERO-CASE-C-7304)

---

### Option B: Live GCP Mode (Connected to Vertex AI & Cloud Run)

To run with live Google Cloud services:

1. **Set your GCP credentials**:
   ```powershell
   $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account-key.json"
   $env:PROJECT_ID = "your-gcp-project-id"
   $env:REGION = "asia-south1"
   ```
2. In `backend/.env`, set:
   ```env
   PROJECT_ID=your-gcp-project-id
   REGION=asia-south1
   RAW_BUCKET=cargoclear-raw-pdfs
   FIRESTORE_DATABASE=(default)
   BQ_DATASET=ahtn
   GEMINI_LIVE_MODEL=gemini-2.5-flash
   GEMINI_LIVE_LOCATION=asia-south1
   ```
3. Start the backend and frontend as shown in Option A. The application will automatically detect credentials and connect to live Vertex AI, Firestore, GCS, and BigQuery.

---

## 4. Deploying to Google Cloud

### Step 1: Day-0 Environment Bootstrap
Run the automated bootstrap script to provision all required GCP resources:
```bash
# Set your target project ID
export PROJECT_ID="your-gcp-project-id"
export REGION="asia-south1"

# Execute bootstrap script
bash ./infra/bootstrap.sh
```
This script automatically:
- Enables APIs: `aiplatform`, `storage`, `firestore`, `bigquery`, `run`, `cloudbuild`.
- Creates service account `cargoclear-sa` with least-privilege roles.
- Creates regional GCS bucket `gs://cargoclear-raw-pdfs`.
- Initializes Firestore database in `asia-south1`.
- Creates BigQuery dataset `ahtn` and provisions the vector index.

---

### Step 2: Automated Deployment via Cloud Build
Submit a single Cloud Build command to test, build, and deploy both services:
```bash
gcloud builds submit --config=cloudbuild.yaml
```

---

### Step 3: Direct Manual Deploy via Scripts
You can also deploy services individually:
```bash
# Deploy Backend API to Cloud Run
bash ./infra/deploy_api.sh

# Deploy Frontend UI to Cloud Run
bash ./infra/deploy_ui.sh
```

---

## 5. Step-by-Step Demo Script for Judges (Hero Case C)

Follow this exact walkthrough during judging presentations:

### Phase 1: Incomplete Bundle & Adversarial Detection
1. **Open Workbench**: Navigate to `/workbench/HERO-CASE-C-7304`.
2. **Present the Problem**:
   - Point out the 3 initial trade documents in the Document Rail: `Commercial_Invoice`, `Bill_of_Lading`, and `Packing_List`.
   - The declared commodity is **Seamless Carbon Steel Line Pipe (AHTN HS 7304.19.00)**.
3. **Show Initial Status**:
   - TopBar displays the amber status pill: **`Missing Evidence`**.
   - Assessment panel shows deterministic math check `W-001` has **`PASS`** (Net + Tare matches Gross within tolerance $\pm 71.4$ kg).
4. **Highlight Grounding Finding**:
   - Show the **Missing Evidence Card**:
     > *"Missing: Mill Test Certificate (MTC) — Mandatory material compliance certificate required under AHTN Chapter 73 rules for seamless pipes."*
   - Explain to judges: The system prevented an invalid customs submission before filing!

### Phase 2: Corrective Upload & Reassessment
1. **Upload Missing Document**:
   - In the upload dropzone, upload `mtc_pipe_test_cert.pdf`.
   - Click **Reassess Bundle** (or trigger auto-reassessment).
2. **Show Live SSE Progress**:
   - Point to the live progress strip updating in real time:
     *Stage: Preprocessing $\to$ Extracting $\to$ Math Check $\to$ Grounding $\to$ Synthesizing*.

### Phase 3: Adjudication & Reasoning Delta
1. **Compliant Status**:
   - Status pill turns to green: **`Compliant for Submission`**.
   - Missing evidence card disappears.
2. **Reasoning Delta Drawer**:
   - Open the bottom drawer to the **Reasoning Delta** tab.
   - Show the structured diff table explaining *why* the status changed:
     - `status`: `MISSING_EVIDENCE` $\to$ `COMPLIANT_FOR_SUBMISSION`.
     - `missing_evidence.ME-MILL_TEST_CERTIFICATE`: `REQUIRED` $\to$ `SATISFIED`.
     - Narrative: *"Uploaded Mill Test Certificate satisfies AHTN regulatory requirements for HS 7304."*
3. **Cryptographic Audit Trail**:
   - Click the **Audit Chain Timeline** tab in the drawer.
   - Show judges the tamper-evident SHA-256 hash chain linking every event from `GENESIS`.
4. **WCAG 2.2 AA Accessibility**:
   - Mention high-contrast token palette (minimum 4.5:1 text, 3:1 borders), full keyboard navigation (`Tab` and arrow keys), and dual ARIA live regions for screen readers.

---

## 6. Testing & Verification

Run the full automated test suite anytime:

### Backend Unit & Integration Tests (Python)
```bash
cd backend
pytest tests/unit tests/integration -v
```
Verifies:
- Deterministic math engine & tolerance boundary conditions
- Status precedence resolution matrix
- SHA-256 cryptographic audit chain & tamper detection
- BigQuery tariff vector search & ambiguity threshold
- Case C Hero Journey multi-iteration reassessment

### Frontend Accessibility & E2E Tests (Playwright)
```bash
cd frontend
# Run Playwright tests
npx playwright test
```
Verifies:
- Zero critical WCAG 2.2 AA accessibility violations (via `axe-core`)
- Keyboard navigation stop verification
- Case C user interface interaction flow
