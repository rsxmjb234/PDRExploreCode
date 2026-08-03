# System Plan: Evaluate CCD Coding Quality by Source

Use this file as an index only.

## Active Plans

- Core scoring and policy plan: DataCodingQualityStandards/ccd-coding-quality-core-plan.md
- DEV synthetic test-data and test-case plan: DataCodingQualityStandards/ccd-coding-quality-dev-test-data-plan.md

## Key Parameters

- 14 CCD segments evaluated (including demographics)
- 4 states per segment: Standard, Local, Missing, Section Absent
- 20 CCDs per source per run (use restart to accumulate more)
- 4-tier decision framework (A/B/C/D) for policy signals

## Execution Contract

1. Use DataCodingQualityStandards/ccd-coding-quality-dev-test-data-plan.md to generate DEV CCD test files and expected-score records.
2. Use DataCodingQualityStandards/ccd-coding-quality-core-plan.md to score that same generated CCD set.
3. Confirm produced scores match expected scores record-by-record before PROD promotion.
