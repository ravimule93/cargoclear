#!/usr/bin/env bash
# =============================================================================
# Cloud KMS signing key for the audit chain (services/signing.py).
#
# After every completed assessment the API signs the head of the bundle's audit chain with this key. It is an asymmetric
# EC P-256 / SHA-256 signing key: the private half never leaves KMS, and the API's runtime identity may only SIGN with it and
# read its PUBLIC half (roles/cloudkms.signerVerifier on this one key). Whoever can write Firestore cannot forge a signature.
#
# Idempotent. Prints the SIGNING_KEY_VERSION to deploy with:
#     export SIGNING_KEY_VERSION=<printed value>; bash infra/deploy_api.sh
#
# Required: PROJECT_ID, RUNTIME_SERVICE_ACCOUNT. Optional: REGION (asia-south1; keys stay in the data-residency region),
# KMS_KEYRING (cargoclear), KMS_KEY (audit-head), KMS_PROTECTION (software | hsm; default software).
#
# Rotation: create a new version (gcloud kms keys versions create) and deploy with its SIGNING_KEY_VERSION. Old signatures
# name the version that made them and keep verifying while that version is enabled; do not destroy a version whose signatures
# you still need to verify.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
REGION="${REGION:-asia-south1}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:?RUNTIME_SERVICE_ACCOUNT must be the API runtime identity}"
KMS_KEYRING="${KMS_KEYRING:-cargoclear}"
KMS_KEY="${KMS_KEY:-audit-head}"
KMS_PROTECTION="${KMS_PROTECTION:-software}"

gcloud services enable cloudkms.googleapis.com --project "${PROJECT_ID}"

gcloud kms keyrings create "${KMS_KEYRING}" --location "${REGION}" --project "${PROJECT_ID}" || true

gcloud kms keys create "${KMS_KEY}" \
  --keyring "${KMS_KEYRING}" \
  --location "${REGION}" \
  --project "${PROJECT_ID}" \
  --purpose asymmetric-signing \
  --default-algorithm ec-sign-p256-sha256 \
  --protection-level "${KMS_PROTECTION}" || true

# sign + read the public key of THIS key, nothing else
gcloud kms keys add-iam-policy-binding "${KMS_KEY}" \
  --keyring "${KMS_KEYRING}" \
  --location "${REGION}" \
  --project "${PROJECT_ID}" \
  --member "serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role "roles/cloudkms.signerVerifier"

VERSION="$(gcloud kms keys versions list \
  --key "${KMS_KEY}" --keyring "${KMS_KEYRING}" --location "${REGION}" --project "${PROJECT_ID}" \
  --filter "state=ENABLED" --sort-by "~name" --limit 1 --format "value(name)")"

echo
echo "Signing key ready: ${VERSION}"
echo "  export SIGNING_KEY_VERSION=${VERSION}"
