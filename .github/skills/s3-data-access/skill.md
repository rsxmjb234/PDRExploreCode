# S3 Data Access Skill

## Description
Connect to AWS S3 and read CCD documents using boto3 with named profiles.

## Key Knowledge

### Authentication
We use AWS CLI named profiles (not environment variables or IAM roles):
```python
session = boto3.Session(profile_name="student1")
s3 = session.client("s3")
```

### Profiles
- DEV: `student1` — access to `nyec.ccda.learning` bucket
- PROD: `dan-prod` — access to `nyec-pdr-prod-hixny` bucket

### Reading a CCD
```python
response = s3.get_object(Bucket=bucket, Key=s3_key)
xml_bytes = response["Body"].read()
```

### Listing Objects
```python
response = s3.list_objects_v2(Bucket=bucket, Prefix="RawCCDs/", MaxKeys=10)
for obj in response.get("Contents", []):
    print(obj["Key"])
```

### Important Notes
- CCDs are kept in memory only (never written to local disk)
- S3 keys come from input CSVs (Athena export or DEV utility)
- Always handle download errors gracefully and continue to next file
