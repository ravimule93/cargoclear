#!/usr/bin/env bash
# =============================================================================
# CargoClear UI Deployment Script (Cloud Run)
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-cargoclear-hackathon}"
REGION="${REGION:-asia-south1}"

echo "Deploying cargoclear-ui to Google Cloud Run in ${REGION} (project: ${PROJECT_ID})..."

# Fetch deployed backend URL to configure BFF proxy
API_URL=$(gcloud run services describe cargoclear-api --region "${REGION}" --project "${PROJECT_ID}" --format="value(status.url)" 2>/dev/null || echo "https://cargoclear-api-demo.a.run.app")

gcloud run deploy cargoclear-ui \
  --source ./frontend \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-env-vars NEXT_PUBLIC_API_BASE="${API_URL}"

echo "cargoclear-ui deployment completed successfully."
