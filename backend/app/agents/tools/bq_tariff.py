"""BigQuery tariff lookup tool for the Grounding Agent.

Executes VECTOR_SEARCH against the AHTN master_tariff table using
ML.GENERATE_EMBEDDING to embed the query commodity description.

Per v4.0 Specification Appendix D:
  - Table: `cargoclear-hackathon.ahtn.master_tariff`
  - Index: `tariff_vector_index` (TREE_AH, COSINE distance)
  - Pre-filter: `destination_country = @dest`
  - Returns: hs_code, description, required_documents, cosine distance.

Provides an offline local seed matching fallback when in demo mode.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import structlog

from app.core.config import settings
from app.core.mode import no_credentials_message, use_live_gcp
from app.domain.provenance import REGULATION_REF_DEMO, RULE_SET_DEMO
from app.gateway.errors import UpstreamError

logger = structlog.get_logger(__name__)

AMBIGUITY_THRESHOLD = 0.35  # Cosine distance > 0.35 considered ambiguous

VECTOR_SQL = """
SELECT
    base.hs_code,
    base.description,
    base.required_documents,
    base.rule_set,
    base.regulation_ref,
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

    if not use_live_gcp():
        if settings.app_mode == "live":
            raise UpstreamError(no_credentials_message())
        logger.info("bq_client_mock_mode", reason="Running in demo mode without GCP credentials")
        return None

    try:
        from google.cloud import bigquery

        _bq_client = bigquery.Client(project=settings.project_id)
        return _bq_client
    except Exception as exc:
        if settings.app_mode == "live":
            raise UpstreamError(f"BigQuery client init failed in live mode: {type(exc).__name__}") from exc
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
        Each entry contains: hs_code, description, required_documents, rule_set, regulation_ref, distance.

    Use :func:`lookup_tariff_with_source` when you also need to know where the answer came from.
    """
    hits, _source = lookup_tariff_with_source(description, destination_country)
    return hits


def lookup_tariff_with_source(
    description: str,
    destination_country: str = "SG",
) -> tuple[list[dict[str, Any]], Literal["bigquery", "seed"]]:
    """Like :func:`lookup_tariff`, but also reports which backend answered.

    Returns:
        ``(hits, source)`` where source is ``"bigquery"`` when the vector search answered and
        ``"seed"`` when the offline local seed did (demo mode only; live mode raises instead).
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
            results = [_with_provenance(dict(row)) for row in job.result()]
            logger.info("bq_vector_search_success", count=len(results), desc=description[:30])
            return results, "bigquery"
        except Exception as exc:
            if settings.app_mode == "live":
                raise UpstreamError(f"BigQuery vector query failed: {type(exc).__name__}") from exc
            logger.warning("bq_vector_query_failed", error=str(exc), fallback="seed_data")

    # Offline local seed fallback
    return _local_seed_search(description, destination_country), "seed"


def _with_provenance(candidate: dict[str, Any]) -> dict[str, Any]:
    """Every candidate states its rule set and reference; rows that carry none get the prototype wording."""
    candidate["rule_set"] = candidate.get("rule_set") or RULE_SET_DEMO
    candidate["regulation_ref"] = candidate.get("regulation_ref") or REGULATION_REF_DEMO
    return candidate


def _local_seed_search(query: str, destination_country: str) -> list[dict[str, Any]]:
    """Simulates vector search against local seed records.

    ``query`` is the commodity DESCRIPTION only. It is scored by token overlap with each row's description;
    digits in the query get no special treatment, so a declared HS code can never pull its own row up the ranking.
    """
    seed_file = Path(__file__).resolve().parents[4] / "infra" / "bigquery" / "seed" / "sample_tariff.json"
    records: list[dict[str, Any]] = []

    if seed_file.exists():
        try:
            records = json.loads(seed_file.read_text(encoding="utf-8"))
        except Exception:
            records = []

    if not records:
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

    filtered = [r for r in records if r.get("destination_country", "SG") == destination_country.upper()]
    if not filtered:
        filtered = records

    q_tokens = set(query.lower().replace(",", " ").replace("-", " ").split())
    candidates = []

    for item in filtered:
        item_tokens = set(item["description"].lower().replace(",", " ").replace("-", " ").split())
        overlap = len(q_tokens & item_tokens)

        if overlap >= 2:
            distance = 0.08
        elif overlap == 1:
            distance = 0.22
        else:
            distance = 0.48

        candidates.append(_with_provenance({
            "hs_code": item["hs_code"],
            "description": item["description"],
            "required_documents": item.get("required_documents", []),
            "distance": distance,
            "rule_set": item.get("rule_set"),
            "regulation_ref": item.get("regulation_ref"),
        }))

    candidates.sort(key=lambda x: x["distance"])
    return candidates[:5]
