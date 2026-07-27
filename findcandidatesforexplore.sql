/*
findcandidatesforexplore.sql — Get 10 random CCD S3 paths per assigning authority

Based on Dan's SQL from danemail.md with these changes:
  1. Include backload paths (removed the backload exclusion)
  2. Handle all path prefixes (processed/error/backload/normal) for AA derivation
  3. CCD only (removed TRN/ORU)
  4. Hardcoded to Jul 21-22

Output feeds into findandsaveEHRfromCCD-EntireCCD.py
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
        -- 10-day window: Jul 15-24, with dt partitions offset by +2 days
        i.dt IN (
            '2026-07-17-01-00',
            '2026-07-18-01-00',
            '2026-07-19-01-00',
            '2026-07-20-01-00',
            '2026-07-21-01-00',
            '2026-07-22-01-00',
            '2026-07-23-01-00',
            '2026-07-24-01-00',
            '2026-07-25-01-00',
            '2026-07-26-01-00'
        )
        AND i.last_modified_date >= timestamp '2026-07-15 00:00:00'
        AND i.last_modified_date <  timestamp '2026-07-25 00:00:00'

        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false

        -- CCD only
        AND regexp_like(lower(i.key), '(^|/)ccd(/|$)')
)

SELECT
    assigning_authority,
    qe,
    bucket,
    key,
    size,
    date_format(last_modified_date, '%Y-%m-%d %H:%i:%s') AS last_modified
FROM ranked
WHERE rn <= 5
ORDER BY assigning_authority, last_modified DESC
