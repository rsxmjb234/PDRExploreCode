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

ANCHOR TO THE MOST RECENT INVENTORY, NOT WALL-CLOCK "NOW":
  Time matters for this exploration — an unreported hint goes stale fast.
  But `current_timestamp` is wall-clock time, not necessarily when the
  inventory table was last refreshed. If the inventory lags behind real
  time by even a day, a plain `current_timestamp - interval '10' day`
  window silently misses the most recent real data. So this query first
  finds MAX(last_modified_date) actually present in the inventory (the
  "most recent inventory" anchor), then looks back 10 days FROM THAT POINT,
  not from wall-clock now. Same anchor pattern used in
  find_ccd_measles_candidates.sql — see that file's header for the full
  rationale and the cost note on the anchor subquery.

Output columns: bucket, key, qe, assigning_authority, last_modified
  - Matches what run_pipeline.py's candidate loader expects.
  - Export from Athena as CSV -> place in 05-Candidates/.

Tunable parameters (marked below):
  - RECENT_WINDOW_DAYS: how many days to look back from the most recent
    inventory data (default 10, for this POC)
  - SAMPLES_PER_AA:      WHERE rn <= N (default 20)
*/

WITH anchor AS (
    -- The most recent inventory data point actually present — the anchor
    -- for "look back 10 days", instead of wall-clock current_timestamp.
    SELECT MAX(last_modified_date) AS most_recent_date
    FROM pdr_inventory.pdr_inventory_prod_data_all
    WHERE bucket LIKE 'nyec-pdr-prod-%'
      AND is_latest = true
      AND coalesce(is_delete_marker, false) = false
),

ranked AS (
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
    CROSS JOIN anchor a

    WHERE
        -- ====================================================================
        -- RECENT_WINDOW_DAYS: last 10 days, measured BACK FROM THE MOST
        -- RECENT INVENTORY DATA (anchor.most_recent_date), not from
        -- wall-clock current_timestamp. See header note above.
        -- ====================================================================
        i.last_modified_date >= a.most_recent_date - interval '10' day
        AND i.last_modified_date <= a.most_recent_date

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
