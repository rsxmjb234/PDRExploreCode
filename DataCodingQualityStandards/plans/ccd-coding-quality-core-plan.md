# Core Plan: CCD Coding Quality Evaluation

## Purpose

Measure whether each data source codes its clinical data to recognized
national standards (LOINC, RxNorm, SNOMED-CT, etc.) — or uses local/proprietary
codes that aren't interoperable.


## The Simple Idea

Each CCD section has a known "correct" code system. For every clinical entry
in that section, we check: does it reference a national standard?

- Medications → should be coded to **RxNorm** (or NDC)
- Labs/Results → should be coded to **LOINC**
- Problems → should be coded to **SNOMED-CT** (or ICD-10)
- Procedures → should be coded to **SNOMED-CT** (or CPT, ICD-10-PCS)
- Immunizations → should be coded to **CVX**
- Vital Signs → should be coded to **LOINC**
- Allergies → should be coded to **RxNorm** (substance) + **SNOMED-CT** (reaction)
- Demographics → should be coded to **CDC CDCREC** (race/ethnicity) + **HL7** (gender)

If the entry's code references one of these → **Standard** (good).
If it references something else → **Local** (bad — proprietary code).
If it has no code at all → **Missing**.
If the entire section doesn't exist → **Section Absent**.

We do NOT count structural CDA wrapper codes (ActCode, ActClass, etc.).
We only look at the actual clinical data codes on the primary entries.


## What We Look At Per Section

For each CCD section, we find the **clinical entries** (the actual data
items — observations, substance administrations, acts, encounters) and
check the `code` element on each one.

In XML terms, a clinical entry's code looks like:
```xml
<code code="1535362" 
      codeSystem="2.16.840.1.113883.6.88"
      codeSystemName="RxNorm"
      displayName="sodium fluoride 0.0272 MG/MG Oral Gel"/>
```

We check the `codeSystem` attribute against the expected list for that section.

Alternatively, some CCDs use URL-style references in text:
```
http://www.nlm.nih.gov/research/umls/rxnorm 1535362
```

Both styles indicate the same thing: this entry is coded to RxNorm.


## Expected Code Systems Per Section

| Section | LOINC Code | Expected Code Systems (any of these = "Standard") |
|---------|-----------|--------------------------------------------------|
| Medications | 10160-0 | RxNorm (`2.16.840.1.113883.6.88`), NDC (`2.16.840.1.113883.6.69`) |
| Labs/Results | 30954-2 | LOINC (`2.16.840.1.113883.6.1`) |
| Problems | 11450-4 | SNOMED-CT (`2.16.840.1.113883.6.96`), ICD-10-CM (`2.16.840.1.113883.6.90`) |
| Procedures | 47519-4 | SNOMED-CT (`2.16.840.1.113883.6.96`), CPT (`2.16.840.1.113883.6.12`), ICD-10-PCS (`2.16.840.1.113883.6.4`) |
| Immunizations | 11369-6 | CVX (`2.16.840.1.113883.12.292`) |
| Vital Signs | 8716-3 | LOINC (`2.16.840.1.113883.6.1`) |
| Allergies | 48765-2 | RxNorm (`2.16.840.1.113883.6.88`), SNOMED-CT (`2.16.840.1.113883.6.96`), UNII (`2.16.840.1.113883.4.9`) |
| Encounters | 46240-8 | SNOMED-CT (`2.16.840.1.113883.6.96`), CPT (`2.16.840.1.113883.6.12`) |
| Social History | 29762-2 | SNOMED-CT (`2.16.840.1.113883.6.96`), LOINC (`2.16.840.1.113883.6.1`) |
| Care Plan | 18776-5 | SNOMED-CT (`2.16.840.1.113883.6.96`) |
| Functional Status | 47420-5 | SNOMED-CT (`2.16.840.1.113883.6.96`), LOINC (`2.16.840.1.113883.6.1`) |
| Demographics | (header) | CDC CDCREC (`2.16.840.1.113883.6.238`), HL7 Gender (`2.16.840.1.113883.5.1`) |


## What We Count As a "Clinical Entry"

Per section, we look for the primary coded data items — not the wrapper/structural
elements that CDA uses for organization. Specifically:

| Section | Entry Element(s) to Check |
|---------|--------------------------|
| Medications | `substanceAdministration/.../code` on the manufactured material |
| Labs | `observation/code` (the test identity — not the organizer wrapper) |
| Problems | `observation/value` (the diagnosis code, often in `@value`) |
| Procedures | `procedure/code` or `act/code` |
| Immunizations | `substanceAdministration/.../code` on the vaccine material |
| Vitals | `observation/code` (the vital type — height, weight, BP, etc.) |
| Allergies | `observation/value` (the allergen) or `participant/code` |
| Encounters | `encounter/code` (the encounter type) |
| Social History | `observation/code` or `observation/value` |
| Care Plan | `act/code` or `observation/code` |
| Functional Status | `observation/code` or `observation/value` |
| Demographics | `raceCode`, `ethnicGroupCode`, `administrativeGenderCode` directly |

Key rule: we look at the **FIRST meaningful code** on each entry.
If that code references a national standard → Standard.
If not → check `translation` elements for a standard code (give credit if found).
If nothing → Local or Missing.


## Scoring Per Source

For each QE|AA:
1. Score N documents (20 in PROD, 10 in DEV)
2. Aggregate per-section counts: how many entries standard vs local vs missing
3. Compute section_standard_pct = standard / total for each section
4. Compute overall_standard_pct across all sections
5. Assign tier: A (>=90%), B (75-89%), C (60-74%), D (<60%)

Note: In DEV with Synthea data, the ceiling is lower (~70%) because Synthea
uses some structural codes we don't track. Thresholds are adjusted for DEV.
In PROD with real Epic/Cerner data, expect the full 90%+ range.


## Architecture (same pattern as findandsaveEHRfromCCD-EntireCCD.py)

```
[Candidate CSV]  →  [Batch Scorer]  →  [1 JSON per CCD]  →  [HTML Report]
```

1. Input: Candidate CSV (assigning_authority, qe, bucket, key, size, last_modified)
2. Processing: Download CCD, find sections, count clinical entries, classify each
3. Output: One JSON per CCD with source metadata + per-section counts
4. Restart: Skip files where output JSON already exists
5. Report: HTML files grouped by QE, worst sources first


## Output JSON Schema (per CCD)

```json
{
  "source": {
    "assigning_authority": "STRONG MEMORIAL",
    "qe": "rochester",
    "bucket": "nyec-pdr-prod-rochester",
    "key": "STRONG MEMORIAL/ccd/2026/Jul/21/...",
    "path": "s3://..."
  },
  "processing_time_ms": 342,
  "file_size_bytes": 456000,
  "summary": {
    "total_entries": 45,
    "standard_count": 40,
    "local_count": 3,
    "missing_count": 2,
    "sections_absent": 2
  },
  "domain_counts": {
    "medications": { "total": 8, "standard": 8, "local": 0, "missing": 0, "section_absent": false },
    "labs_results": { "total": 12, "standard": 11, "local": 1, "missing": 0, "section_absent": false },
    "problems": { "total": 10, "standard": 9, "local": 0, "missing": 1, "section_absent": false },
    "...": "..."
  },
  "local_code_systems_found": {
    "1.2.3.4.5.facility": 3
  }
}
```


## Deliverables

- [x] Plans (this document)
- [x] generate_test_cases.py (DEV test data with realistic quality tiers)
- [ ] segment_mapping.py (REWRITE: simpler, entry-focused approach)
- [ ] score_ccd_coding_quality.py (REWRITE: count clinical entries only)
- [x] validate_test_cases.py (promotion gate)
- [x] validate_tier_assignments.py (expected tier = actual tier)
- [x] generate_report.py (HTML reports)
- [x] 0. run_dev_full_pipeline.py (end-to-end)
- [x] 0. run_PROD_full_pipeline.py (PROD runner)
