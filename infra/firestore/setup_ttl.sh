#!/usr/bin/env bash
# =============================================================================
# Firestore TTL policy for the shared rate-limit counters (RATE_LIMIT_BACKEND=firestore).
#
# Every counter document in the `ratelimits` collection carries `expires_at`; this policy lets Firestore delete it once that
# time has passed (typically within a day), so the collection never grows. Idempotent; the policy takes effect asynchronously.
# Without it the counters still WORK (a window's document is never read again), they merely accumulate.
#
# Required: PROJECT_ID. Optional: FIRESTORE_DATABASE ((default)).
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-(default)}"

gcloud firestore fields ttls update expires_at \
  --collection-group=ratelimits \
  --enable-ttl \
  --database="${FIRESTORE_DATABASE}" \
  --project="${PROJECT_ID}" \
  --async

echo "TTL policy requested for ratelimits.expires_at in ${FIRESTORE_DATABASE}."
echo "Check it with: gcloud firestore fields ttls list --database='${FIRESTORE_DATABASE}' --project='${PROJECT_ID}'"
