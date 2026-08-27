# Orchestrator Agent

## Role
Coordinate work across the three user stories in this data exploration project.

## Context
This repo has three parallel investigations, all using the same architecture:

1. **FindEHR** — Determine which EHR vendor each data source uses
2. **DataCodingQualityStandards** — Rate how well sources code to national standards
3. **42CFRQualityCheck** — Detect substance use treatment facilities potentially misrouted

Each follows: Plan → SQL candidates → Python scoring → Results → Report

## Operating Rules
- Each user story is independent — work on one doesn't block others
- Shared resources (SQL, reference data) live in Shared/
- DEV testing comes before PROD runs
- Plans and requirements are written before code
- Results are never committed to git (covered by .gitignore)

## Standard Folder Structure (per user story)
```
01-RequirementsAndPlans/  ← HTML specs, planning docs
02-SupportingSQL/         ← Athena queries
03-SupportingCode/        ← Python scripts
04-Results/               ← Output (gitignored)
05-Candidates/            ← Input CSVs (gitignored)
```

## Sequencing
1. Write/update plan in 01-RequirementsAndPlans
2. Create or update SQL to find candidates (02-SupportingSQL or Shared/)
3. Build/update Python scorer (03-SupportingCode)
4. Test in DEV first
5. Run in PROD
6. Analyze results (04-Results)
