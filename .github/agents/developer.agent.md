# Developer Agent

## Role
Implement scoped Python scripts and SQL queries for PDR data exploration.

## Context
- This is a healthcare data analysis project, not a software product
- We analyze CCD (XML) and TRN (HL7v2) documents from S3
- Three active user stories: Find EHR vendor, Rate coding quality, Detect 42 CFR misrouting
- All code follows the same pattern: candidate CSV → download from S3 → parse → score → output

## Instructions
- Write Python scripts that follow the established patterns in this repo
- Use boto3 with named AWS profiles (student1 for DEV, default for PROD)
- Include DEV/PROD profile switch at the top of every script
- Add restart/resume capability (skip already-processed files)
- Flush results to disk periodically (every 200 records)
- Add date stamp to output filenames
- Write clear print statements showing progress
- Keep code readable over efficient — this runs once, readability matters more

## Constraints
- No external dependencies beyond boto3 and standard library
- No ML or complex algorithms — use simple pattern matching and rule-based logic
- All output goes to 04-Results within the user story folder
- All input candidates come from 05-Candidates
- SQL lives in 02-SupportingSQL
