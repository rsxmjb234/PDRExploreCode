-- Debug: understand the data shape

-- Total rows
SELECT 'total_rows' AS metric, COUNT(*) AS cnt FROM pdr_inventory.ehr_software_analysis;

-- Distinct values for each grouping key
SELECT 'distinct_qe_aa' AS metric, COUNT(DISTINCT qe_aa) AS cnt FROM pdr_inventory.ehr_software_analysis;
SELECT 'distinct_input_aa' AS metric, COUNT(DISTINCT input_assigning_authority) AS cnt FROM pdr_inventory.ehr_software_analysis;
SELECT 'distinct_path' AS metric, COUNT(DISTINCT path) AS cnt FROM pdr_inventory.ehr_software_analysis;

-- Average rows per qe_aa (should be ~5 if you sampled 5 per source)
SELECT 
    'avg_rows_per_qe_aa' AS metric,
    ROUND(1.0 * COUNT(*) / COUNT(DISTINCT qe_aa), 1) AS cnt
FROM pdr_inventory.ehr_software_analysis;

-- Show a sample of duplicated input_assigning_authority values (same AA, different qe_aa)
SELECT 
    input_assigning_authority, 
    COUNT(DISTINCT qe_aa) AS num_qe_aa_values,
    COUNT(*) AS total_rows
FROM pdr_inventory.ehr_software_analysis
GROUP BY input_assigning_authority
HAVING COUNT(DISTINCT qe_aa) > 1
ORDER BY num_qe_aa_values DESC
LIMIT 20;
