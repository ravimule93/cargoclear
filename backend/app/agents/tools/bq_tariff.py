"""BigQuery tariff lookup tool for the Grounding Agent.

Executes VECTOR_SEARCH against the AHTN master_tariff table using
ML.GENERATE_EMBEDDING to embed the query commodity description.

Per v4.0 Specification Appendix D:
  - Table: `cargoclear-hackathon.ahtn.master_tariff`
  - Index: `tariff_vector_index` (TREE_AH, COSINE distance)
  - Pre-filter: `destination_country = @dest`
  - Returns: hs_code, description, required_documents, cosine distance.

Provides an offline local seed matching fallback when GCP credentials
are not present in the runtime environment.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

AMBIGUITY_THRESHOLD = 0.35  # Cosine distance > 0.35 considered ambiguous

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

_bq_client = None


def _get_bq_client():
    """Lazily initialize BigQuery client."""
    global _bq_client
    if _bq_client is not None:
        return _bq_client

    has_creds = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("K_SERVICE"))
    if not has_creds and os.getenv("USE_BIGQUERY_MOCK") != "false":
        logger.info("bq_client_mock_mode", reason="No GCP credentials found, running vector seed fallback")
        return None

    try:
        from google.cloud import bigquery

        _bq_client = bigquery.Client(project=settings.project_id)
        return _bq_client
    except Exception as exc:
        logger.warning("bq_client_init_failed", error=str(exc), fallback="seed_lookup")
        return None


def lookup_tariff(
    description: str,
    destination_country: str = "SG",
) -> list[dict[str, Any]]:
    """Search AHTN master tariffs by commodity description using vector similarity.

    Args:
        description: Free-text commodity description from extraction.
        destination_country: ISO alpha-2 country code for pre-filtering (e.g. SG, IN).

    Returns:
        List of up to 5 tariff candidates sorted by cosine distance (ascending).
        Each entry contains: hs_code, description, required_documents, distance.
    """
    client = _get_bq_client()

    if client is not None:
        try:
            from google.cloud import bigquery

            sql = VECTOR_SQL.format(
                tariff_table=settings.tariff_table_fqn,
                embedding_model=settings.embedding_model_fqn,
            )
            job = client.query(
                sql,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("q", "STRING", description),
                        bigquery.ScalarQueryParameter("dest", "STRING", destination_country.upper()),
                    ]
                ),
            )
            results = [dict(row) for row in job.result()]
            logger.info("bq_vector_search_success", count=len(results), desc=description[:30])
            return results
        except Exception as exc:
            logger.warning("bq_vector_query_failed", error=str(exc), fallback="seed_data")

    # Offline local seed fallback
    return _local_seed_search(description, destination_country)


def _local_seed_search(query: str, destination_country: str) -> list[dict[str, Any]]:
    """Simulates vector search against local AHTN seed records."""
    seed_file = Path(__file__).resolve().parents[3] / "infra" / "bigquery" / "seed" / "sample_tariff.json"
    records: list[dict[str, Any]] = []

    if seed_file.exists():
        try:
            records = json.loads(seed_file.read_text(encoding="utf-8"))
        except Exception:
            records = []

    if not records:
        # Fallback default records
        records = [
            {
                "hs_code": "73041900",
                "description": "Line pipe of a kind used for oil or gas pipelines, seamless, of iron or steel",
                "destination_country": "SG",
                "required_documents": ["MILL_TEST_CERTIFICATE"],
            },
            {
                "hs_code": "73043100",
                "description": "Other tubes, pipes and hollow profiles, seamless, circular cross-section, iron or non-alloy steel",
                "destination_country": "SG",
                "required_documents": ["MILL_TEST_CERTIFICATE"],
            },
            {
                "hs_code": "10019910",
                "description": "Wheat and meslin: Other: Fit for human consumption",
                "destination_country": "SG",
                "required_documents": ["PHYTOSANITARY"],
            },
        ]

    # Filter by destination country
    filtered = [r for r in records if r.get("destination_country", "SG") == destination_country.upper()]
    if not filtered:
        filtered = records

    # Token overlap heuristic to compute simulated cosine distance [0.0 - 1.0]
    q_tokens = set(query.lower().replace(",", " ").replace("-", " ").split())
    candidates = []

    for item in filtered:
        item_tokens = set(item["description"].lower().replace(",", " ").replace("-", " ").split())
        overlap = len(q_tokens & item_tokens)

        # Distance: 0.08 if high overlap, 0.45 if low overlap
        if overlap >= 2 or any(token in item["hs_code"] for token in q_tokens):
            distance = 0.08
        elif overlap == 1:
            distance = 0.22
        else:
            distance = 0.48

        candidates.append({
            "hs_code": item["hs_code"],
            "description": item["description"],
            "required_documents": item.get("required_documents", []),
            "distance": distance,
        })

    candidates.sort(key=lambda x: x["distance"])
    return candidates[:5]
