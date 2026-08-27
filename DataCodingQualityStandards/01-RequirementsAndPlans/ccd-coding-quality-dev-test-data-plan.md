# DEV Plan: Synthetic Test Data and Test Case Creation

## Purpose

Create controlled DEV test CCDs from Synthea raw CCDs so core parser and scoring logic can be validated against known expected outcomes before PROD runs.

This plan is the source of truth for generated CCD test inputs and expected scores consumed by the core scorer in DataCodingQualityStandards/ccd-coding-quality-core-plan.md.

## Scope

- DEV only.
- Input is synthetic CCD data in s3://nyec.ccda.learning/RawCCDs/.
- For every input CCD, generate test-case variants with known outcomes.
- Validate all 14 segment scoring behaviors (Standard, Local, Missing, Section Absent).

Out of scope for this plan:

- Production scoring runs.
- Policy interpretation and final source/QE decisions.

## Input and Output Locations

Input:

- Bucket: nyec.ccda.learning
- Prefix: RawCCDs/

Suggested output:

- s3://nyec.ccda.learning/TestDataForDeterminingLevelOfCodeSetQuality/
- Store generation manifest and expected outcomes alongside generated CCDs.

## Test Case Generator Requirements

Generator must:

- Accept bucket and prefix as inputs.
- Read each CCD in source folder.
- Create copied CCD variants from each source CCD.
- Mutate all 14 segments in controlled ways.
- Save generated CCDs and test manifests.

Per generated CCD record include:

- test_case_id
- source_input_key
- generated_output_key
- segments_modified
- intended segment state per segment key
- expected aggregate outcomes

## Expected Outcome Mirror Contract

For every generated CCD, store an expected-outcome object that mirrors the core pipeline export shape so actual vs expected comparison is one-to-one.

Required mirror fields per generated CCD:

- run_id (or expected_run_id pattern)
- source.assigning_authority
- source.qe
- source.bucket
- source.key
- summary.total_elements
- summary.standard_count
- summary.local_count
- summary.missing_count
- domain_counts for all 14 fixed segment keys, each with:
	- total
	- standard
	- local
	- missing
	- section_absent (boolean)
- local_oid_counts (when local coding is intentionally introduced)

Required storage pattern:

- Save expected outcomes next to generated CCDs, for example as expected JSON sidecar files or a manifest JSONL file.
- Ensure each generated CCD has exactly one expected outcome record keyed by generated_output_key.
- The core scoring run must use this same generated_output_key set as its input population in DEV.

Minimum expected-outcome example (shape only):

```json
{
	"generated_output_key": "s3://.../testcases/doc-123-case-L.xml",
	"expected_result": {
		"summary": {
			"total_elements": 140,
			"standard_count": 74,
			"local_count": 42,
			"missing_count": 24,
			"sections_absent": 2
		},
		"domain_counts": {
			"allergies": { "total": 10, "standard": 5, "local": 3, "missing": 2, "section_absent": false },
			"assessment": { "total": 10, "standard": 6, "local": 2, "missing": 2, "section_absent": false },
			"care_plan": { "total": 10, "standard": 6, "local": 3, "missing": 1, "section_absent": false },
			"chief_complaint": { "total": 10, "standard": 4, "local": 4, "missing": 2, "section_absent": false },
			"demographics": { "total": 10, "standard": 8, "local": 1, "missing": 1, "section_absent": false },
			"encounters": { "total": 10, "standard": 5, "local": 3, "missing": 2, "section_absent": false },
			"functional_status": { "total": 0, "standard": 0, "local": 0, "missing": 0, "section_absent": true },
			"immunizations": { "total": 10, "standard": 7, "local": 2, "missing": 1, "section_absent": false },
			"labs_results": { "total": 10, "standard": 3, "local": 6, "missing": 1, "section_absent": false },
			"medications": { "total": 10, "standard": 6, "local": 3, "missing": 1, "section_absent": false },
			"problems": { "total": 10, "standard": 7, "local": 2, "missing": 1, "section_absent": false },
			"procedures": { "total": 10, "standard": 6, "local": 2, "missing": 2, "section_absent": false },
			"social_history": { "total": 0, "standard": 0, "local": 0, "missing": 0, "section_absent": true },
			"vitals": { "total": 10, "standard": 4, "local": 5, "missing": 1, "section_absent": false }
		},
		"local_oid_counts": {
			"1.2.3.4.5.local": 15
		}
	}
}
```

## Required Segment-State Coverage

For each of the 14 segments, include at minimum:

1. Standard case
2. Local case
3. Missing case (code element present but unusable)
4. Section Absent case (entire CDA section removed)

Coverage rule:

- Every CCD in the input folder must produce generated documents satisfying the required cases.

## Mutation Patterns

IMPORTANT DESIGN PRINCIPLE: Real EHR systems are CONSISTENT. A source that
codes labs to LOINC does so for virtually every CCD it produces. A source
with local codes sends local codes every time. Test data must reflect this.

Each QE|AA source is assigned a quality_tier (A/B/C/D) that determines its
coding behavior CONSISTENTLY across all CCDs from that source:

- Tier A (well-coded): 90-100% standard across all segments
- Tier B (decent): 75-89% standard, with 1-2 weak segments
- Tier C (mixed): 60-74% standard, several segments poorly coded
- Tier D (poorly coded): <60% standard, heavy local codes, some sections absent

Per-document variance within a source is SMALL (5-10%) — simulating the fact
that the underlying EHR configuration drives coding, not the clinical content.

The source quality profiles are defined in exampleof5aaforeveryqe.txt alongside
the QE/AA identifiers. The generator reads this file and applies the appropriate
quality behavior per source.

Segment-level behavior per tier:

- Tier A: all 14 segments coded to national standards (small random variance)
- Tier B: most segments well-coded, 1-2 segments have 20-40% local codes
- Tier C: problems/meds usually ok, labs/procedures often local, some sections absent
- Tier D: mostly local codes, multiple sections absent, high missing rate

## Validation Workflow

1. Generate DEV test CCDs from Synthea inputs.
2. Run core scoring pipeline in DEV over generated test CCDs.
3. Join produced results to expected outcomes using generated_output_key.
4. Compare mirrored fields directly: summary counts, each segment in domain_counts, and local_oid_counts where applicable.
5. Flag mismatches by segment and by test_case_id.
6. Fail validation if mismatch threshold exceeded.

## Validation Acceptance Criteria

- Expected outcome match: 100% for required baseline cases, or explicitly approved exceptions.
- Segment coverage: all 14 segments tested in all four states (Standard, Local, Missing, Section Absent).
- Generator completeness: every source input CCD produces required test outputs.
- Manifest completeness: no generated file without expected-outcome metadata.

## Deliverables

- DEV test-case generator specification
- Mutation profile catalog
- Generated test-case manifest format
- Expected outcomes format
- Validation result report template
- Promotion gate checklist from DEV to PROD
