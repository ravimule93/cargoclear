#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-cargoclear-hackathon}"
REGION="${REGION:-asia-south1}"

gcloud run deploy cargoclear-ui \
  --source ./frontend \
  --region "${REGION}" \
  --allow-unauthenticated
