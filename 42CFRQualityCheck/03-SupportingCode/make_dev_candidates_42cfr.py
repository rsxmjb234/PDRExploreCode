"""
make_dev_candidates_42cfr.py — Build DEV Candidates CSV from S3
================================================================

Lists all CCD files under s3://nyec.ccda.learning/42CFRStyleCCDs/
and writes a candidates CSV for the 42 CFR scoring pipeline.

This gives us "known positives" for Phase 1 calibration — documents
we expect to score as CANDIDATE - HIGH.

Output: ../05-Candidates/DEV-42CFR-CandidateS3Paths.csv

Usage:
    python make_dev_candidates_42cfr.py
"""

import boto3
import csv
import os

# ============================================================================
# Configuration
# ============================================================================

AWS_PROFILE = "student1"
BUCKET = "nyec.ccda.learning"
PREFIX = "42CFRStyleCCDs/"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "05-Candidates")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "DEV-42CFR-CandidateS3Paths.csv")


def main():
    print("=" * 60)
    print("Build DEV Candidates CSV — 42 CFR Known Positives")
    print("=" * 60)
    print(f"  Bucket:  {BUCKET}")
    print(f"  Prefix:  {PREFIX}")
    print(f"  Profile: {AWS_PROFILE}")
    print(f"  Output:  {OUTPUT_FILE}")
    print()

    # Connect to S3
    session = boto3.Session(profile_name=AWS_PROFILE)
    s3 = session.client("s3")

    # List all objects under the prefix (paginated)
    objects = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            size = obj["Size"]

            # Skip zero-byte folder markers
            if size == 0:
                continue

            # Skip non-XML if present (optional filter)
            # Commenting out in case files don't have .xml extension
            # if not key.lower().endswith(".xml"):
            #     continue

            objects.append({
                "bucket": BUCKET,
                "key": key,
                "qe": "dev-42cfr",
                "assigning_authority": _parse_aa_from_key(key),
            })

    print(f"  Found {len(objects)} files under {PREFIX}")

    if not objects:
        print("  [WARNING] No files found. Check bucket/prefix/permissions.")
        return

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Write CSV
    fieldnames = ["bucket", "key", "qe", "assigning_authority"]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(objects)

    print(f"  [OK] Wrote {len(objects)} rows to:")
    print(f"       {OUTPUT_FILE}")
    print()
    print("  Next step: run the scoring pipeline in DEV mode against this CSV.")


def _parse_aa_from_key(key):
    """
    Try to extract an assigning authority from the S3 key.
    If the key has a subfolder structure like 42CFRStyleCCDs/someAA/file.xml,
    use the subfolder. Otherwise default to '42cfr-dev'.
    """
    # Remove the prefix
    relative = key.replace(PREFIX, "", 1)
    parts = relative.split("/")

    if len(parts) >= 2:
        # There's a subfolder — use it as the AA
        return parts[0]
    else:
        # Flat structure — use a default
        return "42cfr-dev"


if __name__ == "__main__":
    main()
