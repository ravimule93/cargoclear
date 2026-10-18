#!/usr/bin/env bash
# Configure the approved 90-day retention period for CargoClear evidence artifacts.
set -euo pipefail

RAW_BUCKET="${RAW_BUCKET:?RAW_BUCKET must identify the dedicated CargoClear artifact bucket}"
POLICY_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cargoclear-artifact-lifecycle-90-days.json"

echo "CargoClear artifact lifecycle: delete objects at age 90 days."
echo "Target: gs://${RAW_BUCKET}"
echo "Audit records are excluded: they remain in Firestore under legal-hold retention."
if [[ "${APPLY_RETENTION_POLICY:-}" != "yes" ]]; then
  echo "Preview only. Inspect the policy, then run APPLY_RETENTION_POLICY=yes bash infra/storage/setup_artifact_retention.sh"
  exit 0
fi
echo "Current lifecycle configuration (this update replaces it):"
gcloud storage buckets describe "gs://${RAW_BUCKET}" --format="default(lifecycle_config)"
gcloud storage buckets update "gs://${RAW_BUCKET}" --lifecycle-file="${POLICY_FILE}"
echo "Applied. Verify with: gcloud storage buckets describe gs://${RAW_BUCKET} --format='default(lifecycle_config)'"
