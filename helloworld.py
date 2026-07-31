"""
helloworld.py — Simplest possible S3 CCD test.

Opens one CCD from S3, extracts the document OID, saves S3 path + OID to a file.
"""

import boto3
import xml.etree.ElementTree as ET
import io

# =============================================================================
# PICK ONE: "DEV" or "PROD"
# =============================================================================
ACTIVE_PROFILE = "DEV"

# DEV config
DEV = {
    "aws_profile": "student1",
    "bucket": "nyec.ccda.learning",
    "key": "RawCCDs/Aaron697_Schiller186_d5d96071-fdff-d902-f487-de1a278fd864.xml",
}

# PROD config
PROD = {
    "aws_profile": "default",
    "bucket": "nyec-pdr-prod-hixny",
    "key": "1003861782/ccd/2026/Jul/06/15/hixny_1003861782_59041906c701c0a83ac4ca3781382549a9569358a4bddab470f413fef9fb56a7_2.16.840.1.113883.3.227.3245.1.1.c1be4578.xml",
}

# =============================================================================
# MAIN
# =============================================================================

config = DEV if ACTIVE_PROFILE == "DEV" else PROD

# 1. Download CCD from S3
print(f"Downloading CCD from s3://{config['bucket']}/{config['key']}")
session = boto3.Session(profile_name=config["aws_profile"])
s3 = session.client("s3")
response = s3.get_object(Bucket=config["bucket"], Key=config["key"])
xml_bytes = response["Body"].read()
print(f"  Downloaded {len(xml_bytes):,} bytes")

# 2. Parse XML and get the document OID (ClinicalDocument/id/@root)
ns = "urn:hl7-org:v3"
tree = ET.parse(io.BytesIO(xml_bytes))
root = tree.getroot()
doc_id = root.find(f"{{{ns}}}id")
oid = doc_id.get("root") if doc_id is not None else "(not found)"
print(f"  OID: {oid}")

# 3. Save to file
output_file = "helloworld_output.txt"
with open(output_file, "w") as f:
    f.write(f"s3_path: s3://{config['bucket']}/{config['key']}\n")
    f.write(f"oid: {oid}\n")
print(f"  Saved to {output_file}")
print("Done.")
