#!/usr/bin/env bash
# =============================================================================
# CargoClear: BigQuery tariff grounding setup (idempotent)
#
# Creates, in order, everything the grounding agent (backend/app/agents/tools/bq_tariff.py) needs:
#   1. a BigQuery CLOUD_RESOURCE connection and its Vertex AI permission,
#   2. the dataset and the master_tariff table (infra/bigquery/schema.json),
#   3. the REMOTE embedding model over a Vertex AI embedding endpoint,
#   4. the demo-curated seed rows (re-running replaces them),
#   5. the vector index, but only when the table is big enough for BigQuery to use one,
#   6. a self-check that embeds a sentence and runs the same VECTOR_SEARCH shape the API runs.
#
# Required:
#   PROJECT_ID           target project
#   EMBEDDING_ENDPOINT   the Vertex AI embedding model the remote model wraps, e.g. a model name or full endpoint URL.
#                        NO DEFAULT ON PURPOSE: Google retires embedding models (text-embedding-004 is shut down;
#                        gemini-embedding-001 has a scheduled shutdown). Look up what is served to your project today
#                        (docs/GCP_VERIFICATION.md) and pass it explicitly.
# Optional:
#   REGION (asia-south1)  BQ_DATASET (ahtn)  BQ_TABLE_TARIFF (master_tariff)  BQ_MODEL_EMBEDDING (embedding_model)
#   BQ_CONNECTION (cargoclear-vertex)  RUNTIME_SERVICE_ACCOUNT (granted use of the connection, if given)
#
# The runtime identity also needs roles/bigquery.dataViewer + roles/bigquery.jobUser (infra/bootstrap.sh).
# IMPORTANT: if you change EMBEDDING_ENDPOINT, the stored vectors and the query vectors must come from the SAME model:
# re-run this script (it re-embeds the seed rows) and make the API's BQ_MODEL_EMBEDDING point at the model it creates.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID must identify the target GCP project}"
EMBEDDING_ENDPOINT="${EMBEDDING_ENDPOINT:?EMBEDDING_ENDPOINT must name a Vertex AI embedding model that is currently served to this project (see the header of this script)}"
REGION="${REGION:-asia-south1}"
BQ_DATASET="${BQ_DATASET:-ahtn}"
BQ_TABLE_TARIFF="${BQ_TABLE_TARIFF:-master_tariff}"
BQ_MODEL_EMBEDDING="${BQ_MODEL_EMBEDDING:-embedding_model}"
BQ_CONNECTION="${BQ_CONNECTION:-cargoclear-vertex}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TABLE="${PROJECT_ID}.${BQ_DATASET}.${BQ_TABLE_TARIFF}"
MODEL="${PROJECT_ID}.${BQ_DATASET}.${BQ_MODEL_EMBEDDING}"
CONNECTION_REF="${PROJECT_ID}.${REGION}.${BQ_CONNECTION}"
BQ_QUERY=(bq --project_id="${PROJECT_ID}" --location="${REGION}" query --use_legacy_sql=false --quiet)

echo "=== [1/6] BigQuery connection ${CONNECTION_REF} ==="
bq --project_id="${PROJECT_ID}" mk --connection --location="${REGION}" --connection_type=CLOUD_RESOURCE "${BQ_CONNECTION}" || true
CONNECTION_SA="$(bq --project_id="${PROJECT_ID}" --location="${REGION}" show --connection --format=json "${CONNECTION_REF}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["cloudResource"]["serviceAccountId"])')"
echo "connection service account: ${CONNECTION_SA}"
# the connection calls Vertex AI on behalf of the remote model
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CONNECTION_SA}" --role="roles/aiplatform.user" --condition=None --quiet >/dev/null
if [[ -n "${RUNTIME_SERVICE_ACCOUNT}" ]]; then
  # the API's identity may use the connection (needed to run inference with a remote model)
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" --role="roles/bigquery.connectionUser" --condition=None --quiet >/dev/null
fi

echo "=== [2/6] Dataset and table ${TABLE} ==="
bq --project_id="${PROJECT_ID}" --location="${REGION}" mk -d "${BQ_DATASET}" || true
bq --project_id="${PROJECT_ID}" --location="${REGION}" mk --table "${TABLE}" "${HERE}/schema.json" || true

echo "=== [3/6] Remote embedding model ${MODEL} -> ${EMBEDDING_ENDPOINT} ==="
"${BQ_QUERY[@]}" "CREATE OR REPLACE MODEL \`${MODEL}\` REMOTE WITH CONNECTION \`${CONNECTION_REF}\` OPTIONS (ENDPOINT = '${EMBEDDING_ENDPOINT}')"

echo "=== [4/6] Seed rows (demo-curated; replaces what is there) ==="
"${BQ_QUERY[@]}" "TRUNCATE TABLE \`${TABLE}\`"
# the checked-in seed names the hackathon project/dataset/table/model; point it at this deployment
sed -e "s#cargoclear-hackathon\.ahtn\.master_tariff#${TABLE}#g" \
    -e "s#cargoclear-hackathon\.ahtn\.embedding_model#${MODEL}#g" \
    "${HERE}/seed/seed_master_tariff.sql" | "${BQ_QUERY[@]}"

ROWS="$("${BQ_QUERY[@]}" --format=csv "SELECT COUNT(*) FROM \`${TABLE}\`" | tail -1)"
echo "master_tariff rows: ${ROWS}"

echo "=== [5/6] Vector index ==="
# BigQuery builds and uses a vector index only for tables of at least 5,000 rows; below that VECTOR_SEARCH scans the
# table, which is exact and fast. So the index is created when it can matter.
if [[ "${ROWS}" -ge 5000 ]]; then
  "${BQ_QUERY[@]}" "CREATE VECTOR INDEX IF NOT EXISTS tariff_vector_index ON \`${TABLE}\`(description_embedding) STORING (hs_code, description, required_documents, destination_country) OPTIONS(index_type='TREE_AH', distance_type='COSINE', tree_ah_options='{\"leaf_node_embedding_count\": 1000}')"
else
  echo "skipped: ${ROWS} rows (< 5000); brute-force VECTOR_SEARCH is used"
fi

echo "=== [6/6] Self-check: embed a sentence, then the API's own query shape ==="
"${BQ_QUERY[@]}" "SELECT ARRAY_LENGTH(ml_generate_embedding_result) AS embedding_dimensions, ml_generate_embedding_status AS status FROM ML.GENERATE_EMBEDDING(MODEL \`${MODEL}\`, (SELECT 'Seamless carbon steel pipes API 5L Grade B' AS content))"
"${BQ_QUERY[@]}" --parameter="q:STRING:Seamless carbon steel pipes API 5L Grade B" --parameter="dest:STRING:SG" \
  "SELECT base.hs_code, base.required_documents, distance FROM VECTOR_SEARCH((SELECT * FROM \`${TABLE}\` WHERE destination_country = @dest), 'description_embedding', (SELECT ml_generate_embedding_result AS embedding FROM ML.GENERATE_EMBEDDING(MODEL \`${MODEL}\`, (SELECT @q AS content))), top_k => 5, distance_type => 'COSINE') ORDER BY distance"
echo "Expected: HS 73041900 first, required_documents [MILL_TEST_CERTIFICATE], a small distance (< 0.35 is 'not ambiguous')."
echo "Set BQ_MODEL_EMBEDDING=${BQ_MODEL_EMBEDDING} on the API (deploy_api.sh does) and run scripts/preflight_gcp.py."
