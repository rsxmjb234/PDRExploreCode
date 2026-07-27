/*
DEBUG: Find QE|AA combinations that appear in findallccdcontributors logic
       but have ZERO results in findcandidatesforexplore logic.

This tells us exactly which sources are being lost and why.

Approach:
  - "all_sources" = every QE|AA that contributed CCDs on Jul 21-22
    (using findallccdcontributors logic — includes all path types)
  - "candidate_sources" = every QE|AA that findcandidatesforexplore found
    (using the same dt and time window)
  - Result = all_sources MINUS candidate_sources (the gap)
*/

WITH all_sources AS (
    -- This mirrors findallccdcontributors.sql logic exactly
    SELECT DISTINCT
        regexp_replace(regexp_replace(i.bucket, '^nyec-pdr-prod-', ''), '-part2$', '') AS qe,
        trim(
            CASE
                WHEN lower(split_part(i.key, '/', 1)) IN ('processed', 'error', 'backload')
                THEN split_part(i.key, '/', 2)
                ELSE split_part(i.key, '/', 1)
            END
        ) AS assigning_authority
    FROM pdr_inventory.pdr_inventory_prod_data_all i
    WHERE
        i.dt = '2026-07-22-01-00'
        AND i.last_modified_date >= timestamp '2026-07-19 00:00:00'
        AND i.last_modified_date <  timestamp '2026-07-22 00:00:00'
        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false
        AND regexp_like(lower(i.key), '(^|/)ccd(/|$)')
),

candidate_sources AS (
    -- This mirrors findcandidatesforexplore.sql logic exactly
    SELECT DISTINCT
        regexp_replace(regexp_replace(i.bucket, '^nyec-pdr-prod-', ''), '-part2$', '') AS qe,
        trim(
            CASE
                WHEN lower(split_part(i.key, '/', 1)) IN ('processed', 'error', 'backload')
                THEN split_part(i.key, '/', 2)
                ELSE split_part(i.key, '/', 1)
            END
        ) AS assigning_authority
    FROM pdr_inventory.pdr_inventory_prod_data_all i
    WHERE
        i.dt = '2026-07-22-01-00'
        AND i.last_modified_date >= timestamp '2026-07-19 00:00:00'
        AND i.last_modified_date <  timestamp '2026-07-22 00:00:00'
        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false
        -- This is the ONLY filter that differs: candidates requires .xml extension
        AND regexp_like(lower(i.key), '(^|/)ccd(/|$)')
        AND lower(i.key) LIKE '%.xml'
)

-- Show sources in all_sources that are NOT in candidate_sources
SELECT
    a.qe,
    a.assigning_authority,
    a.qe || '|' || a.assigning_authority AS qe_aa
FROM all_sources a
LEFT JOIN candidate_sources c
    ON a.qe = c.qe AND a.assigning_authority = c.assigning_authority
WHERE c.assigning_authority IS NULL
ORDER BY a.qe, a.assigning_authority
