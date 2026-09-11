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

### What we capture (pending final schema)

**The exact column list / schema will be provided separately (schema TBD —
to follow).** Until that's in hand, capture at least the fields we already
have on hand from parsing, so the pipe is proven end-to-end and only the
column set needs to change once the schema arrives:

- `s3_key`, `bucket`, `path` — where the file came from
- `message_type` (MSH-9), `message_time` (MSH-7)
- `sending_application` / `sending_facility` (MSH-3 / MSH-4) if present
- `patient_identifiers` — every PID-3 found in the file (id + assigning
  authority), flattened to a pipe-delimited string since we don't yet know
  the target schema's shape
- `matched_known_candidate` — yes/no (did this file match one of our 35k
  AA|MRN pairs — cheap to include since we already compute it)
- `file_last_modified` — the S3 object's LastModified date, for reference

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

**Schema pending** — user will provide the target tracking-database schema.
Once received, update this document with the final column list and adjust
`capture_adt_record.py` accordingly.
