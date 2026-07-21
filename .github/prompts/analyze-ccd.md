# Analyze CCD Document

Analyze a CCD XML document from S3 and determine the likely EHR vendor.

## Steps
1. Download the CCD from the specified S3 path
2. Parse the XML and extract these signals:
   - `assignedAuthoringDevice/softwareName`
   - `assignedAuthoringDevice/manufacturerModelName`
   - `custodian/.../representedCustodianOrganization/name`
   - All `templateId` OIDs
   - Section order (LOINC codes)
   - OID families (looking for 1.2.840.114350 = Epic)
   - XML formatting style (indentation)
3. Score the signals against known Epic patterns
4. Report classification: EPIC, NOT-EPIC, or NOT SURE

## Variables
- `$S3_BUCKET` — The S3 bucket to read from
- `$S3_KEY` — The object key (path) within the bucket
- `$AWS_PROFILE` — The AWS CLI profile to use for authentication
