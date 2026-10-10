#!/usr/bin/env bash
# =============================================================================
# CargoClear API Deployment Script (Cloud Run)
# Configured for Server-Sent Events (SSE) and MeitY asia-south1.
#
# NOTE: --service-account is intentionally omitted here so Cloud Build
# (running as the Compute default SA) does not need iam.serviceaccounts.actAs.
# Grant cargoclear-sa manually via Cloud Console post-deploy if needed.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-cargoclear-hackathon}"
REGION="${REGION:-asia-south1}"

echo "Deploying cargoclear-api to Google Cloud Run in ${REGION} (project: ${PROJECT_ID})..."

gcloud run deploy cargoclear-api \
  --source ./backend \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --timeout 300 \
  --concurrency 20 \
  --min-instances 1 \
  --max-instances 10 \
  --no-cpu-throttling \
  --allow-unauthenticated \
  --quiet \
  --set-env-vars \
APP_MODE="live",\
PROJECT_ID="${PROJECT_ID}",\
REGION="${REGION}",\
RAW_BUCKET="cargoclear-raw-pdfs",\
FIRESTORE_DATABASE="(default)",\
BQ_DATASET="ahtn",\
GEMINI_LIVE_MODEL="gemini-2.5-flash",\
GEMINI_LIVE_LOCATION="${REGION}"

echo "cargoclear-api deployment completed successfully."
