# Core Plan: CCD Coding Quality Evaluation

## Purpose

Answer the SHIN-NY policy question on QE value-add versus raw pass-through by
measuring coding quality at source and QE levels across all 14 CCD segments.


## Architecture (mirrors findandsaveEHRfromCCD-EntireCCD.py pattern)

```
[Candidate CSV]  -->  [Batch Scorer]  -->  [1 JSON per CCD]  -->  [Athena]
     |                      |                     |
     |   DEV: make_dev_candidates_csv.py          |   DEV: local folder
     |   PROD: findcandidatesforexplore.sql       |   PROD: S3 analytics bucket
     |                      |
     |   Downloads full CCD from S3
     |   Scores 14 segments using segment_mapping.py
     |   Writes 1 JSON result per CCD processed
     |   Restart: skips files where JSON already exists
```

### Key Design Decisions

1. **Input**: Candidate CSV with columns: `assigning_authority, qe, bucket, key, size, last_modified`
   - DEV: produced by `make_dev_candidates_csv.py` (lists S3 test data folder)
   - PROD: produced by `findcandidatesforexplore.sql` (Athena export)

2. **Output**: One JSON file per CCD processed (not a single big CSV)
   - Enables Athena queries over partitioned JSON output
   - Each JSON is self-contained with all metadata
   - DEV: written to local `scored_output/` folder
   - PROD: written to `s3://<analytics-bucket>/ccd-coding-quality/...`

3. **Restart/Idempotency**: Before processing a CCD, check if its output JSON
   already exists. If yes, skip it. This means:
   - Re-running the script picks up where it left off
   - To reprocess: delete the output JSON
   - No flush-every-N logic needed (each file is written immediately)

4. **DEV/PROD profile switch**: Single `ACTIVE_PROFILE` variable at top of script.
   Same core scoring logic in both; only config differs.


## Scope

- Evaluate coding quality for CCDs from approximately 4,500 sources.
- Report at source level and QE level.
- Cover all 14 target segments using fixed segment keys (including demographics).
- Produce one JSON result per CCD.
- Prioritize readable, quickly created analysis code over production-grade repeatability.

Out of scope:

- DEV synthetic test-data creation logic (see dev-test-data plan).
- Payment policy implementation.
- Production ETL hardening and dashboard implementation.


## Required Segment Coverage (14)

1. allergies
2. assessment
3. care_plan
4. chief_complaint
5. demographics
6. encounters
7. functional_status
8. immunizations
9. labs_results
10. medications
11. problems
12. procedures
13. social_history
14. vitals


## Segment Scoring Model

Per coded element within a segment:

- **Standard**: codeSystem OID is in the segment's accepted national list
  (or a translation element carries a national code)
- **Local**: codeSystem OID is present but NOT in the national list
- **Missing**: no @code or @codeSystem, or nullFlavor present
- **Section Absent**: the entire CDA section does not exist in the CCD

The distinction between Missing and Section Absent:

- Missing = source attempted to send data but didn't code it properly (fixable)
- Section Absent = source never included this section (may be legitimate scope)

Section Absent entries are excluded from the scoring denominator.


## Decision Framework (Tiers)

- Tier A: standard_pct >= 90 and missing_pct <= 5. Policy: raw pass-through.
- Tier B: standard_pct 75-89 or missing_pct 6-10. Policy: targeted improvements.
- Tier C: standard_pct 60-74 or missing_pct 11-20. Policy: QE normalization justified.
- Tier D: standard_pct < 60 or missing_pct > 20. Policy: QE transformation strongly justified.


## JSON Output Schema (per CCD)

```json
{
  "run_date": "2026-07-08",
  "source": {
    "assigning_authority": "STRONG MEMORIAL",
    "qe": "rochester",
    "bucket": "nyec-pdr-prod-rochester",
    "key": "STRONG MEMORIAL/ccd/2026/Jul/21/...",
    "path": "s3://nyec-pdr-prod-rochester/STRONG MEMORIAL/ccd/..."
  },
  "processing": {
    "processing_time_ms": 342,
    "file_size_bytes": 456000
  },
  "summary": {
    "total_elements": 580,
    "standard_count": 510,
    "local_count": 45,
    "missing_count": 25,
    "sections_absent": 2
  },
  "domain_counts": {
    "allergies":        { "total": 12, "standard": 10, "local": 1, "missing": 1, "section_absent": false },
    "assessment":       { "total": 0,  "standard": 0,  "local": 0, "missing": 0, "section_absent": true },
    "care_plan":        { "total": 8,  "standard": 7,  "local": 1, "missing": 0, "section_absent": false },
    "...": "..."
  },
  "local_oid_counts": {
    "1.2.3.4.5.facility": 30,
    "2.16.840.1.113883.3.xxx": 15
  }
}
```


## Output Path Convention

DEV:
```
DataCodingQualityStandards/scored_output/<filename>_scored.json
```

PROD:
```
s3://<analytics-bucket>/ccd-coding-quality/run_date=YYYY-MM-DD/qe=<qe>/assigning_authority=<aa>/<filename>_scored.json
```


## DEV Validation Handshake (Required)

1. `generate_test_cases.py` creates mutated CCDs + expected-outcome JSONs
2. `score_ccd_coding_quality.py` scores those same CCDs
3. `validate_test_cases.py` confirms scored == expected (15/15 pass)
4. Only after validation passes can PROD runs proceed

Status: VALIDATED (15/15 pass)


## Candidate List Generation

DEV:
- `make_dev_candidates_csv.py` lists CCDs from `s3://nyec.ccda.learning/TestDataForDeterminingLevelOfCodeSetQuality/`
- Outputs: `DEV-CodingQuality-Candidates.csv`
- Columns: `assigning_authority, qe, bucket, key, size, last_modified`

PROD:
- `findcandidatesforexplore.sql` run in Athena
- Export to CSV with same columns plus `bucket`
- Feed CSV to the batch scorer


## Batch Scorer Architecture

Same pattern as `findandsaveEHRfromCCD-EntireCCD.py`:

1. Read candidate CSV (all rows, filter already-processed after)
2. Check which output JSONs already exist (restart support)
3. Connect to S3
4. For each unprocessed candidate:
   a. Download full CCD from S3
   b. Parse with ElementTree
   c. Score all 14 segments using `segment_mapping.py`
   d. Write result JSON immediately (no batching needed)
   e. Print progress
5. Print summary with timing

DEV/PROD difference: only the profile config (bucket, CSV path, output location).


## Suggested Run Modes

- Quick validation: max_files = 5-10
- Operational baseline: max_files = 20
- Extended study: max_files = 50+ (restart picks up where you left off)


## Athena Layer

- External table over JSON output (PROD)
- Keep stable key names in domain_counts (14 segments)
- Query per source, per QE, per segment
- Report section_absent separately from coding quality


## Deliverables

- [x] segment_mapping.py (14 segments, OID tables)
- [x] generate_test_cases.py (DEV test data generator)
- [x] score_ccd_coding_quality.py (core scorer, validated)
- [x] validate_test_cases.py (promotion gate)
- [x] regenerate_expected_from_scorer.py (utility)
- [x] make_dev_candidates_csv.py (DEV candidate list builder)
- [ ] score_ccd_coding_quality_batch.py (batch runner with CSV input, JSON-per-file output, restart)
- [ ] Athena table definition for scored JSON output
