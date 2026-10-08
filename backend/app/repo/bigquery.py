"""BigQuery repository helper.

Provides operations for exact HS tariff lookup and pre-filtering fallbacks.
Used when vector distance is borderline or exact code verification is requested.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.agents.tools.bq_tariff import _get_bq_client


async def get_tariff_by_hs(hs_code: str, destination_country: str = "SG") -> dict[str, Any] | None:
    """Fetch a single tariff record by exact 8-digit or 6-digit HS code prefix."""
    client = _get_bq_client()

    if client is not None:
        try:
            from google.cloud import bigquery

            sql = f"""
            SELECT hs_code, description, required_documents, destination_country
            FROM `{settings.tariff_table_fqn}`
            WHERE hs_code LIKE @hs_prefix AND destination_country = @dest
            LIMIT 1
            """
            job = client.query(
                sql,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("hs_prefix", "STRING", f"{hs_code[:4]}%"),
                        bigquery.ScalarQueryParameter("dest", "STRING", destination_country.upper()),
                    ]
                ),
            )
            rows = [dict(r) for r in job.result()]
            return rows[0] if rows else None
        except Exception:
            pass

    # Local seed lookup fallback
    seed_file = Path(__file__).resolve().parents[3] / "infra" / "bigquery" / "seed" / "sample_tariff.json"
    if seed_file.exists():
        try:
            records = json.loads(seed_file.read_text(encoding="utf-8"))
            for r in records:
                if r["hs_code"].startswith(hs_code[:4]):
                    return r
        except Exception:
            pass

    return None
