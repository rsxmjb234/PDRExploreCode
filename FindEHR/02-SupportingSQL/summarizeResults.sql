/*
summarizeResults.sql — EHR Market Share Summary

Simple approach:
  1. For each qe_aa (unique source), pick the EHR guess (majority vote across sampled CCDs)
  2. Count distinct sources per EHR
  3. Join to inventory volume for CCD counts

Configuration:
  Change inventory_dt below to your latest partition.
*/

WITH config AS (
    SELECT
        '2026-08-04-01-00' AS inventory_dt  -- << CHANGE THIS to your latest partition
),

-- One EHR per source: majority vote across all sampled CCDs for that AA
votes AS (
    SELECT
        input_assigning_authority,
        ehr_guess,
        COUNT(*) AS cnt
    FROM pdr_inventory.ehr_software_analysis
    WHERE ehr_guess != '(download error)'
      AND input_assigning_authority != ''
    GROUP BY input_assigning_authority, ehr_guess
),

-- Pick the winning EHR per source
winners AS (
    SELECT
        input_assigning_authority,
        ehr_guess,
        ROW_NUMBER() OVER (PARTITION BY input_assigning_authority ORDER BY cnt DESC) AS rn
    FROM votes
),

-- One row per source with its EHR
source_to_ehr AS (
    SELECT input_assigning_authority, ehr_guess
    FROM winners
    WHERE rn = 1
),

-- Count sources per EHR
ehr_counts AS (
    SELECT
        ehr_guess,
        COUNT(*) AS source_count
    FROM source_to_ehr
    GROUP BY ehr_guess
),

total_sources AS (
    SELECT COUNT(*) AS total FROM source_to_ehr
),

-- Volume: CCDs per qe_aa from inventory (last 30 days) — count AND bytes
source_volume AS (
    SELECT
        regexp_replace(regexp_replace(i.bucket, '^nyec-pdr-prod-', ''), '-part2$', '')
            || '|'
            || trim(
                CASE
                    WHEN lower(split_part(i.key, '/', 1)) IN ('processed', 'error', 'backload')
                    THEN split_part(i.key, '/', 2)
                    ELSE split_part(i.key, '/', 1)
                END
            ) AS qe_aa,
        COUNT(*) AS ccd_count_30d,
        SUM(i.size) AS total_bytes_30d
    FROM pdr_inventory.pdr_inventory_prod_data_all i
    CROSS JOIN config c
    WHERE
        i.dt = c.inventory_dt
        AND i.last_modified_date >= date_add('day', -30, current_timestamp)
        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false
        AND regexp_like(lower(i.key), '(^|/)ccd(/|$)')
    GROUP BY 1
),

-- Sum volume by EHR (count + bytes)
ehr_volume AS (
    SELECT
        s.ehr_guess,
        SUM(v.ccd_count_30d) AS total_ccds_30d,
        SUM(v.total_bytes_30d) AS total_bytes_30d
    FROM source_to_ehr s
    LEFT JOIN source_volume v ON s.input_assigning_authority = split_part(v.qe_aa, '|', 2)
    GROUP BY s.ehr_guess
),

total_volume AS (
    SELECT
        SUM(total_ccds_30d) AS grand_total_30d,
        SUM(total_bytes_30d) AS grand_total_bytes_30d
    FROM ehr_volume
)

SELECT
    c.ehr_guess AS ehr_name,
    c.source_count,
    ROUND(1.0 * c.source_count / t.total, 4) AS pct_of_sources,
    COALESCE(v.total_ccds_30d, 0) AS ccds_last_30_days,
    COALESCE(v.total_ccds_30d * 12, 0) AS projected_annual_ccds,
    ROUND(1.0 * COALESCE(v.total_ccds_30d, 0) / NULLIF(tv.grand_total_30d, 0), 4) AS pct_of_all_shinny_data_by_count,
    COALESCE(v.total_bytes_30d, 0) AS bytes_last_30_days,
    ROUND(COALESCE(v.total_bytes_30d, 0) / 1073741824.0, 2) AS gb_last_30_days,
    COALESCE(v.total_bytes_30d * 12, 0) AS projected_annual_bytes,
    ROUND(COALESCE(v.total_bytes_30d * 12, 0) / 1099511627776.0, 2) AS projected_annual_tb,
    ROUND(1.0 * COALESCE(v.total_bytes_30d, 0) / NULLIF(tv.grand_total_bytes_30d, 0), 4) AS pct_of_all_shinny_data_by_bytes
FROM ehr_counts c
CROSS JOIN total_sources t
LEFT JOIN ehr_volume v ON c.ehr_guess = v.ehr_guess
CROSS JOIN total_volume tv
ORDER BY c.source_count DESC
