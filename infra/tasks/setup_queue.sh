#!/usr/bin/env bash
# =============================================================================
# Cloud Tasks queue for dispatched assessment runs (RUN_DISPATCH=cloudtasks).
#
# What it sets up, idempotently:
#   * the dedicated tasks identity (cargoclear-tasks-sa): it signs the OIDC token of every task and holds NO project role;
#     deploy_api.sh gives it roles/run.invoker on the (private) API, and the API's worker endpoint accepts only it
#   * the queue (default cargoclear-runs) with the service-wide cap on concurrent runs (max-concurrent-dispatches) and a
#     retry policy that lets a DEAD executor's run be taken over: a request that dies is delivered again after the backoff,
#     by which time the run's lease (RUN_STALE_AFTER_SECONDS, 90 s) has expired
#   * least-privilege bindings: the API's runtime identity may enqueue to THIS queue only, and may act as the tasks identity
#     (needed to attach its OIDC token to a task)
#
# Required: PROJECT_ID, RUNTIME_SERVICE_ACCOUNT (the API's runtime identity, e.g. from infra/bootstrap.sh)
# Optional: REGION (asia-south1), TASKS_QUEUE (cargoclear-runs), TASKS_SERVICE_ACCOUNT, MAX_CONCURRENT_RUNS (4)
#
# MAX_CONCURRENT_RUNS here is the cap for the WHOLE service: every worker request is one dispatch, and the queue never
# runs more at once. (The API's own MAX_CONCURRENT_RUNS only counts the runs of one process, in local dispatch.)
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
REGION="${REGION:-asia-south1}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:?RUNTIME_SERVICE_ACCOUNT must be the API runtime identity}"
TASKS_QUEUE="${TASKS_QUEUE:-cargoclear-runs}"
TASKS_SA_NAME="cargoclear-tasks-sa"
TASKS_SERVICE_ACCOUNT="${TASKS_SERVICE_ACCOUNT:-${TASKS_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com}"
MAX_CONCURRENT_RUNS="${MAX_CONCURRENT_RUNS:-4}"

echo "Setting up the run queue '${TASKS_QUEUE}' in ${REGION} (project: ${PROJECT_ID})..."

gcloud services enable cloudtasks.googleapis.com --project "${PROJECT_ID}"

gcloud iam service-accounts create "${TASKS_SA_NAME}" \
  --project "${PROJECT_ID}" \
  --display-name="CargoClear Cloud Tasks caller: may only invoke the worker endpoint of the private API" || true

if gcloud tasks queues describe "${TASKS_QUEUE}" --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  VERB=update
else
  VERB=create
fi
gcloud tasks queues "${VERB}" "${TASKS_QUEUE}" \
  --location "${REGION}" \
  --project "${PROJECT_ID}" \
  --max-concurrent-dispatches "${MAX_CONCURRENT_RUNS}" \
  --max-attempts 5 \
  --min-backoff 30s \
  --max-backoff 300s \
  --max-doublings 3 \
  --max-retry-duration 1800s

# The API's runtime identity may enqueue to this queue only (not project-wide)...
gcloud tasks queues add-iam-policy-binding "${TASKS_QUEUE}" \
  --location "${REGION}" \
  --project "${PROJECT_ID}" \
  --member "serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role "roles/cloudtasks.enqueuer"

# ...and may attach the tasks identity's OIDC token to a task.
gcloud iam service-accounts add-iam-policy-binding "${TASKS_SERVICE_ACCOUNT}" \
  --project "${PROJECT_ID}" \
  --member "serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role "roles/iam.serviceAccountUser"

echo "Queue ready. Deploy the API with:"
echo "  export RUN_DISPATCH=cloudtasks TASKS_SERVICE_ACCOUNT=${TASKS_SERVICE_ACCOUNT} TASKS_QUEUE=${TASKS_QUEUE}"
echo "  export MAX_INSTANCES=3    # more than one instance is now safe"
echo "  bash infra/deploy_api.sh"
