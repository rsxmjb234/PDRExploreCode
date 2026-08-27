# Task Planner Agent

## Role
Break a data exploration goal into executable steps following the established project pattern.

## Context
Every investigation in this repo follows the same lifecycle:

1. **Define the question** (HTML requirement doc + planning markdown)
2. **Find candidates** (SQL query against S3 inventory in Athena)
3. **Build scorer** (Python script: download → parse → extract signals → write results)
4. **Test in DEV** (synthetic or learning-bucket data)
5. **Run in PROD** (real data, same code, different profile)
6. **Analyze** (SQL summaries or HTML reports from results)

## Planning Rules
- Start with the HTML requirements doc — that's the "what"
- Plans go in `01-RequirementsAndPlans/`
- Each plan must specify: what signals to look for, where in the document, what counts as "good" vs "bad"
- DEV testing uses `nyec.ccda.learning` bucket with Synthea data
- PROD uses multi-bucket setup with `allowed_buckets` list
- Sample size: 5-20 per source for initial runs, scale up after validation
- All scripts need: DEV/PROD switch, restart capability, timing, progress output

## Plan Template
```markdown
# Plan: [Name]

## Goal
[One sentence]

## Signals to Extract
| Signal | Where in CCD/TRN | What to look for |

## Scoring Logic
[How to classify: good/bad/missing/absent]

## Output Schema
[JSON or CSV columns]

## Scripts to Build
| Script | Purpose |

## DEV Testing Strategy
[What data, expected results]

## Thresholds / Decision Framework
[When to flag, when to escalate]
```
