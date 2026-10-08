"""BigQuery tariff lookup tool for the Grounding Agent.

Executes VECTOR_SEARCH against the AHTN master_tariff table using
ML.GENERATE_EMBEDDING to embed the query description.

DDL for the index (infra/bigquery/vector_index.sql):
  CREATE VECTOR INDEX ON master_tariff(description_embedding)
  OPTIONS(index_type = 'TREE_AH', distance_type = 'COSINE',
          tree_ah_options = '{"leaf_node_embedding_count": 1000}');

Phase 3: Uncomment BigQuery client.
Skeleton: Function signature defined; raises NotImplementedError.
"""

from __future__ import annotations

from app.core.config import settings

VECTOR_SQL = """
SELECT
    base.hs_code,
    base.description,
    base.required_documents,
    distance
FROM VECTOR_SEARCH(
    TABLE `{tariff_table}`,
    'description_embedding',
    (SELECT ml_generate_embedding_result AS embedding
     FROM ML.GENERATE_EMBEDDING(
         MODEL `{embedding_model}`,
         (SELECT @q AS content)
     )),
    top_k => 5,
    distance_type => 'COSINE'
)
WHERE destination_country = @dest
ORDER BY distance
"""


def lookup_tariff(description: str, destination_country: str = "SG") -> list[dict]:
    """Search AHTN master tariffs by commodity description using vector similarity.

    Args:
        description:         Free-text commodity description from extraction.
        destination_country: ISO alpha-2 country code for pre-filtering.

    Returns:
        List of up to 5 tariff candidates sorted by cosine distance (ascending).
        Each dict has: hs_code, description, required_documents, distance.

    Phase 3: Uncomment BigQuery client below.
    Skeleton: Raises NotImplementedError.
    """
    # ---- Phase 3: uncomment ----
    # from google.cloud import bigquery
    # bq = bigquery.Client(project=settings.project_id)
    # sql = VECTOR_SQL.format(
    #     tariff_table=settings.tariff_table_fqn,
    #     embedding_model=settings.embedding_model_fqn,
    # )
    # job = bq.query(
    #     sql,
    #     job_config=bigquery.QueryJobConfig(query_parameters=[
    #         bigquery.ScalarQueryParameter("q", "STRING", description),
    #         bigquery.ScalarQueryParameter("dest", "STRING", destination_country),
    #     ]),
    # )
    # return [dict(r) for r in job.result()]
    # ----------------------------
    raise NotImplementedError("BigQuery grounding not yet connected. Implement in Phase 3.")
