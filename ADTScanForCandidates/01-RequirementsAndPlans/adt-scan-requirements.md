# Requirements: ADT Scan for Known AA|MRN Combinations

## Top-Line Goal (the business question)

We have ~35,000 **Assigning Authority | MRN** combinations that represent
patients who, over a period of months, were **NOT added to the Opt-Out
database**. The question we are answering:

> **Of the MRNs that were NOT added to the Opt-Out database, do we nonetheless
> see those same MRNs appearing in the ADT traffic?**

In other words: are there people who should have been considered for Opt-Out
(they show up in the encounter/ADT feed) but who are missing from the Opt-Out
database? Each of our 35,000 AA|MRN pairs that turns up in the ADT feed is a
person whose data is flowing even though they were not added to Opt-Out.

The **primary deliverable is per-candidate**: for each of the ~35,000 known
AA|MRN pairs, was it seen anywhere in the ADT feed (yes/no), and if yes, where.
This is a list-centric coverage question, not a per-file report.

## How We Answer It

We have millions of **ADT** (HL7v2) message files in an S3 bucket. We read
every ADT file, extract the patient identifier(s) (PID-3 = MRN + assigning
authority), and check each against our 35,000 known pairs. Every pair that
matches is flagged as "seen in ADT feed."

Speed is not a concern — correctness and completeness are. This is a long,
unattended batch scan.

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

### Date cutoff — exclude data before 1/1/2026
We have good log/data quality only from **January 1, 2026 forward**. The scan
shall support a configurable cutoff date and **exclude any ADT file dated
before it** from processing entirely (not downloaded, not counted against
`max_files`, not written to the ledger).
- Config value: `MIN_FILE_DATE` (default `2026-01-01`).
- Applied using the S3 object's `LastModified` timestamp during the bucket
  listing phase, BEFORE a file is queued for download — so excluded files
  cost nothing (no GET, no parse).
- Files at/after the cutoff are processed normally; files strictly before it
  are skipped and tallied separately in the run summary
  (`skipped_before_cutoff` count) so we know how much of the bucket was
  excluded and why.
- This is a listing-time filter, independent of parallelism/ledger logic —
  a file excluded by date is never considered "unprocessed work" and never
  appears in the ledger, matches, or coverage output.

### Read every file (at/after the cutoff date)
- Enumerate all objects in the bucket (paginated listing) and process each
  whose `LastModified` is on/after `MIN_FILE_DATE`.
- Download each file, parse it as HL7v2, extract every PID-3 identifier.
- Compare against the in-memory lookup set; record any matches.

### Restart-safe / crash recovery (our standard pattern)
This will run for a long time and WILL be interrupted (network, throttling,
machine sleep). It must resume cleanly:
- Maintain a **processed-files ledger** on disk (append-only). Every file that
  has been fully processed has its S3 key/path written to the ledger.
- On startup, load the ledger into memory and **skip any file already in it**.
- A file is only marked processed AFTER its result has been written — so an
  interrupted file is re-processed next run, never silently skipped.

### Flush to disk every 50 records — not just "periodically" (hard requirement)
We previously lost hours of work because a run crashed before output was ever
written to disk — the flush interval was too coarse, or buffering meant
nothing hit disk until a clean shutdown that never happened. To prevent that
from happening again:
- **The matches CSV, the candidate-coverage CSV, and the processed-files
  ledger must all be flushed to disk at least every 50 processed files.**
  This applies whether running sequentially or with parallel workers.
- "Flushed" means an actual write + `flush()` (and ideally `os.fsync()`) to
  the underlying file — not just appended to an in-memory buffer that waits
  for a larger batch or a clean exit.
- This is a MAXIMUM interval, not a target: writing after every single file is
  also acceptable. 50 is the largest acceptable gap between a file being
  processed and its result being safely on disk.
- Do not rely on "flush on exit" or "flush every N=200/500/1000" as the only
  save point — if the process is killed (crash, power loss, OOM, forced
  termination), everything since the last flush is exactly what gets lost, so
  that gap must be small. 50 records is small enough that losing a batch costs
  minutes, not hours.
- This does not need to be perfect (e.g. a partially-written last line on a
  true mid-write crash is an acceptable, rare edge case) — the goal is "never
  again lose hours of processing to a crash," not zero data loss in every
  conceivable failure mode.

### Never process the same file twice
- The processed-files ledger is the single source of truth. A file whose key
  is in the ledger is not downloaded or parsed again.
- Re-running the tool resumes where it left off automatically.
- To force a full re-scan from scratch: delete the ledger (and outputs).

### Correctness over speed
- Prefer completeness and clear logging over throughput.
- Optional parallelism is supported (see `parallelism-requirement.md`) to make
  a large laptop run finish in days instead of weeks. Default is sequential.
- Every file gets one of three outcomes, all recorded: MATCH(es) found,
  no match, or error (download/parse failure). Errored files are logged and
  left OUT of the processed ledger so they are retried on the next run.

### No two workers ever process the same file (race avoidance)
Workers must never "compete" for a file. We prevent the race by design:
- A **single producer** streams the S3 listing and hands each key out
  **exactly once** via a thread-safe work queue / executor. Workers are
  *assigned* files; they never pick their own, so two threads can't grab the
  same ADT.
- The producer applies the ledger check **before** enqueueing, so a
  already-processed file is never dispatched again on a restart.
- The only shared mutable state is the output files (candidate coverage, match
  detail, ledger, errors). All writes go through a **single lock / single
  writer** so concurrent workers cannot interleave or corrupt lines.
- Match tallying per candidate is kept in a thread-safe structure (guarded
  counter/dict) so `times_seen` is accurate under concurrency.


## Outputs

We do **NOT** write a CSV per ADT file. With ~50M files that would be
unusable, and it is not what the business question needs. Instead:

### Output A — Candidate coverage (the PRIMARY deliverable)
One row per **known AA|MRN pair** (all ~35,000), answering "was this pair seen
in the ADT feed?":
- `assigning_authority`, `mrn` — the known pair
- `seen_in_adt` — yes / no
- `times_seen` — how many ADT files it appeared in (0 if not seen)
- `first_s3_key` — an example ADT file where it was found (blank if not seen)
- `first_message_type`, `first_message_time` — light context from that example

This is the file that answers the top-line question: filter to
`seen_in_adt = yes` to get the MRNs that were NOT added to Opt-Out but ARE
present in the ADT traffic.

### Output B — Match detail (supporting evidence)
One row per (matched pair × ADT file), for anyone who needs to trace a hit
back to specific files:
- `assigning_authority`, `mrn` — the matched pair
- `s3_key`, `bucket`, `path` — where it was found
- `message_type` (MSH-9), `message_time` (MSH-7)
- `matched_pid3_raw` — the PID-3 value that matched (for verification)

A file matching multiple known pairs produces one detail row per matched pair.
(Output A is derived by rolling Output B up per candidate; a candidate never
seen simply has `seen_in_adt = no`.)

### Output C — Run summary / progress log
- Files processed, files skipped (already done), total matches, distinct
  candidates seen, errors.
- Written to `06-Results/Output/{DEV|PROD}/`.
- The processed-files ledger lives here too (e.g. `processed_files.log`).

Note on the ledger vs. outputs: the **ledger records every file processed**
(match or not) so we know coverage and never re-read a file. The **match
detail (Output B) only gets a row when a known pair is found** — we do not
write a "no match" row per file.


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
