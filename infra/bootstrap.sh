#!/usr/bin/env bash
# =============================================================================
# CargoClear-JAPAC — Day-0 Environment Bootstrap Script
# Executes all Day-0 setup tasks defined in Section 7 of the v4.0 specification.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
REGION="${REGION:-asia-south1}"
SA_NAME="cargoclear-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
# The UI's own identity. It holds NO project role: deploy_ui.sh grants it roles/run.invoker on the (private) API only.
UI_SA_NAME="cargoclear-ui-sa"
UI_SA_EMAIL="${UI_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
BUCKET_NAME="cargoclear-raw-pdfs"
BQ_DATASET="ahtn"

echo "=== [1/7] Setting project & region ==="
gcloud config set project "${PROJECT_ID}"
gcloud config set compute/region "${REGION}"

echo "=== [2/7] Enabling GCP APIs ==="
gcloud services enable \
    aiplatform.googleapis.com \
    storage.googleapis.com \
    firestore.googleapis.com \
    bigquery.googleapis.com \
    run.googleapis.com \
    eventarc.googleapis.com \
    cloudbuild.googleapis.com \
    cloudtasks.googleapis.com \
    cloudkms.googleapis.com \
    secretmanager.googleapis.com

echo "=== [3/7] Creating Service Account & IAM Bindings ==="
gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="CargoClear Cloud Run Runtime Service Account" || true

# Signs the OIDC token of every dispatched run (infra/tasks/setup_queue.sh binds it: roles/run.invoker on the API only)
gcloud iam service-accounts create "cargoclear-tasks-sa" \
    --display-name="CargoClear Cloud Tasks caller: may only invoke the worker endpoint of the private API" || true

gcloud iam service-accounts create "${UI_SA_NAME}" \
    --display-name="CargoClear UI (Cloud Run) service account: may only invoke the private API" || true

# Bind least-privilege roles
# datastore.user is required for the Firestore bundle/run/audit records that
# the live API persists. bigquery.jobUser is required to START the tariff VECTOR_SEARCH query job
# (dataViewer alone reads tables but cannot run queries).
for ROLE in roles/aiplatform.user roles/storage.objectAdmin roles/bigquery.dataViewer roles/bigquery.jobUser roles/datastore.user roles/secretmanager.secretAccessor; do
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="${ROLE}"
done

# Grant UI SA read access to Secret Manager (for OAuth client secrets)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${UI_SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" || true

# Enable Cloud Build to deploy Cloud Run services and actAs dedicated service accounts
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' 2>/dev/null || true)"
if [ -n "${PROJECT_NUMBER}" ]; then
    CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
    echo "Configuring Cloud Build Service Account (${CB_SA})..."
    for ROLE in roles/run.admin roles/iam.serviceAccountUser; do
        gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
            --member="serviceAccount:${CB_SA}" \
            --role="${ROLE}" >/dev/null 2>&1 || true
    done
fi

echo "=== [4/7] Creating GCS Bucket in ${REGION} ==="
gsutil mb -l "${REGION}" "gs://${BUCKET_NAME}" || true

echo "=== [5/7] Initializing Firestore Database in ${REGION} ==="
gcloud firestore databases create --region="${REGION}" || true

echo "=== [6/7] Creating BigQuery Dataset ==="
bq --location="${REGION}" mk -d "${BQ_DATASET}" || true

echo "=== [7/7] Bootstrap Complete ==="
echo "GCP Project ${PROJECT_ID} is ready for deployment."
echo
echo "Deploy with these identities (the deployer needs iam.serviceAccounts.actAs on both):"
echo "  export PROJECT_ID=${PROJECT_ID}"
echo "  export RUNTIME_SERVICE_ACCOUNT=${SA_EMAIL}     # API runtime: Vertex AI, Storage, BigQuery, Firestore"
echo "  export UI_SERVICE_ACCOUNT=${UI_SA_EMAIL}      # UI runtime: may only invoke the API"
echo "Next: infra/bigquery/setup_tariff.sh (tariff table + embedding model), then docs/GCP_VERIFICATION.md."
echo "To scale beyond one instance (docs/GCP_VERIFICATION.md section 9): infra/tasks/setup_queue.sh and infra/firestore/setup_ttl.sh."
