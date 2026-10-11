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
    cloudbuild.googleapis.com

echo "=== [3/7] Creating Service Account & IAM Bindings ==="
gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="CargoClear Cloud Run Runtime Service Account" || true

# Bind least-privilege roles
# datastore.user is required for the Firestore bundle/run/audit records that
# the live API persists. No runtime Cloud Run-to-Cloud Run call exists, so the
# specification's conditional roles/run.invoker grant is intentionally omitted.
for ROLE in roles/aiplatform.user roles/storage.objectAdmin roles/bigquery.dataViewer roles/datastore.user; do
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="${ROLE}"
done

echo "=== [4/7] Creating GCS Bucket in ${REGION} ==="
gsutil mb -l "${REGION}" "gs://${BUCKET_NAME}" || true

echo "=== [5/7] Initializing Firestore Database in ${REGION} ==="
gcloud firestore databases create --region="${REGION}" || true

echo "=== [6/7] Creating BigQuery Dataset ==="
bq --location="${REGION}" mk -d "${BQ_DATASET}" || true

echo "=== [7/7] Bootstrap Complete ==="
echo "GCP Project ${PROJECT_ID} is ready for deployment."
