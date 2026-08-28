# Testing Plan — 42 CFR Candidate Identification (DEV and PROD)

## Overview

We have a single test harness (`test_harness.py`) that works in both DEV
and PROD. It runs the pipeline, compares results against known ground truth,
and reports pass/fail with variance tolerance.

Both landscapes use the **same CSV format** with 5 columns:
```
bucket, key, qe, assigning_authority, part2
```

The `part2` column (Yes/No) is the ground truth — it tells us whether a
source is known to be 42 CFR or not. The test checks whether our code
correctly identifies the Yes sources and correctly ignores the No sources.


## How Ground Truth Is Established

| Landscape | How we know part2=Yes/No | Source of candidates CSV |
|-----------|--------------------------|--------------------------|
| DEV | Folder location in S3 — `42CFRStyleCCDs/` = Yes, `RawCCDs/` = No | Built fresh each run by `test_harness.py` listing S3 |
| PROD | Bucket name — `*-part2` suffix = Yes, regular bucket = No | Athena SQL (`findcandidates_42cfr.sql`) exported as CSV |


## S3 Layout — DEV

Two folders in `nyec.ccda.learning` simulate how PDR is set up:

| Folder | part2 | What it represents |
|--------|-------|-------------------|
| `42CFRStyleCCDs/` | Yes | Known 42 CFR data (300 synthetic CCDs with SUD content) |
| `RawCCDs/` | No | General population data (1,706 files, standard care) |

DEV gives us 1 distinct AA for Yes pool, 2 for No pool.

## S3 Layout — PROD

Multiple QE buckets, some with a `-part2` variant:

| Bucket Pattern | part2 | Example |
|---------------|-------|---------|
| `nyec-pdr-prod-{qe}-part2` | Yes | `nyec-pdr-prod-hixny-part2` |
| `nyec-pdr-prod-{qe}` | No | `nyec-pdr-prod-hixny` |

PROD (from Athena) gives us 131 distinct AAs for Yes, 4,802 for No,
across 95,350 total candidate rows.


## The Unified Candidates CSV

Both DEV and PROD produce the same file:

```csv
bucket,key,qe,assigning_authority,part2
nyec.ccda.learning,42CFRStyleCCDs/Abe_Stracke....xml,dev-42cfr,42cfr-dev,Yes
nyec.ccda.learning,RawCCDs/somefile.xml,dev-general,rawccd-dev,No
```

In PROD (from Athena, values are quoted but Python handles that):
```csv
"bucket","key","qe","assigning_authority","part2"
"nyec-pdr-prod-hixny-part2","backload/1255360046/ccd/...xml","hixny","1255360046","Yes"
"nyec-pdr-prod-hixny","processed/MMC/ccd/...xml","hixny","MMC","No"
```

The pipeline doesn't care which landscape produced the CSV — same 5 columns,
same processing logic.


## How to Run

### DEV
```
python test_harness.py DEV
```
This will:
1. Rebuild the candidates CSV fresh from S3 (lists both pools, samples N per AA)
2. Clean previous results
3. Run the full scoring pipeline
4. Aggregate and classify
5. Compare against ground truth (part2 column)
6. Report pass/fail

`DEV_SAMPLES_PER_AA = 20` at the top of `test_harness.py` controls sample size.

### PROD
```
python test_harness.py PROD
```
Expects the candidates CSV already exists at:
`05-Candidates/PROD-CandidateS3PathsForEvaluation.csv`

To create that CSV:
1. Run `findcandidates_42cfr.sql` in Athena
2. Change `WHERE rn <= 20` in the SQL to set sample size per source
3. Export results as CSV
4. Place in `05-Candidates/`

### Skip scoring (use existing results)
```
python test_harness.py DEV --skip-scoring
python test_harness.py PROD --skip-scoring
```


## What We Need to Prove (5 Tests)

### Test 1 — Distinct Assigning Authorities from Both Pools

The pipeline produces a distinct list of AAs from both part2=Yes and
part2=No populations.

**Pass:** At least 1 distinct AA per pool. Lists don't overlap.


### Test 2 — Correctly Identify Likely 42 CFR Sources

Each AA classified correctly based on clinical content:
- part2=Yes sources → should score as CANDIDATE (any level)
- part2=No sources → should score as NOT A CANDIDATE

**Pass:** Within variance tolerance (see below).


### Test 3 — Generate a Letter for Each Candidate

Every source classified as CANDIDATE produces an HTML letter.

**Pass:** Count of HTML letters = count of sources flagged as CANDIDATE.


### Test 4 — Every Known 42 CFR Source Gets a Letter

No known-positive missed.

**Pass:** All part2=Yes AAs produce a letter (within false-negative tolerance).


### Test 5 — No Letters from Non-42-CFR Sources

part2=No sources should NOT produce letters.

**Pass:** Zero letters for part2=No AAs (within false-positive tolerance).


## Variance Tolerance

Not every result will be perfect — synthetic data may not have strong
enough signals, and borderline cases exist. We allow:

| Landscape | Max False Negatives | Max False Positives |
|-----------|--------------------|--------------------|
| DEV | 2 | 0 |
| PROD | 5 | 3 |

**False negative** = a known Part 2 source that our code missed (scored NOT A CANDIDATE).
- Cost: a phone call we should have made but didn't.
- Action: inspect which checkers returned 0, adjust indicators.

**False positive** = a non-Part-2 source that our code incorrectly flagged.
- Cost: an unnecessary phone call.
- Action: inspect what triggered the flag, tighten that checker.

The DEV tolerance for false positives is 0 because the RawCCDs are clean
synthetic data with no SUD content — if we flag those, something is wrong.


## Test Harness Output

The harness prints a clear report to the console AND generates an HTML report
for the developer in the results folder:

```
06-Results/DEV-Output/test_harness_report_2026-08-27.html
06-Results/PROD-Output/test_harness_report_2026-08-27.html
```

The HTML report focuses on **scoring accuracy** — specifically, how reliably
the system identifies known Part 2 sources as Part 2. It includes:

- **Overall verdict** (PASS/FAIL) with color-coded banner
- **Accuracy metrics** — overall accuracy, sensitivity (Part 2 detection rate),
  specificity (non-Part-2 correct rate), precision
- **Confusion matrix** — true positives, true negatives, false positives,
  false negatives in a clear 2x2 grid
- **Tolerance check** — allowed vs actual for each metric, pass/fail per row
- **Input summary** — what was evaluated (row counts, distinct AAs)
- **Failure detail** — if any false negatives or false positives, lists each
  source with its AA, QE, SUD prevalence, classification, and top codes so
  the developer knows exactly what to investigate

The console output looks like:
```
======================================================================
  TEST RESULTS — DEV
======================================================================

  True Positives  (correctly flagged as CANDIDATE):   1
  True Negatives  (correctly NOT flagged):            2
  False Negatives (missed — should be CANDIDATE):     0
  False Positives (over-flagged — should NOT be):     0

  Allowed false negatives: 2  | Actual: 0  | PASS
  Allowed false positives: 0  | Actual: 0  | PASS

======================================================================
  OVERALL: PASS
======================================================================
```

Exit code 0 = pass, 1 = fail (usable in automation).


## If Tests Fail

| Failure | What it means | Action |
|---------|---------------|--------|
| Known 42 CFR source scores NOT A CANDIDATE | Checkers too strict or missing signals | Look at scored JSON for that source — which checkers returned 0? Are the synthetic CCDs actually coded with F10-F19 / MAT meds? Adjust checker logic. |
| Non-Part-2 source scores as CANDIDATE | Checkers too loose | Look at what triggered the flag — was it a buprenorphine mention in a general practice? A false-matching keyword? Tighten the checker or adjust thresholds. |
| Missing letters for flagged sources | Letter generation bug | Check generate_qe_letters.py — is it reading the aggregate CSV correctly? |
| Letter generated for a non-42-CFR source | Scoring is correct but letter logic wrong | Trace: did aggregate classify it correctly but letter gen picked it up anyway? |
| DEV RawCCDs all fail to parse | Those files are .csv not .xml | The DEV candidate builder now filters to .xml only — verify filter is working |


## File Locations

| File | Purpose |
|------|---------|
| `03-SupportingCode/test_harness.py` | The test harness (run this) |
| `03-SupportingCode/run_pipeline.py` | The pipeline it wraps |
| `03-SupportingCode/make_dev_candidates_42cfr.py` | Standalone DEV CSV builder (test_harness calls this logic internally) |
| `03-SupportingCode/cleanup_run.py` | Utility to wipe results for a fresh run |
| `02-SupportingSQL/findcandidates_42cfr.sql` | Athena SQL to produce PROD candidates CSV |
| `05-Candidates/DEV-42CFR-CandidateS3Paths.csv` | DEV candidates (rebuilt each test run) |
| `05-Candidates/PROD-CandidateS3PathsForEvaluation.csv` | PROD candidates (from Athena export) |
| `06-Results/DEV-Output/` | DEV scoring results, aggregate, letters |
| `06-Results/PROD-Output/` | PROD scoring results, aggregate, letters |
