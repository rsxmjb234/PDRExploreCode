/*
find_ccd_measles_candidates.sql — Sample recent CCDs, statewide, all sources
==============================================================================

Purpose:
  Build the CCD candidate CSV for the Potential Measles Cases exploration.
  Per GUIDANCE.md / measles-candidate-detection.html step 1: breadth across
  sources matters far more than depth across time, so this samples a RECENT
  window statewide rather than looking back over history.

Based on Shared/findcandidatesforexplore.sql (same assigning-authority
derivation and per-AA random sampling pattern).

Output columns: bucket, key, qe, assigning_authority, last_modified
  - Matches what run_pipeline.py's candidate loader expects.
  - Export from Athena as CSV -> place in 05-Candidates/.

Tunable parameters (marked below):
  - RECENT_WINDOW_DAYS: how many days back to look (default 10)
  - SAMPLES_PER_AA:      WHERE rn <= N (default 20)
*/

WITH ranked AS (
    SELECT
        -- Assigning authority: path segment before "/ccd/" (or first segment).
        trim(
            CASE
                WHEN lower(split_part(i.key, '/', 1)) IN ('processed', 'error', 'backload')
                THEN split_part(i.key, '/', 2)
                ELSE split_part(i.key, '/', 1)
            END
        ) AS assigning_authority,

        -- QE: derived from the bucket name (strip prefix and -part2 suffix).
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
        -- RECENT_WINDOW_DAYS: last 10 days. Recency over history for this
        -- exploration — see measles-candidate-detection.html step 1.
        -- ====================================================================
        i.last_modified_date >= current_timestamp - interval '10' day

        -- All production QE buckets (primary and -part2), statewide.
        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false

        -- CCD only
        AND regexp_like(lower(i.key), '(^|/)ccd(/|$)')
)

SELECT
    bucket,
    key,
    qe,
    assigning_authority,
    date_format(last_modified_date, '%Y-%m-%d %H:%i:%s') AS last_modified
FROM ranked
-- ============================================================================
-- SAMPLES_PER_AA: up to 20 CCDs per assigning authority.
-- ============================================================================
WHERE rn <= 20
ORDER BY qe, assigning_authority
