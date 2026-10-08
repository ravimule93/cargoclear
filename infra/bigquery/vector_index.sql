-- BigQuery Vector Search Index Creation (v4.0 Spec Appendix D)
-- Configured for TREE_AH (ScaNN-based) high recall index type

CREATE VECTOR INDEX IF NOT EXISTS `cargoclear-hackathon.ahtn.tariff_vector_index`
ON `cargoclear-hackathon.ahtn.master_tariff`(description_embedding)
STORING (hs_code, description, required_documents)
OPTIONS(
    index_type = 'TREE_AH',
    distance_type = 'COSINE',
    tree_ah_options = '{"leaf_node_embedding_count": 1000}'
);
