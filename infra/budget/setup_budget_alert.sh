#!/usr/bin/env bash
# =============================================================================
# A budget alert on the billing account that pays for this project.
#
# WHAT IT IS: an alert. It emails (and, if you give it a topic or channels, notifies) when spend reaches 50 %, 90 % and 100 % of the
# amount below, and once more when the forecast says it will reach 100 %. It does NOT stop anything: a budget cannot cap Google Cloud
# spending. The things that bound spending are the daily model-token budget in the application (DAILY_TOKEN_BUDGET, services/token_budget.py)
# and the per-minute client limits; this is the independent line that tells a person when those were not enough.
#
# THIS SCRIPT HAS NOT BEEN RUN. It was written against Google's reference for `gcloud billing budgets create` (flags checked 2026-10-16:
# https://docs.cloud.google.com/sdk/gcloud/reference/billing/budgets/create: `--filter-projects` takes `projects/{project_id}`, as passed
# below; `--calendar-period` takes `month`; the threshold basis is spelled `forecasted-spend`) and passes `bash -n`. Run it once, yourself, as someone who may
# manage budgets on the billing account (for example Billing Account Costs Manager or Administrator; Google's budgets documentation lists the
# roles), and read what it prints. `--dry-run` shows the command without running it.
#
# Required:
#   PROJECT_ID           the project whose spend the budget watches
#   BILLING_ACCOUNT_ID   the billing account that pays for it (gcloud billing projects describe "$PROJECT_ID")
#   BUDGET_AMOUNT        the amount per month, with the billing account's currency, e.g. 100USD (the currency must match the account's)
# Optional:
#   BUDGET_DISPLAY_NAME  default "cargoclear <project>" (at most 60 characters)
#   BUDGET_PUBSUB_TOPIC  projects/<project>/topics/<topic>: budget messages are published there (to drive automation)
#   BUDGET_CHANNELS      comma-separated projects/<project>/notificationChannels/<id> (up to 5), for Cloud Monitoring notifications
#   Without either, the default recipients are used: the billing account's administrators and users get the threshold emails.
#
# Idempotence: `create` always makes a NEW budget. The script lists the account's budgets first and stops if one with the same display
# name exists, so running it twice does not make two.
# =============================================================================

set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
fi

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:?BILLING_ACCOUNT_ID must be the billing account that pays for the project}"
BUDGET_AMOUNT="${BUDGET_AMOUNT:?BUDGET_AMOUNT is the monthly amount with its currency, for example 100USD}"
BUDGET_DISPLAY_NAME="${BUDGET_DISPLAY_NAME:-cargoclear ${PROJECT_ID}}"
BUDGET_PUBSUB_TOPIC="${BUDGET_PUBSUB_TOPIC:-}"
BUDGET_CHANNELS="${BUDGET_CHANNELS:-}"

if [ "${#BUDGET_DISPLAY_NAME}" -gt 60 ]; then
  echo "ERROR: BUDGET_DISPLAY_NAME is ${#BUDGET_DISPLAY_NAME} characters; Google allows at most 60." >&2
  exit 1
fi

# `gcloud billing budgets` needs the Cloud Billing Budget API on the project that runs the command.
echo "=== [1/3] Enabling the Cloud Billing Budget API ==="
if [ "${DRY_RUN}" -eq 1 ]; then
  echo "+ gcloud services enable billingbudgets.googleapis.com --project ${PROJECT_ID}"
else
  gcloud services enable billingbudgets.googleapis.com --project "${PROJECT_ID}"
fi

echo "=== [2/3] Checking that the budget does not exist yet ==="
if [ "${DRY_RUN}" -eq 0 ]; then
  EXISTING="$(gcloud billing budgets list --billing-account "${BILLING_ACCOUNT_ID}" \
    --filter="displayName=\"${BUDGET_DISPLAY_NAME}\"" --format='value(name)')"
  if [ -n "${EXISTING}" ]; then
    echo "A budget named '${BUDGET_DISPLAY_NAME}' already exists: ${EXISTING}"
    echo "Nothing was created. Change it with 'gcloud billing budgets update' or pick another BUDGET_DISPLAY_NAME."
    exit 0
  fi
fi

ARGS=(
  billing budgets create
  --billing-account "${BILLING_ACCOUNT_ID}"
  --display-name "${BUDGET_DISPLAY_NAME}"
  --budget-amount "${BUDGET_AMOUNT}"
  --calendar-period month
  --filter-projects "projects/${PROJECT_ID}"
  --threshold-rule percent=0.5
  --threshold-rule percent=0.9
  --threshold-rule percent=1.0
  --threshold-rule percent=1.0,basis=forecasted-spend
)
if [ -n "${BUDGET_PUBSUB_TOPIC}" ]; then
  ARGS+=(--notifications-rule-pubsub-topic "${BUDGET_PUBSUB_TOPIC}")
fi
if [ -n "${BUDGET_CHANNELS}" ]; then
  ARGS+=(--notifications-rule-monitoring-notification-channels "${BUDGET_CHANNELS}")
fi

echo "=== [3/3] Creating the budget '${BUDGET_DISPLAY_NAME}' (${BUDGET_AMOUNT} a month) ==="
if [ "${DRY_RUN}" -eq 1 ]; then
  echo "+ gcloud ${ARGS[*]}"
  echo "Dry run: nothing was created."
else
  gcloud "${ARGS[@]}"
  echo "Budget created. Alerts at 50 %, 90 % and 100 % of ${BUDGET_AMOUNT} a month, and when the forecast reaches 100 %."
  echo "This is an alert only: it does not stop spending. See DAILY_TOKEN_BUDGET for the limit the application enforces."
  echo "Check it with: gcloud billing budgets list --billing-account '${BILLING_ACCOUNT_ID}'"
fi
