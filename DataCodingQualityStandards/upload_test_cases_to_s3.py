"""
upload_test_cases_to_s3.py — Upload generated test CCDs to the DEV S3 test folder

Uploads all XML files from generated_test_cases/ to:
  s3://nyec.ccda.learning/TestDataForDeterminingLevelOfCodeSetQuality/

After upload, make_dev_candidates_csv.py can list them and produce the
candidate CSV that the batch scorer reads.
"""

import boto3
import os

AWS_PROFILE = "student1"
BUCKET = "nyec.ccda.learning"
S3_PREFIX = "TestDataForDeterminingLevelOfCodeSetQuality/"

LOCAL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "DEV-Output",
    "generated_test_cases"
)


def main():
    print(f"Uploading test cases to s3://{BUCKET}/{S3_PREFIX}")
    print(f"  Source: {LOCAL_DIR}")
    print()

    session = boto3.Session(profile_name=AWS_PROFILE)
    s3 = session.client("s3")

    xml_files = [f for f in os.listdir(LOCAL_DIR) if f.endswith(".xml")]
    print(f"  Found {len(xml_files)} XML files to upload")
    print()

    for idx, filename in enumerate(sorted(xml_files), 1):
        local_path = os.path.join(LOCAL_DIR, filename)
        s3_key = f"{S3_PREFIX}{filename}"
        s3.upload_file(local_path, BUCKET, s3_key)
        print(f"  [{idx:2d}/{len(xml_files)}] {filename}")

    print()
    print(f"Done! Uploaded {len(xml_files)} files.")
    print(f"  Location: s3://{BUCKET}/{S3_PREFIX}")
    print()
    print("Next: python make_dev_candidates_csv.py")


if __name__ == "__main__":
    main()
