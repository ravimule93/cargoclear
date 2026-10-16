# CargoClear-JAPAC — Google Cloud Platform (GCP) Deployment Guide

This guide provides end-to-end instructions for deploying the **CargoClear** platform to Google Cloud Platform (GCP). It covers both automated CI/CD deployment (Cloud Build) and manual step-by-step CLI deployment (Bash & Windows PowerShell).

---

## 1. Architectural Overview

CargoClear utilizes a **Zero-Trust Cloud Run dual-service architecture** situated in the MeitY-compliant region `asia-south1` (Mumbai):

```mermaid
flowchart TD
    User["End User / Customs Broker (Browser)"]
    Firebase["Firebase Hosting<br/>cargoclear-app.web.app"]
    UI["Cloud Run: cargoclear-ui (Public)<br/>Next.js 15 BFF Proxy<br/>Identity: cargoclear-ui-sa"]
    API["Cloud Run: cargoclear-api (Private)<br/>FastAPI / Python 3.12<br/>Identity: cargoclear-sa"]
    GCS[("Cloud Storage<br/>gs://cargoclear-raw-pdfs")]
    FS[("Firestore Native Mode<br/>Bundles, Audits, SSO")]
    BQ[("BigQuery<br/>ahtn.master_tariff + Vector Search")]
    Vertex["Vertex AI<br/>Gemini 2.5 Flash Multimodal"]
    Tasks["Cloud Tasks<br/>cargoclear-runs queue"]
    KMS["Cloud KMS<br/>Audit Head Signing Key"]
    SM[("Secret Manager<br/>OAuth Client Secret & JWT Keys")]

    User -->|HTTPS| Firebase
    Firebase -->|Rewrite| UI
    User -.->|Direct HTTPS| UI
    SM -.->|In-Memory Mount: GOOGLE_CLIENT_SECRET| UI
    SM -.->|In-Memory Mount: AUTH_JWT_SECRET| API
    UI -->|Google ID Token (roles/run.invoker)| API
    API -->|Raw PDFs & Metadata| GCS
    API -->|Audit Ledger & State| FS
    API -->|Grounding & Embeddings| BQ
    API -->|Document Extraction & Reasoning| Vertex
    API -->|Async Job Leases| Tasks
    API -->|Cryptographic Verification| KMS
```

### Key Security & Isolation Principles
1. **Private API**: `cargoclear-api` is deployed with `--no-allow-unauthenticated`. Cloud Run's IAM layer rejects all requests that do not carry an authorized Google ID token.
2. **Dedicated UI Identity**: `cargoclear-ui` runs under `cargoclear-ui-sa` and holds only `roles/run.invoker` on `cargoclear-api`. It has **no** access to Firestore, Cloud Storage, BigQuery, or Vertex AI.
3. **Dedicated Backend Identity**: `cargoclear-api` runs under `cargoclear-sa` with least-privilege IAM roles (`roles/aiplatform.user`, `roles/storage.objectAdmin`, `roles/bigquery.dataViewer`, `roles/bigquery.jobUser`, `roles/datastore.user`).
4. **Data Residency**: All compute, storage, databases, and AI model inference are anchored to `asia-south1`.
5. **Zero Plaintext Secrets (Key Vault Pattern)**: No credentials or client secrets are committed to git or exposed in plaintext environment variables. Application secrets (`GOOGLE_CLIENT_SECRET`, `AUTH_JWT_SECRET`) are stored in **Google Cloud Secret Manager** and injected into container memory at startup via Cloud Run's native `--set-secrets` integration. Immutable audit chain heads are signed via **Cloud KMS**.

---

## 2. Prerequisites & Tooling

Ensure your workstation has the following installed:
- [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk/docs/install) (version ≥ 490.0.0)
- [Python](https://www.python.org/) 3.12+
- [Node.js](https://nodejs.org/) 20.x or 22.x LTS
- [Firebase CLI](https://firebase.google.com/docs/cli) (`npm install -g firebase-tools`)
- Docker (optional, if building containers locally instead of Cloud Build)

---

## 3. Step 1: GCP Authentication & Project Configuration

Set your project variables and authenticate:

### Bash / Linux / macOS / Cloud Shell:
```bash
export PROJECT_ID="cargoclear-hackathon"  # Replace with your GCP Project ID
export REGION="asia-south1"

gcloud auth login
gcloud auth application-default login
gcloud config set project "${PROJECT_ID}"
gcloud config set compute/region "${REGION}"
```

### Windows PowerShell:
```powershell
$env:PROJECT_ID = "cargoclear-hackathon"  # Replace with your GCP Project ID
$env:REGION = "asia-south1"

gcloud auth login
gcloud auth application-default login
gcloud config set project $env:PROJECT_ID
gcloud config set compute/region $env:REGION
```

---

## 4. Step 2: Day-0 Environment Bootstrap

Enable required APIs, provision service accounts, and initialize foundational storage.

### Option A: Using the Automated Bootstrap Script (Bash / Cloud Shell)
```bash
chmod +x infra/bootstrap.sh
./infra/bootstrap.sh
```

### Option B: Manual Execution via PowerShell / CLI

1. **Enable Google Cloud APIs:**
   ```bash
   gcloud services enable \
       aiplatform.googleapis.com \
       storage.googleapis.com \
       firestore.googleapis.com \
       bigquery.googleapis.com \
       run.googleapis.com \
       eventarc.googleapis.com \
       cloudbuild.googleapis.com \
       cloudtasks.googleapis.com \
       cloudkms.googleapis.com
   ```

2. **Create Dedicated Service Accounts:**
   ```bash
   # API Runtime Service Account
   gcloud iam service-accounts create cargoclear-sa \
       --display-name="CargoClear API Runtime SA"

   # UI Proxy Service Account
   gcloud iam service-accounts create cargoclear-ui-sa \
       --display-name="CargoClear UI Service SA"

   # Cloud Tasks Service Account
   gcloud iam service-accounts create cargoclear-tasks-sa \
       --display-name="CargoClear Tasks Worker SA"
   ```

3. **Grant Least-Privilege IAM Roles to `cargoclear-sa`:**
   ```bash
   SA_EMAIL="cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com"
   for ROLE in roles/aiplatform.user roles/storage.objectAdmin roles/bigquery.dataViewer roles/bigquery.jobUser roles/datastore.user; do
       gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
           --member="serviceAccount:${SA_EMAIL}" \
           --role="${ROLE}"
   done
   ```

4. **Initialize Cloud Storage & Databases:**
   ```bash
   # GCS Bucket for PDF Documents
   gsutil mb -l "${REGION}" "gs://cargoclear-raw-pdfs" || true

   # Firestore Database (Native Mode)
   gcloud firestore databases create --region="${REGION}" || true

   # BigQuery Dataset
   bq --location="${REGION}" mk -d "ahtn" || true
   ```

---

## 5. Step 3: BigQuery Tariff Grounding & Embeddings

CargoClear grounds document analysis against official HS code tariff schedules using vector similarity search in BigQuery.

1. **Run the Tariff Setup Script:**
   ```bash
   export EMBEDDING_ENDPOINT="text-embedding-005"  # or gemini-embedding-001 depending on current quota
   export RUNTIME_SERVICE_ACCOUNT="cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com"
   bash infra/bigquery/setup_tariff.sh
   ```
2. **What this provisions:**
   - Creates a BigQuery `CLOUD_RESOURCE` connection (`cargoclear-vertex`).
   - Grants the connection's service account `roles/aiplatform.user`.
   - Creates the `ahtn.master_tariff` table and seeds it with HS 7304/7306/7210 rules.
   - Generates vector embeddings for all tariff definitions.

---

## 6. Step 4: Preflight Validation Check

Before building container images, verify that all IAM permissions and GCP APIs are responding correctly:

```bash
# Impersonate runtime service account
gcloud auth application-default login --impersonate-service-account="cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Run preflight suite from backend environment
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
APP_MODE=live python ../scripts/preflight_gcp.py
cd ..
```
*Expected Output:* `RESULT: PASS` across Firestore, Storage, BigQuery, and Vertex AI.

---

## 7. Step 5: Deploying Backend (`cargoclear-api`)

Deploy the FastAPI backend to Cloud Run as a **private** service.

### Bash:
```bash
export RUNTIME_SERVICE_ACCOUNT="cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com"
chmod +x infra/deploy_api.sh
./infra/deploy_api.sh
```

### Windows PowerShell / Direct gcloud command:
```powershell
gcloud run deploy cargoclear-api `
  --source ./backend `
  --project $env:PROJECT_ID `
  --region $env:REGION `
  --timeout 1200 `
  --concurrency 80 `
  --min-instances 0 `
  --max-instances 1 `
  --cpu-throttling `
  --service-account "cargoclear-sa@$($env:PROJECT_ID).iam.gserviceaccount.com" `
  --no-allow-unauthenticated `
  --set-secrets="AUTH_JWT_SECRET=auth-jwt-secret:latest" `
  --set-env-vars `
APP_MODE="live",`
ENABLE_API_DOCS="false",`
PROJECT_ID="$env:PROJECT_ID",`
REGION="$env:REGION",`
RAW_BUCKET="cargoclear-raw-pdfs",`
FIRESTORE_DATABASE="(default)",`
BQ_DATASET="ahtn",`
BQ_MODEL_EMBEDDING="embedding_model",`
GEMINI_LIVE_MODEL="gemini-2.5-flash",`
GEMINI_THINKING_BUDGET="0",`
GEMINI_LIVE_LOCATION="$env:REGION",`
GEMINI_MAX_OUTPUT_TOKENS="65536",`
RUN_TIMEOUT_SECONDS="1200",`
CLIENT_IP_HEADER="x-cargoclear-client-ip",`
TRUST_FORWARDED_FOR="false",`
AUTH_ENABLED="true"
```

---

## 8. Step 6: Deploying Frontend (`cargoclear-ui`)

Deploy the Next.js 15 UI to Cloud Run as a **public** service.

1. **Obtain the private API URL:**
   ```bash
   API_URL=$(gcloud run services describe cargoclear-api --region "${REGION}" --project "${PROJECT_ID}" --format="value(status.url)")
   echo "Private API URL: ${API_URL}"
   ```

2. **Grant the UI Service Account invoker permission on the API:**
   ```bash
   gcloud run services add-iam-policy-binding cargoclear-api \
     --region "${REGION}" \
     --project "${PROJECT_ID}" \
     --member "serviceAccount:cargoclear-ui-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
     --role "roles/run.invoker"
   ```

3. **Deploy the UI:**
   ```bash
   export UI_SERVICE_ACCOUNT="cargoclear-ui-sa@${PROJECT_ID}.iam.gserviceaccount.com"
   chmod +x infra/deploy_ui.sh
   ./infra/deploy_ui.sh
   ```

   *Or via Windows PowerShell:*
   ```powershell
   $API_URL = gcloud run services describe cargoclear-api --region $env:REGION --project $env:PROJECT_ID --format="value(status.url)"

   gcloud run deploy cargoclear-ui `
     --source ./frontend `
     --project $env:PROJECT_ID `
     --region $env:REGION `
     --port 8080 `
     --timeout 300 `
     --concurrency 80 `
     --min-instances 0 `
     --service-account "cargoclear-ui-sa@$($env:PROJECT_ID).iam.gserviceaccount.com" `
     --allow-unauthenticated `
     --set-secrets="GOOGLE_CLIENT_SECRET=google-client-secret:latest" `
     --set-env-vars `
   API_BASE="$API_URL",`
   API_AUTH_MODE="google-id-token",`
   TRUSTED_PROXY_HOPS="1"
   ```

---

## 9. Step 7: Automated Deployment via Cloud Build (CI/CD)

The repository includes a ready-to-use [`cloudbuild.yaml`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/cloudbuild.yaml) pipeline that:
1. Runs Python backend unit & integration tests (`pytest`).
2. Typechecks and builds the Next.js frontend (`npm run build`).
3. Deploys `cargoclear-api` to Cloud Run.
4. Deploys `cargoclear-ui` to Cloud Run.

To trigger Cloud Build:
```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_REGION="asia-south1",_RUNTIME_SERVICE_ACCOUNT="cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com",_UI_SERVICE_ACCOUNT="cargoclear-ui-sa@${PROJECT_ID}.iam.gserviceaccount.com"
```

---

## 10. Step 8: Firebase Hosting Setup (Custom Domain & CDN)

Firebase Hosting routes edge traffic to the Cloud Run `cargoclear-ui` service:

1. **Login to Firebase:**
   ```bash
   firebase login
   ```
2. **Associate with GCP Project:**
   ```bash
   firebase use "${PROJECT_ID}"
   ```
3. **Deploy Hosting Config:**
   ```bash
   firebase deploy --only hosting
   ```
   *Live target URLs defined in [`firebase.json`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/firebase.json):*
   - `https://cargoclear-app.web.app`
   - `https://cargoclear-japac.web.app`
   - `https://cargoclear-hackathon.web.app`

---

## 11. Step 9: Post-Deployment Smoke Verification

Run these validation commands to verify system health:

### 1. Confirm API is Private:
```bash
API_URL=$(gcloud run services describe cargoclear-api --region "${REGION}" --project "${PROJECT_ID}" --format="value(status.url)")
curl -i "${API_URL}/api/v1/health"
```
*Expected Result:* `HTTP/1.1 403 Forbidden` (Rejects unauthenticated public traffic).

### 2. Confirm UI Server-Side Proxy is Live:
```bash
UI_URL=$(gcloud run services describe cargoclear-ui --region "${REGION}" --project "${PROJECT_ID}" --format="value(status.url)")
curl -i "${UI_URL}/api/proxy/meta"
```
*Expected Result:* `HTTP/1.1 200 OK` with JSON payload `{ "app_mode": "live", "region": "asia-south1", ... }`.

### 3. Run Live E2E Case D Assessment:
Navigate to the deployed UI in your browser or run:
```bash
python scripts/test_case_d_live.py
```
*Expected Result:* Live document upload, OCR & Gemini multimodal extraction, and material contradiction verdict (`HS 7304` declared vs `HS 7306` chemical composition).

---

## 12. Gemini Model & Thinking Budget Configuration

CargoClear leverages Google Vertex AI's multimodal Gemini models for document OCR, layout understanding, and structured JSON parsing.

### Controlling the Gemini Thinking Budget

Gemini 2.5 models support internal chain-of-thought reasoning ("thinking") prior to emitting the final response. You can configure this behavior dynamically via `GEMINI_THINKING_BUDGET`:

| `GEMINI_THINKING_BUDGET` | Mode | Behavior | Best Used For |
| :---: | :--- | :--- | :--- |
| **`0`** | **Disabled** *(Default in Dev)* | Skips internal reasoning tokens. Directly streams structured JSON. Extraction takes **2–5 seconds** per document at minimum cost. | Routine dev, CI testing, synthetic PDFs, and budget conservation. |
| **`1024`** or **`2048`** | **Controlled Thinking** | Allocates up to 1,024–2,048 reasoning tokens. Allows the model to reason through ambiguities without runaway costs. | Degraded scans, blurred photocopies, complex multi-column chemical tables. |
| **`-1`** | **Dynamic / Unconstrained** | Omits the thinking budget parameter completely. Gemini dynamically decides how many tokens to spend. | Deep exploratory analysis and edge cases. |

### How to Toggle Thinking

**1. On Live Cloud Run (`cargoclear-api`):**
```powershell
# Enable controlled thinking (1024 tokens)
gcloud run services update cargoclear-api `
  --region asia-south1 `
  --update-env-vars GEMINI_THINKING_BUDGET=1024

# Disable thinking (for fast, zero-extra-cost extractions)
gcloud run services update cargoclear-api `
  --region asia-south1 `
  --update-env-vars GEMINI_THINKING_BUDGET=0
```

**2. In Local Development:**
Set in `backend/.env` or PowerShell:
```powershell
$env:GEMINI_THINKING_BUDGET = "1024"  # or "0"
python -m uvicorn app.main:app --reload --port 8000
```

**3. In Standalone Test Scripts:**
```powershell
$env:GEMINI_THINKING_BUDGET = "1024"
python scripts/test_case_d_live.py
```

---

## 13. Bundle Cleanup & Test Data Management

During development and testing, numerous assessment bundles accumulate. The repository provides a dedicated administrative tool [`scripts/clean_bundles.py`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/gcp-cup-poc/scripts/clean_bundles.py) to manage and prune test bundles across both **Firestore** and **Cloud Storage**:

### 1. List all existing bundles:
```bash
python scripts/clean_bundles.py --list
```
Displays all bundles with their ID, reference code, status, tenant, and creation date.

### 2. Delete a single bundle (and its subcollections + GCS files):
```bash
python scripts/clean_bundles.py --bundle bnd-c27d3d168ae0
```
*(Add `--dry-run` to preview deletions beforehand).*

### 3. Keep the latest $N$ bundles and prune all older test runs:
```bash
# Preview keeping the 3 newest bundles:
python scripts/clean_bundles.py --keep 3 --dry-run

# Execute the pruning:
python scripts/clean_bundles.py --keep 3
```

### 4. Wipe ALL test bundles before a live competition demo:
```bash
# Execute with interactive confirmation:
python scripts/clean_bundles.py --all

# Or skip confirmation:
python scripts/clean_bundles.py --all -y
```
> **Safety Guarantee**: The cleanup script deletes only bundle documents, subcollections (`documents`, `iterations`, `audit`), and PDF storage objects. It **never** touches user authentication credentials or BigQuery tariff tables.

---

## 14. Troubleshooting & Cost Optimization

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **`403 Forbidden` on UI Proxy calls** | `cargoclear-ui-sa` lacks `roles/run.invoker` on `cargoclear-api` | Run: `gcloud run services add-iam-policy-binding cargoclear-api --region=asia-south1 --member="serviceAccount:cargoclear-ui-sa@${PROJECT_ID}.iam.gserviceaccount.com" --role="roles/run.invoker"` |
| **`401 Unauthorized` on API routes** | Client request missing or invalid SSO bearer token | Sign in on the UI landing page using the Corporate SSO or licensed CHA preset (`demo-cha@customs.com`). |
| **Unexpected Cloud Run Costs** | Service configured with always-on instances (`min-instances 1`) | Update Cloud Run to scale-to-zero: `gcloud run services update cargoclear-api --region asia-south1 --min-instances 0 --cpu-throttling` |
| **High Vertex AI Token Costs** | Unconstrained thinking tokens on every document | Set `GEMINI_THINKING_BUDGET=0` for routine development and test extractions. |
| **BigQuery Vector Search Fails** | Missing `roles/bigquery.jobUser` on runtime SA | Ensure `cargoclear-sa` has `roles/bigquery.jobUser` (needed to run query jobs, not just read). |
| **Artifact Registry Storage Growth** | Old Docker container images accumulating across revisions | Set 7-day cleanup policy: `gcloud artifacts repositories set-cleanup-policies cloud-run-source-deploy --location=asia-south1 --policy=...` |

