"""
DEV-makelistofdevdocsfollowingprodcsvformat.py

Lists up to 2000 XML files from the DEV S3 bucket and writes them
to a CSV that mirrors the PROD Athena export format
(output of findcandidatesforexplore.sql):

    assigning_authority, qe, bucket, key, size, last_modified

This allows findandsaveEHRfromCCD-EntireCCD.py to process DEV and PROD CSVs
using the same read_input_csv_file() logic — no code changes needed.

Key columns the processing script needs:
  - "bucket" — which S3 bucket the file is in
  - "key" — the S3 object key (path within bucket)
  - "qe" — QE name (optional, for context)
  - "assigning_authority" — source system ID (optional, for context)

In PROD: findcandidatesforexplore.sql produces this CSV from Athena/S3 inventory.
In DEV: This script scans S3 directly and builds the same format by hand.

Note: DEV data is all Synthea (synthetic). The EHR classifier will tag
everything as "Synthea" — that's correct behavior for test data.
"""

import boto3
import csv
import os

# Configuration
BUCKET = "nyec.ccda.learning"
PREFIX = "RawCCDs/"
PROFILE = "student1"
MAX_FILES = 5000
OUTPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "DEV-CandidateS3PathsForEvaluation.csv"
)


def main():
    print(f"Connecting to S3 with profile '{PROFILE}'...")
    session = boto3.Session(profile_name=PROFILE)
    s3 = session.client("s3")

    print(f"Listing up to {MAX_FILES} XML files in s3://{BUCKET}/{PREFIX}...")
    xml_files = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(".xml"):
                xml_files.append({
                    "key": key,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].strftime("%Y-%m-%d %H:%M:%S"),
                })
                if len(xml_files) >= MAX_FILES:
                    break
        if len(xml_files) >= MAX_FILES:
            break

    print(f"Found {len(xml_files)} XML files.")

    # Write CSV matching PROD Athena export format (findcandidatesforexplore.sql output)
    # Columns: assigning_authority, qe, bucket, key, size, last_modified
    print(f"Writing to: {OUTPUT_CSV}")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow([
            "assigning_authority",
            "qe",
            "bucket",
            "key",
            "size",
            "last_modified",
        ])

        for item in xml_files:
            writer.writerow([
                "(dev)",           # assigning_authority — placeholder for DEV
                "(dev)",           # qe — placeholder for DEV
                BUCKET,            # bucket — required by read_input_csv_file()
                item["key"],       # key — S3 object path
                item["size"],      # size
                item["last_modified"],  # last_modified
            ])

    print(f"Done! Wrote {len(xml_files)} rows.")
    print(f"  Format matches PROD Athena export (has 'bucket' column)")


if __name__ == "__main__":
    main()
