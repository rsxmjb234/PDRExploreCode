# Core Plan: CCD Coding Quality Evaluation

## Purpose

Answer the SHIN-NY policy question on QE value-add versus raw pass-through by measuring coding quality at source and QE levels across all 13 CCD segments.

## Scope

- Evaluate coding quality for CCDs processed into PDR from approximately 4,500 sources.
- Report at source level and QE level.
- Cover all 14 target segments using fixed segment keys (including demographics).
- Produce one JSON result per CCD and analyze with Athena.
- Prioritize readable, quickly created analysis code over production-grade repeatability.

Out of scope for this core plan:

- DEV synthetic test-data creation logic.
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

## Decision Framework

Use consistent cutoffs with standard_pct and missing_pct:

- Tier A: standard_pct >= 90 and missing_pct <= 5. Policy signal: raw pass-through default.
- Tier B: standard_pct 75-89 or missing_pct 6-10. Policy signal: targeted QE improvements.
- Tier C: standard_pct 60-74 or missing_pct 11-20. Policy signal: QE normalization justified.
- Tier D: standard_pct < 60 or missing_pct > 20. Policy signal: QE transformation strongly justified.

## Segment Scoring Model

Per coded segment instance:

- Standard: at least one accepted national-standard code appears (primary or translation).
- Local: coded only with local or proprietary code systems.
- Missing: code element present but @code or @codeSystem is absent/empty/nullFlavor.
- Section Absent: the entire CDA section for this domain does not exist in the CCD.

The distinction between Missing and Section Absent matters:

- Missing = the source attempted to send data but didn't code it properly.
  This is a coding quality issue that could potentially be fixed.
- Section Absent = the source never included this section at all.
  This may reflect scope (e.g., a mental health provider with no lab section)
  or a configuration gap in the interface engine.

Both are reported separately in domain_counts so consumers can distinguish
"bad coding" from "data not applicable to this source."

Optional points:

- Standard = 1.0
- Local = 0.0
- Missing = 0.0
- Section Absent = not counted (excluded from denominator)

Core formulas:

- domain_standard_pct = 100 * domain_standard_count / domain_total_count
- domain_nonstandard_pct = 100 * (domain_local_count + domain_missing_count) / domain_total_count
- overall_standard_pct = 100 * sum(standard_count) / sum(total_count)

## Data Inputs and Environment

- Candidate list pattern reused from findcandidatesforexplore.sql.
- DEV and PROD fork at startup using one explicit profile switch.
- Same core logic in DEV and PROD; only config changes.
- DEV first, then PROD promotion with unchanged core logic.

## DEV Validation Handshake (Required)

- Test data and expected scores are created by the process defined in DataCodingQualityStandards/ccd-coding-quality-dev-test-data-plan.md.
- The core scoring code in this plan must run against that exact generated CCD set (same generated_output_key set).
- For each generated CCD, produced summary/domain_counts/local_oid_counts must match the expected mirrored record from the DEV plan.
- Matching key for comparisons is generated_output_key.
- Expected records should be read from the DEV plan output location s3://nyec.ccda.learning/TestDataForDeterminingLevelOfCodeSetQuality/ (or configured override).
- Promote to PROD only after expected-versus-actual comparison passes.

Suggested run modes:

- Quick validation: N = 5-10
- Operational baseline: N = 20
- Extended study: N = 50+ (run multiple batches using restart capability)

## Output Contract

One JSON per CCD at deterministic mirrored path:

s3://<analytics-bucket>/ccd-coding-quality/run_date=YYYY-MM-DD/qe=<qe>/assigning_authority=<aa>/key_mirror/<original-s3-key>.json

For DEV validation runs, a DEV output prefix may be used, but the JSON schema and segment keys must remain identical to PROD.

Idempotency and restart rules:

- Never process the same XML twice in a target output location.
- Before parse, check if mirrored JSON exists.
- If JSON exists, skip and log as already processed.

JSON must include:

- Run metadata
- Source metadata
- Document metadata
- Summary counts (standard, local, missing, section_absent)
- domain_counts for all 14 fixed segment keys, each with:
  - total (number of coded elements found)
  - standard (count using national code systems)
  - local (count using proprietary/local code systems)
  - missing (count where code element present but unusable)
  - section_absent (boolean: was the CDA section present at all?)
- local_oid_counts

## Athena Layer

- Maintain external table over JSON output.
- Keep stable key names in domain_counts (14 segments).
- Query per source, per QE, per segment for national-standard versus non-standard rates.
- Report section_absent separately from coding quality (absent != poorly coded).

Minimum end-state writing requirement:

- For each Assigning Authority and each segment, report percent nationally encoded and percent non-standard (local + missing).
- Identify weakest segment per Assigning Authority.

## Metrics and Acceptance Criteria

- Parsing success rate: >= 98%
- Duplicate-processing rate: 0 duplicates when mirrored JSON exists
- Classification coverage: >= 95%
- Source score completeness: 100%

## Deliverables

- Core scoring rulebook for 13 segments
- Stable segment key convention
- JSON output schema and naming contract
- Athena table definition and query pack
- Source/QE score outputs with decision tiers
