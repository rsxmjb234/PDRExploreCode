"""
helloworld.py — "Hello World" for PDR S3 Access

PURPOSE:
    Confirm that the AWS CLI is working and that your account can read
    from the PDR S3 bucket. This is purely a connectivity test.

    If this script prints a patient's last name from the CCD, you're good to go.

HOW TO USE:
    1. Pick a profile below: "DEV" or "PROD"
    2. Set ACTIVE_PROFILE to "DEV" or "PROD"
    3. Run: python helloworld.py
    4. If you see a patient last name, your access is confirmed.

PROFILES:
    DEV  — Uses the learning bucket (nyec.ccda.learning) with a known
           Synthea test file. Known good, used for development.

    PROD — Dan: this is yours. Set your AWS CLI profile, bucket, and a
           known CCD key. Once this prints a last name, you're confirmed
           working in PROD (or QA — substitute as appropriate).
"""

import boto3
import xml.etree.ElementTree as ET
import io

# =============================================================================
# CHOOSE YOUR PROFILE — set to "DEV" or "PROD"
# =============================================================================

ACTIVE_PROFILE = "DEV"

# =============================================================================
# DEV PROFILE — known good, uses the learning bucket
# =============================================================================
DEV = {
    "aws_profile": "student1",
    "bucket": "nyec.ccda.learning",
    "key": "RawCCDs/Aaron697_Schiller186_d5d96071-fdff-d902-f487-de1a278fd864.xml",
}

# =============================================================================
# PROD PROFILE — Dan: fill these in for your environment
#   - aws_profile: your AWS CLI profile name (check `aws configure list-profiles`)
#   - bucket: the PDR prod bucket (or QA bucket if testing there)
#   - key: a known CCD file path in that bucket
# =============================================================================
PROD = {
    "aws_profile": "dan-prod",                # Dan: change to your CLI profile
    "bucket": "nyec-pdr-prod-hixny",          # Dan: change to QA bucket if needed
    "key": "1003861782/ccd/2026/Jul/06/15/hixny_1003861782_59041906c701c0a83ac4ca3781382549a9569358a4bddab470f413fef9fb56a7_2.16.840.1.113883.3.227.3245.1.1.c1be4578.xml",
}

# =============================================================================
# End of configuration
# =============================================================================


def main():
    # Select the active config
    if ACTIVE_PROFILE.upper() == "PROD":
        config = PROD
    else:
        config = DEV

    aws_profile = config["aws_profile"]
    bucket = config["bucket"]
    key = config["key"]

    print("=" * 55)
    print("PDR Hello World — S3 Connectivity Test")
    print("=" * 55)
    print(f"  Active profile: {ACTIVE_PROFILE}")
    print(f"  AWS CLI profile: {aws_profile}")
    print(f"  Bucket:  {bucket}")
    print(f"  Key:     {key[:70]}...")
    print()

    # Connect to S3
    print("Connecting to S3...")
    session = boto3.Session(profile_name=aws_profile)
    s3 = session.client("s3")

    # Download the CCD
    print("Downloading CCD file...")
    response = s3.get_object(Bucket=bucket, Key=key)
    xml_bytes = response["Body"].read()
    print(f"  Downloaded {len(xml_bytes):,} bytes.")

    # Parse XML and find the patient's last name
    print("Parsing XML for patient last name...")
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()

    ns = "urn:hl7-org:v3"
    family_el = root.find(
        f".//{{{ns}}}recordTarget/{{{ns}}}patientRole/{{{ns}}}patient/{{{ns}}}name/{{{ns}}}family"
    )

    if family_el is not None and family_el.text:
        last_name = family_el.text.strip()
        print()
        print(f"  SUCCESS! Patient last name: {last_name}")
        print()
        print(f"  Your AWS access is working ({ACTIVE_PROFILE}). You can read from the bucket.")
    else:
        print()
        print("  WARNING: Connected to S3 and downloaded the file,")
        print("  but could not find a patient last name in the XML.")
        print("  The file may have a different structure. But S3 access works!")

    print()
    print("=" * 55)


if __name__ == "__main__":
    main()
