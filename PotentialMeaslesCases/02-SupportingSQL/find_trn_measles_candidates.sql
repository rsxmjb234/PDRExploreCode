/*
find_trn_measles_candidates.sql — Sample recent TRNs, statewide, all sources
==============================================================================

Purpose:
  Build the TRN candidate CSV for the Potential Measles Cases exploration.
  Copied from TRNMessageMix/02-SupportingSQL/find_trn_candidates.sql (same
  "/trn/" path filter), with the date window changed to match THIS project's
  recent-window intent — TRNMessageMix intentionally looks at data that's
  10-20 days old; this exploration wants the opposite (as recent as possible,
  since we're trying to catch unreported hints before they go stale — see
  measles-candidate-detection.html step 1).

Output columns: bucket, key, qe, assigning_authority, last_modified
  - Matches what run_pipeline.py's candidate loader expects.
  - Export from Athena as CSV -> place in 05-Candidates/.

Tunable parameters (marked below):
  - RECENT_WINDOW_DAYS: how many days back to look (default 10)
  - SAMPLES_PER_AA:      WHERE rn <= N (default 20)
*/

WITH ranked AS (
    SELECT
        trim(
            CASE
                WHEN lower(split_part(i.key, '/', 1)) IN ('processed', 'error', 'backload')
                THEN split_part(i.key, '/', 2)
                ELSE split_part(i.key, '/', 1)
            END
        ) AS assigning_authority,

        regexp_replace(
            regexp_replace(i.bucket, '^nyec-pdr-prod-', ''),
            '-part2$',
            ''
        ) AS qe,

        i.bucket,
        i.key,
        i.size,
        i.last_modified_date,

        row_number() OVER (
            PARTITION BY
                trim(
                    CASE
                        WHEN lower(split_part(i.key, '/', 1)) IN ('processed', 'error', 'backload')
                        THEN split_part(i.key, '/', 2)
                        ELSE split_part(i.key, '/', 1)
                    END
                )
            ORDER BY random()
        ) AS rn

    FROM pdr_inventory.pdr_inventory_prod_data_all i

    WHERE
        -- ====================================================================
        -- RECENT_WINDOW_DAYS: last 10 days (NOT the 10-20-day-old window
        -- TRNMessageMix uses — this project wants the freshest data).
        -- ====================================================================
        i.last_modified_date >= current_timestamp - interval '10' day

        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false

        -- TRN messages ONLY
        AND regexp_like(lower(i.key), '(^|/)trn(/|$)')
)

SELECT
    bucket,
    key,
    qe,
    assigning_authority,
    date_format(last_modified_date, '%Y-%m-%d %H:%i:%s') AS last_modified
FROM ranked
-- ============================================================================
-- SAMPLES_PER_AA: up to 20 TRNs per assigning authority.
-- ============================================================================
WHERE rn <= 20
ORDER BY qe, assigning_authority
