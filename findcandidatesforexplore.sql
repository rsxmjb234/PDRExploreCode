/*
Expected cost/run: ~$0.50 (3-day partition scan, ~100 GB @ $5/TB)
Expected runtime: ~1-2 minutes

Goal:
- Get a RANDOM sample of up to 20 documents per assigning authority.
- Sampled from a 3-day window (not most recent or oldest — truly random).
- Only real-time data (excludes backlog).
- Random selection avoids bias from time-of-day patterns or batch loads.

How to use:
- Adjust the date range in config if needed.
- Results give you up to 20 random docs per source to inspect.
- Feed the output CSV into findandsaveEHRfromCCD.py to extract EHR signals.
*/

WITH config AS (
    SELECT
        date_add('day', -5, current_date) AS window_start,  -- << start of 3-day window
        date_add('day', -2, current_date) AS window_end,    -- << end of 3-day window (3 full days)
        2 AS inventory_snapshot_offset_days
),
params AS (
    SELECT
        c.window_start,
        c.window_end,
        CAST(c.window_start AS timestamp) AS start_ts,
        CAST(date_add('day', 1, c.window_end) AS timestamp) AS end_ts,
        -- We need to cover inventory partitions for each day in the window
        date_format(
            date_add('day', c.inventory_snapshot_offset_days, c.window_end),
            '%Y-%m-%d-01-00'
        ) AS dt_target_partition
    FROM config c
),

ranked AS (
    SELECT
        CASE
            WHEN lower(i.key) LIKE 'backload/%' THEN split_part(i.key, '/', 2)
            ELSE split_part(i.key, '/', 1)
        END AS assigning_authority,
        regexp_replace(regexp_replace(i.bucket, '^nyec-pdr-prod-', ''), '-part2$', '') AS qe,
        CASE
            WHEN regexp_like(lower(i.key), '(^|/)ccd(/|$)') THEN 'CCD'
            WHEN regexp_like(lower(i.key), '(^|/)trn(/|$)') THEN 'TRN'
            WHEN regexp_like(lower(i.key), '(^|/)oru(/|$)') THEN 'ORU'
        END AS data_type,
        i.key,
        i.size,
        i.last_modified_date,
        row_number() OVER (
            PARTITION BY
                CASE
                    WHEN lower(i.key) LIKE 'backload/%' THEN split_part(i.key, '/', 2)
                    ELSE split_part(i.key, '/', 1)
                END
            ORDER BY random()  -- << RANDOM ordering instead of time-based
        ) AS rn
    FROM pdr_inventory.pdr_inventory_prod_data_all i
    JOIN params p
        ON i.dt = p.dt_target_partition
        AND i.last_modified_date >= p.start_ts
        AND i.last_modified_date < p.end_ts
    WHERE
        i.bucket LIKE 'nyec-pdr-prod-%'
        AND i.is_latest = true
        AND coalesce(i.is_delete_marker, false) = false
        -- Exclude backlog
        AND NOT regexp_like(lower(i.key), '(^|/)backload/')
        -- Only known doc types
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
    key,
    size,
    date_format(last_modified_date, '%Y-%m-%d %H:%i:%s') AS last_modified
FROM ranked
WHERE rn <= 20
ORDER BY assigning_authority ASC, data_type ASC, last_modified DESC;
