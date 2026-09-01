# Plan: TRN Message Mix — % Discharge by Facility
# where to find the 'explore' index card on this: https://main.dh6928p62r0tp.amplifyapp.com/explore/trn-message-mix.html

## Goal

For the TRN (HL7v2 transaction) data flowing into PDR, characterize the
message mix by facility. Specifically: for each source, what percentage of
its TRN messages are discharge messages versus everything else?

Terminology note: "TRN" here is PDR's label for the raw HL7v2 transactions
feed a source sends (as opposed to the "CCD" document feed) — it is NOT an
HL7 message type. In HL7v2, admit/discharge/transfer events are the **ADT**
message family, and discharge specifically is trigger event **A03**
(carried in MSH-9). Those ADT messages are delivered *inside* the TRN feed,
alongside other message types (results/ORU, document/MDM, scheduling, etc.).

So this exploration samples a facility's TRN-feed messages, reads the HL7
message type in MSH-9, classifies each as "discharge" (ADT^A03) vs "other",
and computes the discharge percentage per source.

## End in Mind

A single HTML report with one row per source:

| QE | Assigning Authority | Sample Size | % Discharge |

you can then add other categories if they occur frequently

Behavior:
- **Filterable by QE** (dropdown / filter control at the top).
- **Sorted by % Discharge, highest to lowest** by default.

That table is the deliverable. Nothing more (no event-ordering, no letters,
no per-message report).


## What Counts as "Discharge"

TRN files are HL7v2 pipe-delimited messages. The first line is the MSH
(Message Header) segment, and the message type is in **MSH-9**:

```
MSH|^~\&|SendingApp|SendingFacility|RecvApp|RecvFacility|20260731143022||ADT^A03^ADT_A03|MSGID|P|2.5.1
                                                                          [MSH-9 msg type]
```

Classification rule (kept deliberately simple):
- **Discharge** = MSH-9 indicates a discharge. Primarily `ADT^A03`
  (discharge / end visit). Also count discharge-document messages when the
  message type / document type clearly indicates a discharge summary
  (e.g., MDM with a discharge-summary document type, LOINC 18842-5).
- **Other** = every other MSH-9 (admit A01, transfer A02, register A04,
  update A08, results ORU, scheduling, financial, etc.).

The exact set of "discharge" MSH-9 values lives in `run_pipeline_config.py`
as a simple list so it is easy to tune.


## Metric (the only one)

Per source (assigning authority):

```
sample_size    = count of TRN messages sampled for this source
discharge_count = count where message is classified as discharge
pct_discharge  = discharge_count / sample_size
```

Output columns: `qe`, `assigning_authority`, `sample_size`, `pct_discharge`.


## Reference Architecture (same as 42CFRQualityCheck / FindEHR)

```
[Athena SQL]  ->  [Candidate CSV]  ->  [Python Scorer]  ->  [Per-msg JSON]  ->  [Aggregate]  ->  [HTML report]
     |                                       |                                      |
     | TRN candidates (data_type=TRN)        | Download TRN from S3                  | Group by QE|AA
     | sampled per assigning authority       | Parse MSH-9, classify disch/other    | Compute % discharge
     |                                       | Write 1 flat JSON per message         | Sort desc
```

Same conventions as the other codebases:
- DEV/PROD profile switch at the top of `run_pipeline.py`
- Candidate CSV input (bucket, key, qe, assigning_authority)
- Restart-safe (never re-score a message already scored)
- Flush every 200 records
- `max_files` limit
- Flat, Athena-friendly JSON output
- Reuse the HL7v2 MSH parsing already proven in
  `FindEHR/03-SupportingCode/findandsaveEHRfromCCD-EntireTRN.py`

Note on the source identifier: the FindEHR TRN work extracts MSH-3 (Sending
Application) and MSH-4 (Sending Facility). We key the mix on the assigning
authority from the candidate CSV (consistent with the other projects); MSH-4
Sending Facility is captured as a supporting field for context.


## What We Extract Per TRN Message

Flat JSON, one record per message:
- `qe` — from candidate CSV
- `assigning_authority` — from candidate CSV (the grouping key)
- `bucket`, `key`, `path`
- `message_type` — full MSH-9 value
- `is_discharge` — boolean (the classification)
- `sending_facility` — MSH-4 (context only)
- `error` — parse/download error if any

No patient-identifiable content is retained.


## Aggregation

`aggregate_trn.py` reads all scored JSONs, groups by
`assigning_authority` (with `qe` carried along), and computes per source:
- `sample_size`
- `discharge_count`
- `pct_discharge`

Writes an aggregate CSV with columns: `qe, assigning_authority, sample_size,
discharge_count, pct_discharge`.


## Output — HTML Report

Single self-contained HTML file (inline CSS + a little JS, no external deps):
- One row per source: **QE | Assigning Authority | Sample Size | % Discharge**
- **Filter by QE** — a dropdown at the top that shows only rows for the
  selected QE (or "All").
- **Default sort: % Discharge descending** (highest first). Column headers
  clickable to re-sort is a nice-to-have, not required.
- Small header summary: total sources, total messages sampled, overall %
  discharge.

Same visual style family as the 42 CFR report (warm palette, clean table).


## Modular Code Layout (mirrors 42CFRQualityCheck)

```
03-SupportingCode/
  run_pipeline_config.py   # DEV/PROD profiles; DISCHARGE_MSH9 list
  run_pipeline.py          # orchestrator (score -> aggregate -> report)
  parse_trn.py             # HL7v2 MSH parsing (reuse FindEHR logic)
  classify_message.py      # MSH-9 -> is_discharge
  score_message.py         # per-message worker: download, parse, classify, emit JSON
  aggregate_trn.py         # group by QE|AA, compute % discharge
  generate_report.py       # single HTML report (filter by QE, sort desc)
  cleanup_run.py           # wipe a DEV/PROD run's results
```


## Candidate Selection (SQL)

**Requirement: the S3/Athena candidate query shall select TRN messages only.**

TRN messages are identified by `/trn/` in the S3 key (confirmed by the sample
path `s3://nyec-pdr-prod-bronx/processed/BAHN/trn/2026/Jul/11/00/bronx_BAHN_..._9578.hl7`).
This is the same key-pattern approach PDR already uses to tell data types
apart in the Athena inventory.

Base the query on the existing examples in the repo:
- `Shared/findcandidatesforexplore.sql` — the per-source sampling candidate
  query (currently filters CCD via `regexp_like(lower(i.key), '(^|/)ccd(/|$)')`).
- `Shared/findallccdcontributors.sql` — already classifies TRN with
  `regexp_like(lower(i.key), '(^|/)trn(/|$)')` and labels it `data_type = 'TRN'`.

For this project, `02-SupportingSQL/find_trn_candidates.sql` shall:
- Filter to TRN only: replace the CCD filter with
  `regexp_like(lower(i.key), '(^|/)trn(/|$)')`.
- Derive `assigning_authority` and `qe` the same way the shared query does
  (from the key path / bucket).
- Sample N messages per assigning authority (N is a clearly-marked parameter,
  same pattern as the other projects — e.g. `WHERE rn <= 20`).
- Emit the standard candidate columns: `bucket, key, qe, assigning_authority`.

Note on access: this project runs against DEV only from here (the developer
profile has no PROD bucket access). Selecting the actual PROD TRN candidates
is done by running this Athena query and exporting the CSV, exactly as the
42 CFR and FindEHR projects do — not by listing PROD buckets from code.


## DEV vs PROD

- **DEV:** point at a learning-bucket TRN sample to validate MSH-9 parsing and
  the discharge classification before trusting PROD numbers.
- **PROD:** Athena-produced candidate CSV across the real TRN feed.

Same restart-safe, flush-every-200, max_files conventions.


## Build Order (TODO)

1. [ ] `run_pipeline_config.py` — DEV/PROD profiles + `DISCHARGE_MSH9` list.
2. [ ] `parse_trn.py` — MSH split + MSH-3/4/9 extraction (reuse FindEHR TRN).
3. [ ] `classify_message.py` — `is_discharge` from MSH-9.
4. [ ] `score_message.py` — per-message flat JSON record.
5. [ ] `aggregate_trn.py` — group by QE|AA, compute sample_size + % discharge.
6. [ ] `generate_report.py` — HTML table, filter by QE, sort % discharge desc.
7. [ ] `run_pipeline.py` — orchestrator, DEV/PROD, restart-safe.
8. [ ] `cleanup_run.py`.
9. [ ] SQL candidate query.
10. [ ] DEV validation run, then PROD.


## Open Questions to Resolve Before Coding

- Confirm which MSH-9 values PDR uses for discharge (is it always `ADT^A03`,
  or do some sources send discharge summaries as MDM documents?). This sets
  the `DISCHARGE_MSH9` list.
- Confirm the assigning authority is available on the candidate CSV for TRN
  data (the FindEHR TRN work should confirm this).
