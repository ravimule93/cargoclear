# CargoClear Infrastructure & Deployment Guide

> **Google Cloud AI Builder Cup 2026** | Production-Grade Serverless Infrastructure

This directory contains the Infrastructure-as-Code (IaC), deployment automation scripts, security definitions, and configuration manifests for deploying CargoClear-JAPAC to **Google Cloud Platform (GCP)**.

---

## Architecture Overview

CargoClear is built entirely on modern, serverless Google Cloud managed services, engineered for high security, data residency compliance, and **$0 idle cost** through aggressive **scale-to-zero** configuration.

```
                                  [ Internet / User Browser ]
                                               │
                                      HTTPS / Port 443
                                               ▼
                              ┌─────────────────────────────────┐
                              │    Cloud Run: cargoclear-ui     │
                              │  • Public (allow-unauthenticated)│
                              │  • Min: 0 (Scale-to-Zero)       │
                              │  • Max: 10 Instances            │
                              │  • Next.js BFF Proxy            │
                              └────────────────┬────────────────┘
                                               │
                                Google ID Token (IAM Invoker)
                                               ▼
                              ┌─────────────────────────────────┐
                              │    Cloud Run: cargoclear-api    │
                              │  • Private (no-allow-unauth)    │
                              │  • Min: 0 (Scale-to-Zero)       │
                              │  • Max: 1 Instance              │
                              │  • CPU Throttling: Active       │
                              └────┬───────────┬───────────┬────┘
                                   │           │           │
                 ┌─────────────────┼───────────┼───────────┼─────────────────┐
                 ▼                 ▼           ▼           ▼                 ▼
          ┌─────────────┐   ┌─────────────┐┌───────┐┌─────────────┐   ┌─────────────┐
          │  Vertex AI  │   │  BigQuery   ││  GCS  ││  Firestore  │   │  Cloud KMS  │
          │ Gemini 2.5  │   │   Vector    ││  Raw  ││   Leases,   │   │ Asymmetric  │
          │    Flash    │   │   Search    ││ PDFs  ││ Audit Trail │   │ P-256 ECDSA │
          └─────────────┘   └─────────────┘└───────┘└─────────────┘   └─────────────┘
```

---

## Key Infrastructure Characteristics

| Attribute | Specification | Justification |
| :--- | :--- | :--- |
| **Region** | `asia-south1` (Mumbai) | Guarantees strict Indian & JAPAC cross-border data residency. |
| **Scale-to-Zero** | `min-instances = 0` | When no requests are active, container instances scale to zero, resulting in **$0 idle compute cost**. |
| **Private Backend** | `--no-allow-unauthenticated` | The backend API is not exposed to the public internet; it can only be invoked by the UI's service account. |
| **Zero-Trust BFF** | Server-side Google ID Token | The Next.js BFF proxy fetches Google ID tokens from the GCP Metadata server (`metadata.google.internal`) to authenticate against the private API. |
| **Concurrency & Fencing** | Firestore atomic leases | Distributed concurrency control ensures two concurrent requests cannot corrupt state on shared document bundles. |
| **Artifact Pruning** | `prune_old_images.sh` | Automatically prunes older container images in Artifact Registry, retaining only active images to eliminate storage clutter. |

---

## Directory Contents

| Path | Purpose |
| :--- | :--- |
| [`deploy_api.sh`](deploy_api.sh) | Deploys the FastAPI backend container to Cloud Run with scale-to-zero defaults, secret bindings, and environment variables. |
| [`deploy_ui.sh`](deploy_ui.sh) | Deploys the Next.js frontend UI container to Cloud Run, grants invoker permissions on the API, and verifies live health. |
| [`deploy.ps1`](deploy.ps1) | 1-Click interactive PowerShell deployment script for Windows environments with automated preflight checks. |
| [`prune_old_images.sh`](prune_old_images.sh) | Utility script that prunes superseded container digests in Google Artifact Registry to reduce storage overhead. |
| [`bootstrap.sh`](bootstrap.sh) | Initial GCP environment provisioning script (API enablement, service account creation, IAM bindings). |
| [`cloudbuild.yaml`](../cloudbuild.yaml) | Cloud Build CI/CD pipeline executing backend testing, frontend compilation, and zero-downtime deployment. |
| [`bigquery/setup_tariff.sh`](bigquery/setup_tariff.sh) | Provisions BigQuery dataset `ahtn`, loads tariff rules, and sets up vector search embeddings. |
| [`kms/setup_signing_key.sh`](kms/setup_signing_key.sh) | Provisions Cloud KMS KeyRing `cargoclear` and asymmetric signing key `audit-head` (EC-P256-SHA256). |
| [`firestore/setup_ttl.sh`](firestore/setup_ttl.sh) | Configures Firestore Time-to-Live (TTL) policies on cache and rate-limiting collections. |
| [`budget/setup_budget_alert.sh`](budget/setup_budget_alert.sh) | Sets up Google Cloud billing budget alerts at 50% and 100% threshold rules. |
| [`iam/roles.yaml`](iam/roles.yaml) | Declarative least-privilege IAM matrix mapping service accounts to narrow roles. |

---

## Service Accounts & Least-Privilege IAM

CargoClear uses dedicated, isolated service identities for each tier:

### 1. Runtime Service Account (`RUNTIME_SERVICE_ACCOUNT`)
- **Assigned Service**: `cargoclear-api`
- **Required Roles**:
  - `roles/datastore.user`: Read/write bundle states, leases, and audit logs in Firestore.
  - `roles/bigquery.jobUser` & `roles/bigquery.dataViewer`: Execute vector search queries against tariff schedules.
  - `roles/storage.objectUser`: Read and write raw PDF documents in Cloud Storage (`cargoclear-raw-pdfs`).
  - `roles/cloudkms.signerVerifier`: Digitally sign audit chain heads using Cloud KMS asymmetric key.
  - `roles/aiplatform.user`: Invoke Gemini 2.5 Flash on Vertex AI.
  - *No project-wide administrative roles.*

### 2. UI Service Account (`UI_SERVICE_ACCOUNT`)
- **Assigned Service**: `cargoclear-ui`
- **Required Roles**:
  - `roles/run.invoker` on `cargoclear-api` service resource only.
  - *Holds zero project-wide roles and cannot access BigQuery, Firestore, GCS, or KMS.*

### 3. Cloud Build Service Account (`PROJECT_NUMBER@cloudbuild.gserviceaccount.com`)
- **Assigned Service**: Cloud Build CI/CD Runner
- **Required Roles**:
  - `roles/cloudbuild.builds.builder`
  - `roles/run.admin` (to deploy Cloud Run revisions)
  - `roles/iam.serviceAccountUser` on `RUNTIME_SERVICE_ACCOUNT` and `UI_SERVICE_ACCOUNT` (to act-as runtime identities during deployment).

---

## Deployment Options

### Option 1: 100% Automated Remote Deployment via Cloud Build (Recommended)
Submits source code directly to Google Cloud Build, which runs all tests, builds containers, and deploys both services with scale-to-zero configuration:

```bash
gcloud builds submit --config=cloudbuild.yaml --project="cargoclear-hackathon"
```

### Option 2: 1-Click Automated PowerShell Deployment (Windows)
Runs local preflights and executes deployments sequentially with automated status checks:

```powershell
.\infra\deploy.ps1 -ProjectId cargoclear-hackathon -Region asia-south1
```

### Option 3: Modular Bash Deployment
To deploy individual services independently:

```bash
# 1. Deploy Private API
export PROJECT_ID="cargoclear-hackathon"
export REGION="asia-south1"
export RUNTIME_SERVICE_ACCOUNT="448522365737-compute@developer.gserviceaccount.com"
export DAILY_TOKEN_BUDGET="5000000"
export RELEASE_SHA="$(git rev-parse HEAD)"
export RELEASE_TIMESTAMP="$(git show -s --format=%cI HEAD)"
bash infra/deploy_api.sh

# 2. Deploy Frontend UI
export UI_SERVICE_ACCOUNT="448522365737-compute@developer.gserviceaccount.com"
bash infra/deploy_ui.sh
```

---

## Scale-to-Zero & Cold-Start Optimization

- **API Configuration**: `--min-instances 0`, `--max-instances 1`, `--cpu-throttling`, `--startup-cpu-boost` enabled.
- **UI Configuration**: `--min-instances 0`, `--max-instances 10`, `--startup-cpu-boost` enabled.
- **Cold Start Latency**: ~2.5 seconds with startup CPU boost; subsequent invocations respond in under 80ms.
- **Cost**: **$0.00 / month** idle cost when no customs officers are actively reviewing bundles.

---

## Post-Deployment Verification

Verify end-to-end communication and live mode status using the automated verification suite:

```bash
python scripts/verify_live_domain.py \
  --ui-url "https://cargoclear-ui-5ho4zmc74q-el.a.run.app" \
  --api-url "https://cargoclear-api-5ho4zmc74q-el.a.run.app" \
  --identity-token "$(gcloud auth print-identity-token)"
```

Expected output:
```
LIVE MODE VERIFIED: UI metadata and private API version report live with no public user session.
```
