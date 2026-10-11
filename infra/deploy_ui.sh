#!/usr/bin/env bash
# =============================================================================
# CargoClear UI Deployment Script (Cloud Run)
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
REGION="${REGION:-asia-south1}"

echo "Deploying cargoclear-ui to Google Cloud Run in ${REGION} (project: ${PROJECT_ID})..."

# Fetch the deployed backend URL for the server-side BFF proxy.  Do not invent
# a fallback: an empty or unavailable API service must stop the UI deployment.
API_URL="$(gcloud run services describe cargoclear-api --region "${REGION}" --project "${PROJECT_ID}" --format="value(status.url)")"
if [[ -z "${API_URL}" ]]; then
  echo "cargoclear-api has no deployed URL; deploy the API successfully before the UI." >&2
  exit 1
fi

gcloud run deploy cargoclear-ui \
  --source ./frontend \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --port 8080 \
  --timeout 300 \
  --concurrency 80 \
  --allow-unauthenticated \
  --quiet \
  --set-env-vars API_BASE="${API_URL}"

echo "cargoclear-ui deployment completed successfully."
