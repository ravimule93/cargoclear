#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-cargoclear-hackathon}"
REGION="${REGION:-asia-south1}"
SA_EMAIL="cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud run deploy cargoclear-api \
  --source ./backend \
  --region "${REGION}" \
  --service-account "${SA_EMAIL}" \
  --timeout 300 \
  --concurrency 20 \
  --min-instances 1 \
  --max-instances 10 \
  --no-cpu-throttling \
  --set-env-vars PROJECT_ID="${PROJECT_ID}",REGION="${REGION}"
