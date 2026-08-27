# Analyze a CCD Document

Download a CCD from S3, parse it, and extract the relevant signals for the current investigation.

## Pattern
1. Read the candidate CSV for the S3 path (bucket + key)
2. Download using boto3 with the active AWS profile
3. Parse the XML using ElementTree
4. Extract signals relevant to the user story:
   - **FindEHR**: softwareName, manufacturerModelName → classify vendor
   - **CodingQuality**: code elements per section → classify as Standard/Local/Missing
   - **42CFR**: diagnoses, medications, encounters → count SUD-related entries
5. Write result (JSON or CSV row)

## Variables
- `$AWS_PROFILE` — The AWS CLI profile to use
- `$BUCKET` — The S3 bucket
- `$KEY` — The S3 object key
- `$USER_STORY` — Which analysis to run (FindEHR / CodingQuality / 42CFR)
