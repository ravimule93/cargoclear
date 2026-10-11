#!/usr/bin/env bash
# =============================================================================
# CargoClear API Deployment Script (Cloud Run)
# Configured for Server-Sent Events (SSE) and MeitY asia-south1.
#
# A live API must run as the dedicated runtime service account. The deployer
# therefore needs iam.serviceAccounts.actAs on that identity; failing closed is
# safer than silently using Cloud Run's default service account.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
REGION="${REGION:-asia-south1}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:?RUNTIME_SERVICE_ACCOUNT must be the dedicated Cloud Run runtime identity}"

echo "Deploying cargoclear-api to Google Cloud Run in ${REGION} (project: ${PROJECT_ID})..."

gcloud run deploy cargoclear-api \
  --source ./backend \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --timeout 300 \
  --concurrency 80 \
  --min-instances 1 \
  --max-instances 1 \
  --no-cpu-throttling \
  --service-account "${RUNTIME_SERVICE_ACCOUNT}" \
  --allow-unauthenticated \
  --quiet \
  --set-env-vars \
APP_MODE="live",\
ENABLE_API_DOCS="false",\
PROJECT_ID="${PROJECT_ID}",\
REGION="${REGION}",\
RAW_BUCKET="cargoclear-raw-pdfs",\
FIRESTORE_DATABASE="(default)",\
BQ_DATASET="ahtn",\
GEMINI_LIVE_MODEL="gemini-2.5-flash",\
GEMINI_LIVE_LOCATION="${REGION}",\
RUN_TIMEOUT_SECONDS="1200",\
TRUST_FORWARDED_FOR="false"

echo "cargoclear-api deployment completed successfully."
