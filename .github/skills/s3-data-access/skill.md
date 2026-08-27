# S3 Data Access

## How we connect to S3
```python
session = boto3.Session(profile_name="student1")  # DEV
session = boto3.Session(profile_name="default")   # PROD
s3 = session.client("s3")
```

## DEV Bucket
- `nyec.ccda.learning` — Synthea test data
- Prefix: `RawCCDs/` for source CCDs

## PROD Buckets (12 total)
- `nyec-pdr-prod-hixny` / `-part2`
- `nyec-pdr-prod-bronx` / `-part2`
- `nyec-pdr-prod-healtheconnections` / `-part2`
- `nyec-pdr-prod-healthix` / `-part2`
- `nyec-pdr-prod-rochester` / `-part2`
- `nyec-pdr-prod-techbd` / `-part2`

## Reading a file
```python
response = s3.get_object(Bucket=bucket, Key=key)
content = response["Body"].read()
```

## Key pattern
- Candidate CSVs have: `assigning_authority, qe, bucket, key, size, last_modified`
- PROD: each row specifies its own bucket
- DEV: uses `default_bucket` configuration
