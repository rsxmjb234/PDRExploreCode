# Requirements: ADT Scan for Known AA|MRN Combinations

## Goal

We have a list of ~35,000 known **Assigning Authority | MRN** combinations
(patients of interest). We have millions of **ADT** (HL7v2) message files in
an S3 bucket. We want code that reads every ADT file and determines whether
any of our known AA|MRN combinations appears in that file.

The output is, for each match, a record tying a known AA|MRN to the ADT file
(and enough context to find it again). Speed is not a concern — correctness
and completeness are. This is a long, unattended batch scan.

S3 bucket: `encounter-gateway-incoming-prod` (region us-east-1)


## Inputs

### 1. The lookup list — known AA|MRN combinations
- ~35,000 rows, each an Assigning Authority + MRN pair.
- Provided as a CSV in `05-Candidates/` (exact filename set in config).
- Assumed columns: `assigning_authority`, `mrn`.
  (If the source file uses different headers, config maps them.)
- Loaded once into memory as a fast lookup set of normalized
  `(assigning_authority, mrn)` keys. 35k pairs is small — fits in memory.

### 2. The ADT files — the haystack
- HL7v2 ADT messages stored as files in
  `s3://encounter-gateway-incoming-prod/`.
- Millions of files. Each file is read in full and inspected.
- In HL7v2, the patient identifier lives in **PID-3** (Patient Identifier
  List), which carries the ID value and its assigning authority. A file may
  contain one or more messages / PID segments.


## What "AA|MRN is in that ADT" Means

A file is a MATCH for a known pair when the ADT's patient identifier matches
BOTH the MRN value AND its assigning authority for one of our 35,000 pairs.

Matching detail (to confirm against a real sample before finalizing):
- Parse each PID-3 in the file. PID-3 is `ID^checkdigit^scheme^assigning_authority^id_type...`
  — the ID value is component 1, the assigning authority is component 4.
- Normalize both sides (trim, upper-case, strip leading zeros on MRN if
  needed) before comparing, so formatting differences don't cause misses.
- A file matches if any of its PID-3 identifiers equals one of our known
  (assigning_authority, mrn) pairs.

Open question to resolve on a real sample: how the assigning authority is
represented in these files (a name, an OID, a QE code) and whether it lines
up with how our 35k list expresses AA. The matching/normalization rules will
be finalized once we see a real ADT from this bucket.


## Core Processing Requirements

### Read every file
- Enumerate all objects in the bucket (paginated listing) and process each.
- Download each file, parse it as HL7v2, extract every PID-3 identifier.
- Compare against the in-memory lookup set; record any matches.

### Restart-safe / crash recovery (our standard pattern)
This will run for a long time and WILL be interrupted (network, throttling,
machine sleep). It must resume cleanly:
- Maintain a **processed-files ledger** on disk (append-only). Every file that
  has been fully processed has its S3 key/path written to the ledger.
- On startup, load the ledger into memory and **skip any file already in it**.
- Flush progress to disk frequently (every N files, e.g. 200) so a crash
  loses at most N files of work, never more.
- A file is only marked processed AFTER its result has been written — so an
  interrupted file is re-processed next run, never silently skipped.

### Never process the same file twice
- The processed-files ledger is the single source of truth. A file whose key
  is in the ledger is not downloaded or parsed again.
- Re-running the tool resumes where it left off automatically.
- To force a full re-scan from scratch: delete the ledger (and outputs).

### Correctness over speed
- No parallelism required. A simple sequential loop is fine.
- Prefer completeness and clear logging over throughput.
- Every file gets one of three outcomes, all recorded: MATCH(es) found,
  no match, or error (download/parse failure). Errored files are logged and
  left OUT of the processed ledger so they are retried on the next run.


## Outputs

### Output A — Matches (the deliverable)
A CSV (and/or NDJSON for Athena) with one row per match:
- `assigning_authority`, `mrn` — the known pair that matched
- `s3_key`, `bucket`, `path` — where it was found
- `message_type` (MSH-9), `message_time` (MSH-7) — light context
- `matched_pid3_raw` — the PID-3 value that matched (for verification)

If a single file matches multiple known pairs, emit one row per matched pair.

### Output B — Run summary / progress log
- Files processed, files skipped (already done), matches found, errors.
- Written to `06-Results/Output/{DEV|PROD}/`.
- The processed-files ledger lives here too (e.g. `processed_files.log`).


## Conventions (same as our other projects)

- DEV/PROD profile switch at the top of the runner
  (`ACTIVE_PROFILE = "DEV"` / `"PROD"`), with AWS profile, bucket, input CSV,
  output dir, and `max_files` per profile.
- Restart-safe, flush-every-N, `max_files` cap for bounded test runs.
- Flat, Athena-friendly output (no nested JSON, pipe-delimited multi-values).
- Modular: separate the HL7v2 parsing (reuse the MSH/PID approach from
  `FindEHR/03-SupportingCode/findandsaveEHRfromCCD-EntireTRN.py`) from the
  match logic and the S3/ledger driver.
- Reference architecture: `[bucket listing] -> [per-file scan] -> [match log +
  ledger]`. No Athena candidate CSV needed here since we scan the whole
  bucket, but the lookup list is provided as a CSV input.


## Access Note

- The developer profile (`student1`) has DEV access only. Scanning the real
  `encounter-gateway-incoming-prod` bucket requires the PROD-capable AWS
  profile (`default` or an appropriately-permissioned role), set in the PROD
  profile block. DEV testing runs against a small sample bucket/prefix we can
  read.


## Assumptions To Confirm

1. The lookup CSV has (or can be mapped to) `assigning_authority` + `mrn`.
2. ADT files are HL7v2 with the patient ID in PID-3; the assigning authority
   in PID-3 component 4 aligns with how our list expresses AA.
3. MRN normalization rules (leading zeros, case) — finalize on a real sample.
4. One S3 object may hold one message (typical) or a batch; the parser handles
   multiple PID segments per file just in case.
5. "Read every file" means every current object in the bucket; delete markers
   / old versions are ignored.


## Build Order (TODO — after requirements approved)

1. [ ] `config.py` — DEV/PROD profiles, bucket, lookup CSV path, output/ledger
       paths, `max_files`, flush interval, column mappings.
2. [ ] `load_lookup.py` — read the 35k AA|MRN CSV into a normalized set.
3. [ ] `parse_adt.py` — HL7v2 parse: MSH + all PID-3 identifiers (reuse
       FindEHR TRN parsing).
4. [ ] `scan_bucket.py` — list bucket, per-file: skip-if-in-ledger, download,
       parse, match, write matches, append to ledger, flush every N.
5. [ ] `cleanup_run.py` — wipe a run's outputs + ledger for a fresh scan.
6. [ ] DEV validation on a small sample, then PROD full scan.
