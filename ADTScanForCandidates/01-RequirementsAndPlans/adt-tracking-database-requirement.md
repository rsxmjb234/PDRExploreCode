# Requirement: Capture Data About Every ADT for a Tracking Database

## Why

Every ADT file is already downloaded and parsed into memory during the scan
(to check for known AA|MRN matches). Since that work is already being done,
we should also capture a record describing each ADT and make it available for
a tracking database — regardless of whether that file matched a known
candidate.

This does not need to be perfect. The goal is: capture what we can, in a
structured way, so we have *something* to load into a tracking database,
rather than nothing. We can refine the fields captured over time.

## Requirement

For **every ADT file successfully parsed** (whether or not it matched a known
AA|MRN pair), write one tracking record capturing what we found in that file.

- This applies to every file that passes download + parse, not just matches.
  (Files that fail download/parse still go to the errors log per the main
  requirements; they do not get a tracking record for now.)
- Output format: a flat CSV / NDJSON file (`06-Results/Output/{DEV|PROD}/`),
  same restart-safe and flush-every-50 rules as the rest of the scan — this is
  not a separate pass, it is captured in the same pass that already reads
  each file.
- This is a new, distinct output alongside candidate coverage (Output A) and
  match detail (Output B) from the main requirements — call it **Output D:
  ADT tracking records**.

### What we capture (interim schema — v1)

**Final schema to follow.** Until we have it, capture the minimum useful
fields so the pipe is proven end-to-end: **date/time, Assigning Authority,
MRN.** This does not need to be perfect — it's something, versus nothing,
and it slots into a real schema later with minimal rework.

One tracking row per **patient identifier (PID-3) found**, in every
successfully parsed ADT file — not just files that matched a known candidate:

- `adt_date_time` — the message timestamp (MSH-7) from the ADT that carried
  this identifier
- `assigning_authority` — from PID-3 component 4 (normalized the same way as
  the rest of the scan)
- `mrn` — from PID-3 component 1 (normalized the same way as the rest of the
  scan)

A file with multiple PID-3 identifiers (or multiple messages in one file)
produces multiple tracking rows. No S3 path, message type, or match flag is
captured in v1 — those can be added once the real schema defines whether/how
they're needed.

### Design note: keep this decoupled from the final schema

Because the destination schema is not final, implement this as its own
module (e.g. `capture_adt_record.py`) with a single function that takes the
already-parsed ADT data and returns a flat dict. When the real schema
arrives, only that function's output mapping needs to change — the
scan/restart/parallelism logic is untouched.

### Loading into the actual tracking database

Out of scope for this requirement: how the CSV/NDJSON output gets loaded into
the tracking database (separate load step, Athena, or direct DB load) is a
follow-up decision once the schema is confirmed. This requirement only
covers *capturing* the data during the scan.

## Open Item

**Final schema pending** — user will provide the target tracking-database
schema. The v1 fields above (date/time, assigning authority, MRN) are a
placeholder we can start capturing immediately. Once the real schema
arrives, update this document with the final column list and adjust
`capture_adt_record.py`'s output mapping — the scan/restart/parallelism logic
does not change.
