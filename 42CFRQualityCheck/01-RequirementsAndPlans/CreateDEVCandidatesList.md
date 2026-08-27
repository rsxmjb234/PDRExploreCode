# Plan: Create DEV Candidates CSV from Known 42 CFR CCDs

## Goal

Build a candidates CSV file listing all CCDs in:

```
s3://nyec.ccda.learning/42CFRStyleCCDs/
```

This CSV becomes the DEV input for our 42 CFR scoring pipeline — the
"known positives" we use in Phase 1 calibration to confirm the tool
reliably identifies 42 CFR-style content before trusting it on the
general population.


## What the CSV Needs to Look Like

Same format as all our other candidate CSVs (FindEHR, DataCodingQuality):

| Column | Value |
|--------|-------|
| bucket | `nyec.ccda.learning` |
| key | Full S3 key (e.g., `42CFRStyleCCDs/somefile.xml`) |
| qe | `dev-42cfr` (hardcoded — these are test docs, not from a real QE) |
| assigning_authority | Parse from the key if possible, otherwise `42cfr-dev` |


## How to Build It

1. Use boto3 with profile `student1` to list all objects under the prefix
   `42CFRStyleCCDs/` in bucket `nyec.ccda.learning`
2. Filter to files only (skip zero-byte "folder" markers)
3. Optionally filter to `.xml` extensions if other file types are present
4. Write one row per object to the output CSV
5. Save to: `42CFRQualityCheck/05-Candidates/DEV-42CFR-CandidateS3Paths.csv`


## Script

Write a small standalone Python script:

```
42CFRQualityCheck/03-SupportingCode/make_dev_candidates_42cfr.py
```

It should:
- Use `student1` AWS profile
- List `s3://nyec.ccda.learning/42CFRStyleCCDs/` (paginated if >1000 objects)
- Print count of objects found
- Write the CSV
- Be runnable standalone: `python make_dev_candidates_42cfr.py`


## Then

Once the CSV exists, update `config.py` DEV profile to point to it:

```python
"input_csv": os.path.join("..", "05-Candidates", "DEV-42CFR-CandidateS3Paths.csv"),
```

And run the pipeline in DEV mode. These are our known 42 CFR documents —
we expect them to score as CANDIDATE - HIGH. If they don't, we iterate
the checkers until they do.
