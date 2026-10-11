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
    SELECT '73041900' AS hs_code,
           'Line pipe of a kind used for oil or gas pipelines, seamless, of iron or steel' AS description,
           'SG' AS destination_country,
           ['MILL_TEST_CERTIFICATE'] AS required_documents,
           'demo-curated' AS rule_set,
           'Demo rule set (prototype); not an official AHTN requirement' AS regulation_ref
    UNION ALL
    SELECT '73043100',
           'Other tubes, pipes and hollow profiles, seamless, of circular cross-section, of iron or non-alloy steel: Cold-drawn or cold-rolled (cold-reduced)',
           'SG',
           ['MILL_TEST_CERTIFICATE'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
    UNION ALL
    SELECT '10019910',
           'Wheat and meslin: Other: Fit for human consumption',
           'SG',
           ['PHYTOSANITARY'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
    UNION ALL
    SELECT '09012110',
           'Coffee, whether or not roasted or decaffeinated: Roasted: Not decaffeinated',
           'SG',
           ['PHYTOSANITARY', 'CERTIFICATE_OF_ORIGIN'],
           'demo-curated',
           'Demo rule set (prototype); not an official AHTN requirement'
) t
JOIN ML.GENERATE_EMBEDDING(
    MODEL `cargoclear-hackathon.ahtn.embedding_model`,
    (
        SELECT '73041900' AS hs_code, 'Line pipe of a kind used for oil or gas pipelines, seamless, of iron or steel' AS content
        UNION ALL
        SELECT '73043100', 'Other tubes, pipes and hollow profiles, seamless, of circular cross-section, of iron or non-alloy steel: Cold-drawn or cold-rolled (cold-reduced)'
        UNION ALL
        SELECT '10019910', 'Wheat and meslin: Other: Fit for human consumption'
        UNION ALL
        SELECT '09012110', 'Coffee, whether or not roasted or decaffeinated: Roasted: Not decaffeinated'
    )
) e ON t.hs_code = e.hs_code;
