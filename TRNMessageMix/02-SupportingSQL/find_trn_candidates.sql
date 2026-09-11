/*
find_trn_candidates.sql — Sample TRN messages per assigning authority
=====================================================================

Purpose:
  Build the candidate CSV for the TRN Message Mix exploration. Selects TRN
  messages ONLY (identified by "/trn/" in the S3 key) and samples up to
  100 messages per assigning authority, from data submitted 10-20 days ago.

Based on Shared/findcandidatesforexplore.sql and the TRN classification
pattern already used in Shared/findallccdcontributors.sql:
    regexp_like(lower(i.key), '(^|/)trn(/|$)')

Output columns: bucket, key, qe, assigning_authority
  - Same shape the pipeline expects (run_pipeline.py candidate loader).
  - Export from Athena as CSV -> place in 05-Candidates/.

Tunable parameters (marked below):
  - SAMPLES_PER_AA:  WHERE rn <= 100
  - DATE WINDOW:     submitted > 10 days ago AND < 20 days ago
*/


WITH ranked AS (
    SELECT
        -- Assigning authority: the path segment just before "/trn/".
        -- Key shapes handled:
        --   processed/<AA>/trn/...   error/<AA>/trn/...   backload/<AA>/trn/...
        --   <AA>/trn/...
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

        -- Random sample within each assigning authority.
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
        -- DATE WINDOW: submitted more than 10 days ago and less than 20.
        -- last_modified_date is when PDR received/wrote the object.
        -- ================================================================
        i.last_modified_date <  current_timestamp - interval '10' day
        AND i.last_modified_date >= current_timestamp - interval '20' day

        -- All production QE buckets (primary and -part2).
        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false

        -- TRN messages ONLY (this is the whole point of this query).
        AND regexp_like(lower(i.key), '(^|/)trn(/|$)')
)

SELECT
    bucket,
    key,
    qe,
    assigning_authority
FROM ranked
-- ============================================================================
-- SAMPLES_PER_AA: up to 100 TRN messages per assigning authority.
-- ============================================================================
WHERE rn <= 100
ORDER BY qe, assigning_authority
