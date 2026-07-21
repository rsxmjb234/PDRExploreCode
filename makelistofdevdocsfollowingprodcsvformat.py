"""
makelistofdevdocsfollowingprodcsvformat.py

Lists up to 2000 XML files from the DEV S3 bucket and writes them
to a CSV that mirrors the PROD format:

    assigning_authority, qe, data_type, key, size, last_modified

This allows findandsaveEHRfromCCD.py to be driven from the same
CSV format whether in DEV or PROD.

In PROD this is done with a SQL query, because in PROD we have S3 inventory
In DEV we don't have S3 inventory so we just scan the S3 by hand , loop through and make a CSV

"""

import boto3
import csv
import os

# Configuration
BUCKET = "nyec.ccda.learning"
PREFIX = "RawCCDs/"
PROFILE = "student1"
MAX_FILES = 2000
OUTPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "DEV-upto2000documentsfromdevbucket.csv"
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

    # Write CSV in the same format as the PROD file
    print(f"Writing to: {OUTPUT_CSV}")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(["assigning_authority", "qe", "data_type", "key", "size", "last_modified"])

        for item in xml_files:
            key = item["key"]
            # In DEV, we don't have the same path structure as PROD,
            # so we derive what we can:
            #   assigning_authority = "(dev)" placeholder
            #   qe = "(dev)" placeholder
            #   data_type = "CCD"
            #   key = the S3 key (relative to bucket, same as PROD)
            #   size = file size
            #   last_modified = timestamp
            writer.writerow([
                "(dev)",       # assigning_authority - unknown until we parse the XML
                "(dev)",       # qe - unknown until we parse the XML
                "CCD",         # data_type
                key,           # full S3 key
                item["size"],
                item["last_modified"],
            ])

    print(f"Done! Wrote {len(xml_files)} rows.")


if __name__ == "__main__":
    main()
