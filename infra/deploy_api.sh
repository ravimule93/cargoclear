#!/usr/bin/env bash
# =============================================================================
# CargoClear API Deployment Script (Cloud Run)
# Configured for Server-Sent Events (SSE) and MeitY asia-south1.
#
# The API is a PRIVATE service (--no-allow-unauthenticated): Cloud Run's IAM check
# rejects every call that does not carry a Google ID token of an identity holding
# roles/run.invoker on it. The only such identity is the UI service's dedicated
# service account (infra/deploy_ui.sh grants it); the browser never calls the API.
# Because only the UI's server-side proxy can reach the API, it is safe for the API
# to read the end user's IP from the header that proxy sets (CLIENT_IP_HEADER).
#
# A live API must run as the dedicated runtime service account. The deployer
# therefore needs iam.serviceAccounts.actAs on that identity; failing closed is
# safer than silently using Cloud Run's default service account.
#
# Run dispatch and scaling (docs/GCP_VERIFICATION.md section 9):
#   RUN_DISPATCH=local (default)   one always-on instance runs assessments as background tasks (min = max = 1)
#   RUN_DISPATCH=cloudtasks        the API enqueues each run on a Cloud Tasks queue and a worker request executes it, so the
#                                  service may scale out (MAX_INSTANCES) and scale-in cannot kill a run. Needs
#                                  infra/tasks/setup_queue.sh first, and TASKS_SERVICE_ACCOUNT. The tasks identity gets
#                                  roles/run.invoker on this (private) service here, after the deployment.
#   MIN_INSTANCES / MAX_INSTANCES  default 1 / 1 (more than one instance is refused unless RUN_DISPATCH=cloudtasks)
#   TASKS_QUEUE                    default cargoclear-runs
#   RATE_LIMIT_BACKEND             memory | firestore; default firestore with cloudtasks (limits shared by all instances)
#   SIGNING_KEY_VERSION            the Cloud KMS key version that signs the audit chain head (infra/kms/setup_signing_key.sh
#                                  prints it); unset = the API does not sign and says so (NOT_CONFIGURED)
#
# Optional overrides (so a model can be swapped without editing this file):
#   GEMINI_LIVE_MODEL     default gemini-2.5-flash. Check Google's model lifecycle page before every
#                         deployment: Vertex AI lists a retirement date for it (see docs/GCP_VERIFICATION.md).
#   GEMINI_LIVE_LOCATION  default ${REGION}
#   BQ_MODEL_EMBEDDING    default embedding_model
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
REGION="${REGION:-asia-south1}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:?RUNTIME_SERVICE_ACCOUNT must be the dedicated Cloud Run runtime identity}"
GEMINI_LIVE_MODEL="${GEMINI_LIVE_MODEL:-gemini-2.5-flash}"
GEMINI_LIVE_LOCATION="${GEMINI_LIVE_LOCATION:-${REGION}}"
BQ_MODEL_EMBEDDING="${BQ_MODEL_EMBEDDING:-embedding_model}"
RUN_DISPATCH="${RUN_DISPATCH:-local}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"
CPU_THROTTLING_FLAG="${CPU_THROTTLING_FLAG:---cpu-throttling}"
TASKS_QUEUE="${TASKS_QUEUE:-cargoclear-runs}"
SIGNING_KEY_VERSION="${SIGNING_KEY_VERSION:-}"

case "${RUN_DISPATCH}" in
  local)
    if [ "${MAX_INSTANCES}" -gt 1 ]; then
      echo "ERROR: MAX_INSTANCES=${MAX_INSTANCES} needs RUN_DISPATCH=cloudtasks: with local dispatch a run is a background task of one instance." >&2
      exit 1
    fi
    REQUEST_TIMEOUT=300
    RATE_LIMIT_BACKEND="${RATE_LIMIT_BACKEND:-memory}"
    TASKS_SERVICE_ACCOUNT="${TASKS_SERVICE_ACCOUNT:-}"
    ;;
  cloudtasks)
    TASKS_SERVICE_ACCOUNT="${TASKS_SERVICE_ACCOUNT:?TASKS_SERVICE_ACCOUNT must be the Cloud Tasks identity (infra/tasks/setup_queue.sh creates it)}"
    # A worker request lives as long as the run it executes: longer than RUN_TIMEOUT_SECONDS (1200)
    REQUEST_TIMEOUT=1500
    RATE_LIMIT_BACKEND="${RATE_LIMIT_BACKEND:-firestore}"
    ;;
  *)
    echo "ERROR: RUN_DISPATCH must be local or cloudtasks, not '${RUN_DISPATCH}'." >&2
    exit 1
    ;;
esac

echo "Deploying cargoclear-api (private) to Google Cloud Run in ${REGION} (project: ${PROJECT_ID})..."

gcloud run deploy cargoclear-api \
  --source ./backend \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --timeout "${REQUEST_TIMEOUT}" \
  --concurrency 80 \
  --min-instances "${MIN_INSTANCES}" \
  --max-instances "${MAX_INSTANCES}" \
  ${CPU_THROTTLING_FLAG} \
  --service-account "${RUNTIME_SERVICE_ACCOUNT}" \
  --no-allow-unauthenticated \
  --quiet \
  --set-env-vars \
APP_MODE="live",\
ENABLE_API_DOCS="false",\
PROJECT_ID="${PROJECT_ID}",\
REGION="${REGION}",\
RAW_BUCKET="cargoclear-raw-pdfs",\
FIRESTORE_DATABASE="(default)",\
BQ_DATASET="ahtn",\
BQ_MODEL_EMBEDDING="${BQ_MODEL_EMBEDDING}",\
GEMINI_LIVE_MODEL="${GEMINI_LIVE_MODEL}",\
GEMINI_LIVE_LOCATION="${GEMINI_LIVE_LOCATION}",\
GEMINI_MAX_OUTPUT_TOKENS="65536",\
RUN_TIMEOUT_SECONDS="1200",\
CLIENT_IP_HEADER="x-cargoclear-client-ip",\
TRUST_FORWARDED_FOR="false",\
RUN_DISPATCH="${RUN_DISPATCH}",\
RATE_LIMIT_BACKEND="${RATE_LIMIT_BACKEND}",\
TASKS_QUEUE="${TASKS_QUEUE}",\
TASKS_LOCATION="${REGION}",\
TASKS_SERVICE_ACCOUNT="${TASKS_SERVICE_ACCOUNT}",\
INTERNAL_CALLER_EMAIL="${TASKS_SERVICE_ACCOUNT}",\
SIGNING_KEY_VERSION="${SIGNING_KEY_VERSION}"

# An earlier version of this script deployed the API publicly. Make sure no anonymous invoker binding survives
# on an existing service (idempotent; harmless when there is none).
gcloud run services remove-iam-policy-binding cargoclear-api \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --member "allUsers" \
  --role "roles/run.invoker" \
  --quiet >/dev/null 2>&1 || true

if [ "${RUN_DISPATCH}" = "cloudtasks" ]; then
  # Cloud Tasks calls this service by its own URL, and signs its OIDC token for that audience: the worker endpoint verifies
  # it against API_URL. The URL is only known once the service exists, so it is set on a second revision.
  API_URL="$(gcloud run services describe cargoclear-api --region "${REGION}" --project "${PROJECT_ID}" --format='value(status.url)')"
  gcloud run services update cargoclear-api \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --update-env-vars "API_URL=${API_URL}" \
    --quiet

  # The tasks identity may invoke this private service (and the worker endpoint accepts only it).
  gcloud run services add-iam-policy-binding cargoclear-api \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --member "serviceAccount:${TASKS_SERVICE_ACCOUNT}" \
    --role "roles/run.invoker" \
    --quiet >/dev/null
  echo "Runs are dispatched through the '${TASKS_QUEUE}' queue (up to ${MAX_INSTANCES} instances); API_URL=${API_URL}"
fi

echo "cargoclear-api deployment completed successfully."
