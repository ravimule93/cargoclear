#!/usr/bin/env bash
# =============================================================================
# Firestore TTL policies for the counters that carry an `expires_at`:
#   `ratelimits`    the shared rate-limit counters (RATE_LIMIT_BACKEND=firestore)
#   `token_budget`  the daily model-token counter (DAILY_TOKEN_BUDGET), one document per UTC day
#   `extraction_cache`  the model's kept answers, one per document read, under every bundle (EXTRACTION_CACHE_TTL_DAYS, 30 by default)
#
# Each document carries `expires_at`; the policy lets Firestore delete it once that time has passed (typically within a day), so the
# collections never grow. Idempotent; a policy takes effect asynchronously. Without it the counters still WORK (a window's or a day's
# document is never read again), they merely accumulate.
#
# Required: PROJECT_ID. Optional: FIRESTORE_DATABASE ((default)).
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-(default)}"

for COLLECTION in ratelimits token_budget extraction_cache; do
  gcloud firestore fields ttls update expires_at \
    --collection-group="${COLLECTION}" \
    --enable-ttl \
    --database="${FIRESTORE_DATABASE}" \
    --project="${PROJECT_ID}" \
    --async
  echo "TTL policy requested for ${COLLECTION}.expires_at in ${FIRESTORE_DATABASE}."
done
echo "Check it with: gcloud firestore fields ttls list --database='${FIRESTORE_DATABASE}' --project='${PROJECT_ID}'"
