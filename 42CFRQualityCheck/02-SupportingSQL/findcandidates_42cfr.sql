/*
findcandidates_42cfr.sql — Get N random CCD S3 paths per assigning authority
                           WITH Part 2 routing indicator

Based on Shared/findcandidatesforexplore.sql with these additions:
  1. Adds 'part2' column (Yes/No) — derived from whether the bucket
     contains '-part2' suffix. This is the ground truth for testing.
  2. Number of CCDs per source is a parameter at the top (change SAMPLES_PER_AA).
  3. Pulls from BOTH general and Part 2 buckets so we get both populations.
  4. Output matches the unified CSV format used by the 42 CFR pipeline:
     bucket, key, qe, assigning_authority, part2

USAGE:
  1. Set SAMPLES_PER_AA below to how many CCDs you want per source
  2. Set the date window to your desired range
  3. Run in Athena
  4. Export as CSV → put in 42CFRQualityCheck/05-Candidates/ as PROD candidate file

OUTPUT COLUMNS: bucket, key, qe, assigning_authority, part2
  - These match what DEV produces via make_dev_candidates_42cfr.py
  - Feed this CSV directly to the pipeline (run_pipeline.py in PROD mode)
*/


-- ============================================================================
-- PARAMETER: How many CCDs to sample per assigning authority
-- Change this value to increase/decrease sample size per source
-- ============================================================================
-- WHERE rn <= 20    ← look for this line below and change the number


WITH ranked AS (
    SELECT
        -- Derive assigning authority from S3 key
        trim(
            CASE
                WHEN lower(split_part(i.key, '/', 1)) IN ('processed', 'error', 'backload')
                THEN split_part(i.key, '/', 2)
                ELSE split_part(i.key, '/', 1)
            END
        ) AS assigning_authority,

        -- Derive QE from bucket name (strip prefix and -part2 suffix)
        regexp_replace(
            regexp_replace(i.bucket, '^nyec-pdr-prod-', ''),
            '-part2$',
            ''
        ) AS qe,

        -- Part 2 indicator: Yes if bucket ends with -part2, No otherwise
        CASE
            WHEN i.bucket LIKE '%-part2' THEN 'Yes'
            ELSE 'No'
        END AS part2,

        i.bucket,
        i.key,
        i.size,
        i.last_modified_date,

        -- Random sample within each AA
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
        -- ================================================================
        -- DATE WINDOW: Adjust these dates for your run
        -- ================================================================
        i.dt IN (
            '2026-08-20-01-00',
            '2026-08-21-01-00',
            '2026-08-22-01-00',
            '2026-08-23-01-00',
            '2026-08-24-01-00',
            '2026-08-25-01-00',
            '2026-08-26-01-00',
            '2026-08-27-01-00'
        )
        AND i.last_modified_date >= timestamp '2026-08-18 00:00:00'
        AND i.last_modified_date <  timestamp '2026-08-28 00:00:00'

        -- Include BOTH general and Part 2 buckets
        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false

        -- CCD only (exclude TRN)
        AND regexp_like(lower(i.key), '(^|/)ccd(/|$)')
)

SELECT
    bucket,
    key,
    qe,
    assigning_authority,
    part2
FROM ranked
-- ============================================================================
-- SAMPLES_PER_AA: Change this number to control how many CCDs per source
-- ============================================================================
WHERE rn <= 20
ORDER BY part2 DESC, assigning_authority
