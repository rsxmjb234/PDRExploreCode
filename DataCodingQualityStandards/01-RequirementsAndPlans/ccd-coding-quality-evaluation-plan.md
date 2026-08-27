# System Plan: Evaluate CCD Coding Quality by Source

## Overview

This plan describes the full pipeline from raw CCD scoring through to
human-readable HTML reports that show coding quality by QE and source.

No Athena reporting layer. Instead, Python reads the scored JSON results
and generates styled HTML report files (similar to the concept HTML in
`data-quality of the codeset in CCDs.html`).


## Active Plans

- Core scoring and policy: `plans/ccd-coding-quality-core-plan.md`
- DEV test data generation: `plans/ccd-coding-quality-dev-test-data-plan.md`
- This file: reporting and output strategy


## Key Parameters

- 14 CCD segments evaluated (including demographics)
- 4 states per segment: Standard, Local, Missing, Section Absent
- 20 CCDs per source per run (use restart to accumulate more)
- 4-tier decision framework (A/B/C/D) for policy signals


## Execution Contract

1. Generate DEV test CCDs (`generate_test_cases.py`)
2. Score all CCDs (`score_ccd_coding_quality.py`)
3. Validate scores match expected (`validate_test_cases.py`)
4. **Generate HTML report(s)** from scored JSON results (`generate_report.py`)


## Reporting Strategy: HTML Files (not Athena)

Rather than loading scored results into Athena for SQL-based reporting,
we generate self-contained HTML report files directly from the scored JSONs.

### Why HTML instead of Athena:
- Shareable without AWS access (email, SharePoint, Teams)
- Visual at a glance (color-coded cells like the concept HTML)
- No infra needed — just run a Python script
- Can be opened by anyone (Dan, management, QE contacts)

### Report Structure:

**One HTML file per QE**, plus one summary file:

```
DEV-Output/reports/
  summary.html                    ← All QEs at a glance
  report_bronx.html               ← Bronx QE detail
  report_healtheconnections.html  ← HealtheConnections detail
  report_healthix.html            ← Healthix detail
  report_hixny.html               ← Hixny detail
  report_rochester.html           ← Rochester detail
  report_techbd.html              ← TechBD detail
```

### Summary HTML (`summary.html`):

Shows one row per QE with aggregate stats:
- QE name
- Number of sources evaluated
- Overall % standard across all sources
- Weakest segment (the domain with lowest % standard)
- Tier distribution (how many A/B/C/D sources in this QE)

### Per-QE Detail HTML (`report_<qe>.html`):

**Header section:**
- QE name, date, number of sources, number of CCDs scored
- Overall QE-level % standard

**Source matrix (the main deliverable):**
- One row per Assigning Authority
- Sorted: WORST performers at TOP, BEST at BOTTOM
- Columns: one per segment (14 columns)
- Each cell color-coded:
  - Green (well-coded): >= 90% standard for that segment
  - Yellow (mixed): 60-89% standard
  - Red (poorly coded): < 60% standard
  - Gray (section absent): section not present in any CCD from this source

**Per-source detail row includes:**
- Assigning Authority name
- Quality tier (A/B/C/D)
- Overall % standard
- Per-segment % standard (color-coded)
- Number of CCDs scored
- Weakest segment name

**Footer:**
- Summary stats for this QE
- Tier distribution pie/bar
- List of most common local code systems found


### Sorting Logic:

Within each QE report, sources are sorted by overall_standard_pct ASCENDING.
This puts the worst performers at the top — the ones that need attention first.
Best performers are at the bottom (they don't need action).


## Report Generator Requirements (`generate_report.py`)

Input:
- Directory of scored JSON files (from `score_ccd_coding_quality.py`)

Processing:
1. Read all scored JSONs
2. Group by source.qe, then by source.assigning_authority
3. For each source, aggregate across all CCDs:
   - Per-segment: avg % standard, avg % local, avg % missing, section_absent rate
   - Overall: total elements, total standard, total local, total missing
4. Assign tier (A/B/C/D) based on overall_standard_pct
5. Sort sources within each QE by overall_standard_pct ascending (worst first)
6. Generate HTML using inline CSS (no external dependencies)

Output:
- `summary.html` — cross-QE overview
- `report_<qe>.html` — one per QE with full source matrix

Style:
- Match the look/feel of `data-quality of the codeset in CCDs.html`
- Warm tones, clear headers, color-coded cells
- Self-contained (all CSS inline, no external files needed)
- Mobile-friendly (responsive grid)


## Color Coding Reference

| % Standard | Color | Label |
|-----------|-------|-------|
| >= 90% | Green (#d1fae5) | Well-coded |
| 60-89% | Yellow (#fef3c7) | Mixed |
| < 60% | Red (#fee2e2) | Poorly coded |
| Section absent | Gray (#f3f4f6) | No data |


## Deliverables

- [x] segment_mapping.py (14 segments, accepted code systems)
- [x] generate_test_cases.py (DEV test data with realistic quality tiers)
- [x] score_ccd_coding_quality.py (core scorer, validated)
- [x] validate_test_cases.py (promotion gate)
- [ ] generate_report.py (HTML report generator)
- [ ] summary.html template/output
- [ ] Per-QE report HTML files
