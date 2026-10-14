-- Demo-curated tariff rows with their embeddings. The rows are PROTOTYPE rules (rule_set 'demo-curated'), not an official
-- AHTN or national tariff requirement. Run by infra/bigquery/setup_tariff.sh (which points the names at the deployment).
--
-- Each row has a composite key k = '<destination>:<hs_code>': the same HS code appears for more than one destination, so
-- joining the rows to their embeddings on hs_code alone would multiply them.
-- Keep this file and sample_tariff.json (the offline seed of demo mode) in step: tests/unit/test_grounding_policy.py compares them.
INSERT INTO `cargoclear-hackathon.ahtn.master_tariff`
(hs_code, description, destination_country, required_documents, rule_set, regulation_ref, description_embedding)
SELECT
    t.hs_code,
    t.description,
    t.destination_country,
    t.required_documents,
    t.rule_set,
    t.regulation_ref,
    e.ml_generate_embedding_result AS description_embedding
FROM (
    SELECT 'SG:73041900' AS k, '73041900' AS hs_code,
           'Line pipe of a kind used for oil or gas pipelines, seamless, of iron or steel' AS description,
           'SG' AS destination_country,
           ['MILL_TEST_CERTIFICATE'] AS required_documents,
           'demo-curated' AS rule_set,
           'Demo rule set (prototype); not an official AHTN requirement' AS regulation_ref
    UNION ALL
    SELECT 'SG:73043100', '73043100',
           'Other tubes, pipes and hollow profiles, seamless, of circular cross-section, of iron or non-alloy steel: Cold-drawn or cold-rolled (cold-reduced)',
           'SG',
           ['MILL_TEST_CERTIFICATE'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
    UNION ALL
    SELECT 'SG:10019910', '10019910',
           'Wheat and meslin: Other: Fit for human consumption',
           'SG',
           ['PHYTOSANITARY'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
    UNION ALL
    SELECT 'SG:09012110', '09012110',
           'Coffee, whether or not roasted or decaffeinated: Roasted: Not decaffeinated',
           'SG',
           ['PHYTOSANITARY', 'CERTIFICATE_OF_ORIGIN'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
    UNION ALL
    SELECT 'IN:73043100', '73043100',
           'Other tubes, pipes and hollow profiles, seamless, of circular cross-section, of iron or non-alloy steel: Cold-drawn or cold-rolled (cold-reduced)',
           'IN',
           ['MILL_TEST_CERTIFICATE'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
    UNION ALL
    SELECT 'IN:73045100', '73045100',
           'Other tubes, pipes and hollow profiles, seamless, of circular cross-section, of other alloy steel: Cold-drawn or cold-rolled (cold-reduced)',
           'IN',
           ['MILL_TEST_CERTIFICATE'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
    UNION ALL
    SELECT 'IN:73041900', '73041900',
           'Line pipe of a kind used for oil or gas pipelines, seamless, of iron or steel',
           'IN',
           ['MILL_TEST_CERTIFICATE'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
) t
JOIN ML.GENERATE_EMBEDDING(
    MODEL `cargoclear-hackathon.ahtn.embedding_model`,
    (
        SELECT 'SG:73041900' AS k, 'Line pipe of a kind used for oil or gas pipelines, seamless, of iron or steel' AS content
        UNION ALL
        SELECT 'SG:73043100', 'Other tubes, pipes and hollow profiles, seamless, of circular cross-section, of iron or non-alloy steel: Cold-drawn or cold-rolled (cold-reduced)'
        UNION ALL
        SELECT 'SG:10019910', 'Wheat and meslin: Other: Fit for human consumption'
        UNION ALL
        SELECT 'SG:09012110', 'Coffee, whether or not roasted or decaffeinated: Roasted: Not decaffeinated'
        UNION ALL
        SELECT 'IN:73043100', 'Other tubes, pipes and hollow profiles, seamless, of circular cross-section, of iron or non-alloy steel: Cold-drawn or cold-rolled (cold-reduced)'
        UNION ALL
        SELECT 'IN:73045100', 'Other tubes, pipes and hollow profiles, seamless, of circular cross-section, of other alloy steel: Cold-drawn or cold-rolled (cold-reduced)'
        UNION ALL
        SELECT 'IN:73041900', 'Line pipe of a kind used for oil or gas pipelines, seamless, of iron or steel'
    )
) e ON t.k = e.k;
