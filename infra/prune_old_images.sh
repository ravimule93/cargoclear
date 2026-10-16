#!/usr/bin/env bash
# =============================================================================
# CargoClear Artifact Registry Pruning Script
#
# Prunes superseded/older container images in Artifact Registry, retaining
# only the active images currently referenced by Cloud Run service revisions.
#
# Usage:
#   ./infra/prune_old_images.sh [SERVICE_NAME] [PACKAGE_NAME]
#
# Examples:
#   ./infra/prune_old_images.sh cargoclear-ui
#   ./infra/prune_old_images.sh cargoclear-api
#   ./infra/prune_old_images.sh all
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo "cargoclear-hackathon")}"
REGION="${REGION:-asia-south1}"
AR_REPO="${AR_REPO:-cloud-run-source-deploy}"
DRY_RUN="${DRY_RUN:-false}"

TARGET_SERVICE="${1:-all}"
TARGET_PACKAGE="${2:-}"

prune_service() {
  local service_name="$1"
  local package_name="${2:-$1}"
  local package_path="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${package_name}"

  echo "=================================================================="
  echo "Pruning older images for service: ${service_name} (package: ${package_name})"
  echo "Registry path: ${package_path}"
  echo "=================================================================="

  # 1. Fetch active image(s) from Cloud Run
  local active_images=()
  
  # Fetch template image
  local template_img
  template_img="$(gcloud run services describe "${service_name}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --format="value(spec.template.spec.containers[0].image)" 2>/dev/null || true)"
  
  if [[ -n "${template_img}" ]]; then
    if [[ "${template_img}" == *"@"* ]]; then
      active_images+=("${template_img##*@}")
    fi
  fi

  # Fetch images from traffic-bearing revisions
  local traffic_revs
  traffic_revs="$(gcloud run services describe "${service_name}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --format="value(status.traffic[].revisionName)" 2>/dev/null || true)"

  for rev in ${traffic_revs}; do
    if [[ -n "${rev}" ]]; then
      local rev_img
      rev_img="$(gcloud run revisions describe "${rev}" \
        --region "${REGION}" \
        --project "${PROJECT_ID}" \
        --format="value(status.containerStatuses[0].imageDigest,spec.containers[0].image)" 2>/dev/null || true)"
      for item in ${rev_img}; do
        if [[ "${item}" == *"@"* ]]; then
          active_images+=("${item##*@}")
        elif [[ "${item}" == sha256:* ]]; then
          active_images+=("${item}")
        fi
      done
    fi
  done

  # Deduplicate active digests
  local unique_active=()
  for digest in "${active_images[@]}"; do
    local already_present=0
    for u in "${unique_active[@]}"; do
      if [[ "${u}" == "${digest}" ]]; then
        already_present=1
        break
      fi
    done
    if [[ "${already_present}" -eq 0 && -n "${digest}" ]]; then
      unique_active+=("${digest}")
    fi
  done

  if [[ ${#unique_active[@]} -eq 0 ]]; then
    echo "WARNING: Could not identify any active image for service '${service_name}' on Cloud Run."
    echo "Failing safe: skipping image deletion to prevent accidental data loss."
    return 0
  fi

  echo "Identified active image digest(s) currently running on Cloud Run:"
  for u in "${unique_active[@]}"; do
    echo "  -> ${u}"
  done

  # 2. List all image versions in the Artifact Registry package
  local all_versions
  all_versions="$(gcloud artifacts docker images list "${package_path}" \
    --format="value(version)" 2>/dev/null || true)"

  if [[ -z "${all_versions}" ]]; then
    echo "No images found in ${package_path}."
    return 0
  fi

  local pruned_count=0
  local kept_count=0

  while IFS= read -r version_digest; do
    [[ -z "${version_digest}" ]] && continue

    local is_active=0
    for active_digest in "${unique_active[@]}"; do
      if [[ "${version_digest}" == "${active_digest}" ]]; then
        is_active=1
        break
      fi
    done

    if [[ "${is_active}" -eq 1 ]]; then
      echo "  [KEEP] Active image in Cloud Run: ${package_path}@${version_digest}"
      kept_count=$((kept_count + 1))
    else
      if [[ "${DRY_RUN}" == "true" ]]; then
        echo "  [DRY-RUN] Would delete older image: ${package_path}@${version_digest}"
      else
        echo "  [DELETE] Deleting older image: ${package_path}@${version_digest} ..."
        gcloud artifacts docker images delete "${package_path}@${version_digest}" --delete-tags --quiet
      fi
      pruned_count=$((pruned_count + 1))
    fi
  done <<< "${all_versions}"

  echo "Summary for ${service_name}: kept ${kept_count} active image(s), pruned ${pruned_count} older image(s)."
}

if [[ "${TARGET_SERVICE}" == "all" ]]; then
  prune_service "cargoclear-api" "cargoclear-api"
  prune_service "cargoclear-ui" "cargoclear-ui"
elif [[ -n "${TARGET_PACKAGE}" ]]; then
  prune_service "${TARGET_SERVICE}" "${TARGET_PACKAGE}"
else
  prune_service "${TARGET_SERVICE}" "${TARGET_SERVICE}"
fi

echo "Artifact Registry pruning finished successfully."
