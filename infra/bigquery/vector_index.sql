-- BigQuery Vector Search Index (v4.0 Spec Appendix D). Normally created by infra/bigquery/setup_tariff.sh.
-- TREE_AH (ScaNN-based) index, COSINE distance.
--
-- BigQuery builds and uses a vector index only for tables of at least 5,000 rows; below that VECTOR_SEARCH scans the
-- table (exact, and fast at this size), so the demo tariff (a handful of rows) runs without one.
-- destination_country is STORED so that the pre-filter in the API's query
--   VECTOR_SEARCH((SELECT * FROM table WHERE destination_country = @dest), ...)
-- can use the index.
-- Replace the project with yours (setup_tariff.sh does this for you).

CREATE VECTOR INDEX IF NOT EXISTS `cargoclear-hackathon.ahtn.tariff_vector_index`
ON `cargoclear-hackathon.ahtn.master_tariff`(description_embedding)
STORING (hs_code, description, required_documents, destination_country)
OPTIONS(
    index_type = 'TREE_AH',
    distance_type = 'COSINE',
    tree_ah_options = '{"leaf_node_embedding_count": 1000}'
);
