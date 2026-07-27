-- Dan's SQL for finding candidate CCD files (from his email 07/27)
-- Key differences from our version:
--   - Uses i.bucket LIKE 'nyec-pdr-prod-%' (not inventory_source IN (...))
--   - Hardcodes dt = '2026-07-22-01-00'
--   - Uses explicit timestamp range for last_modified_date
--   - Includes i.bucket in the SELECT (needed for multi-bucket PROD)
--   - Gets 10 random docs per assigning authority

WITH ranked AS (
    SELECT
        CASE
            WHEN lower(i.key) LIKE 'backload/%'
                THEN split_part(i.key, '/', 2)
            ELSE split_part(i.key, '/', 1)
        END AS assigning_authority,

        regexp_replace(
            regexp_replace(i.bucket, '^nyec-pdr-prod-', ''),
            '-part2$',
            ''
        ) AS qe,

        CASE
            WHEN regexp_like(lower(i.key), '(^|/)ccd(/|$)') THEN 'CCD'
            WHEN regexp_like(lower(i.key), '(^|/)trn(/|$)') THEN 'TRN'
            WHEN regexp_like(lower(i.key), '(^|/)oru(/|$)') THEN 'ORU'
        END AS data_type,
        i.bucket,
        i.key,
        i.size,
        i.last_modified_date,

        row_number() OVER (
            PARTITION BY
                CASE
                    WHEN lower(i.key) LIKE 'backload/%'
                        THEN split_part(i.key, '/', 2)
                    ELSE split_part(i.key, '/', 1)
                END
            ORDER BY random()
        ) AS rn

    FROM pdr_inventory.pdr_inventory_prod_data_all i

    WHERE
        i.dt = '2026-07-22-01-00'
        AND i.last_modified_date >= timestamp '2026-07-21 07:12:05'
        AND i.last_modified_date <= timestamp '2026-07-22 07:12:05'

        AND i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false

        -- Exclude backlog
        AND NOT regexp_like(lower(i.key), '(^|/)backload/')

        -- Only known document types
        AND (
            regexp_like(lower(i.key), '(^|/)ccd(/|$)')
            OR regexp_like(lower(i.key), '(^|/)trn(/|$)')
            OR regexp_like(lower(i.key), '(^|/)oru(/|$)')
        )
)

SELECT
    assigning_authority,
    qe,
    data_type,
    bucket,
    key,
    size,
    date_format(
        last_modified_date,
        '%Y-%m-%d %H:%i:%s'
    ) AS last_modified
FROM ranked
WHERE rn <= 10
ORDER BY
    assigning_authority,
    data_type,
    last_modified DESC;
