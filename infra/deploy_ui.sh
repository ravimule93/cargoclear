#!/usr/bin/env bash
# =============================================================================
# CargoClear UI Deployment Script (Cloud Run)
#
# The UI is the only public service. Its server-side proxy (frontend/app/api/proxy)
# calls the PRIVATE API with a Google ID token of the identity this service runs as,
# so that identity (UI_SERVICE_ACCOUNT) is granted roles/run.invoker on the API here.
# It holds no other role: it cannot touch Firestore, Storage, BigQuery or Vertex AI.
#
# The deployer needs iam.serviceAccounts.actAs on UI_SERVICE_ACCOUNT and
# run.services.setIamPolicy on cargoclear-api.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
REGION="${REGION:-asia-south1}"
UI_SERVICE_ACCOUNT="${UI_SERVICE_ACCOUNT:?UI_SERVICE_ACCOUNT must be the dedicated Cloud Run identity of the UI (it needs roles/run.invoker on the API, nothing else)}"

PUBLIC_URL="${PUBLIC_URL:-https://cargoclear-app.web.app}"
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-448522365737-41s34pmlanitloca4vd4qesoefa060j9.apps.googleusercontent.com}"
NEXT_PUBLIC_APP_MODE="${NEXT_PUBLIC_APP_MODE:-live}"

echo "Deploying cargoclear-ui to Google Cloud Run in ${REGION} (project: ${PROJECT_ID})..."

# Fetch the deployed backend URL for the server-side BFF proxy.  Do not invent
# a fallback: an empty or unavailable API service must stop the UI deployment.
API_URL="$(gcloud run services describe cargoclear-api --region "${REGION}" --project "${PROJECT_ID}" --format="value(status.url)")"
if [[ -z "${API_URL}" ]]; then
  echo "cargoclear-api has no deployed URL; deploy the API successfully before the UI." >&2
  exit 1
fi

# The API is private: only this identity may invoke it. Idempotent.
gcloud run services add-iam-policy-binding cargoclear-api \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --member "serviceAccount:${UI_SERVICE_ACCOUNT}" \
  --role "roles/run.invoker" \
  --quiet

gcloud run deploy cargoclear-ui \
  --source ./frontend \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --port 8080 \
  --timeout 300 \
  --concurrency 80 \
  --min-instances 0 \
  --service-account "${UI_SERVICE_ACCOUNT}" \
  --allow-unauthenticated \
  --quiet \
  --set-secrets \
GOOGLE_CLIENT_SECRET="google-client-secret:latest" \
  --set-env-vars \
API_BASE="${API_URL}",\
API_AUTH_MODE="google-id-token",\
TRUSTED_PROXY_HOPS="1",\
PUBLIC_URL="${PUBLIC_URL}",\
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID}",\
NEXT_PUBLIC_APP_MODE="${NEXT_PUBLIC_APP_MODE}"

# Automatically prune older container images from Artifact Registry, keeping only the active image
echo "Pruning older cargoclear-ui container images from Artifact Registry..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${SCRIPT_DIR}/prune_old_images.sh" cargoclear-ui || echo "WARNING: Image pruning step encountered an issue; proceeding."

echo "cargoclear-ui deployment completed successfully."
