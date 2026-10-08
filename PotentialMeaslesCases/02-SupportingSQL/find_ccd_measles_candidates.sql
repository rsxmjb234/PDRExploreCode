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

ANCHOR TO THE MOST RECENT INVENTORY, NOT WALL-CLOCK "NOW":
  Time matters for this exploration — an unreported hint goes stale fast
  (see measles-candidate-detection.html step 1). But `current_timestamp`
  is wall-clock time, not necessarily when the inventory table was last
  refreshed. If the inventory lags behind real time by even a day, a plain
  `current_timestamp - interval '10' day` window silently misses the most
  recent real data (or scans a window that doesn't actually line up with
  what's there). So this query first finds MAX(last_modified_date) actually
  present in the inventory (the "most recent inventory" anchor), then looks
  back 10 days FROM THAT POINT, not from wall-clock now.

  NOTE on cost: the anchor subquery scans production buckets once to find
  the max. Acceptable for this POC's data volume; same kind of relative-date
  performance tradeoff TRNMessageMix flagged and proceeded with. If this
  becomes a real cost concern, swap the anchor to MAX(dt) partition-pruned
  metadata instead.

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
    CROSS JOIN anchor a

    WHERE
        -- ====================================================================
        -- RECENT_WINDOW_DAYS: last 10 days, measured BACK FROM THE MOST
        -- RECENT INVENTORY DATA (anchor.most_recent_date), not from
        -- wall-clock current_timestamp. See header note above.
        -- ====================================================================
        i.last_modified_date >= a.most_recent_date - interval '10' day
        AND i.last_modified_date <= a.most_recent_date

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
