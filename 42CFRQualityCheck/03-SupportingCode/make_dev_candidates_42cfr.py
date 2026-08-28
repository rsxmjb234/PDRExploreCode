"""
make_dev_candidates_42cfr.py — Build DEV Candidates CSV (Unified Format)
=========================================================================

Lists all CCD files from BOTH DEV folders:
  s3://nyec.ccda.learning/42CFRStyleCCDs/   (known Part 2 sources)
  s3://nyec.ccda.learning/RawCCDs/          (known non-Part 2 sources)

Produces a SINGLE CSV with the same columns that PROD uses:
  bucket, key, qe, assigning_authority, part2

The 'part2' column = "Yes" for 42CFRStyleCCDs, "No" for RawCCDs.
This mirrors the PROD Athena query output (ExampleOfHowDataPathsAreExpressedInPDR.csv)
so the pipeline and test harness work identically in both landscapes.

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

# The two pools — same bucket, different prefixes
POOLS = [
    {
        "prefix": "42CFRStyleCCDs/",
        "part2": "Yes",
        "qe": "dev-42cfr",
    },
    {
        "prefix": "RawCCDs/",
        "part2": "No",
        "qe": "dev-general",
    },
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "05-Candidates")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "DEV-42CFR-CandidateS3Paths.csv")


def main():
    # Auto-set working directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    print("=" * 60)
    print("Build DEV Candidates CSV — Unified Format")
    print("=" * 60)
    print(f"  Bucket:  {BUCKET}")
    print(f"  Profile: {AWS_PROFILE}")
    print(f"  Output:  {OUTPUT_FILE}")
    print()
    print("  Pools:")
    for pool in POOLS:
        print(f"    {pool['prefix']:25s} part2={pool['part2']}")
    print()

    # Connect to S3
    session = boto3.Session(profile_name=AWS_PROFILE)
    s3 = session.client("s3")

    all_rows = []

    for pool in POOLS:
        prefix = pool["prefix"]
        part2 = pool["part2"]
        qe = pool["qe"]

        print(f"  Listing {prefix}...", end=" ")

        objects = _list_objects(s3, BUCKET, prefix)
        print(f"{len(objects)} files")

        for obj_key in objects:
            all_rows.append({
                "bucket": BUCKET,
                "key": obj_key,
                "qe": qe,
                "assigning_authority": _parse_aa_from_key(obj_key, prefix),
                "part2": part2,
            })

    print()
    print(f"  Total rows: {len(all_rows)}")

    if not all_rows:
        print("  [WARNING] No files found. Check bucket/prefix/permissions.")
        return

    # Summary by pool
    yes_count = sum(1 for r in all_rows if r["part2"] == "Yes")
    no_count = sum(1 for r in all_rows if r["part2"] == "No")
    print(f"    Part 2 = Yes: {yes_count}")
    print(f"    Part 2 = No:  {no_count}")
    print()

    # Distinct AAs
    yes_aas = set(r["assigning_authority"] for r in all_rows if r["part2"] == "Yes")
    no_aas = set(r["assigning_authority"] for r in all_rows if r["part2"] == "No")
    print(f"  Distinct AAs (Part 2 = Yes): {len(yes_aas)}")
    print(f"  Distinct AAs (Part 2 = No):  {len(no_aas)}")
    print()

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Write CSV — same column order as PROD reference
    fieldnames = ["bucket", "key", "qe", "assigning_authority", "part2"]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"  [OK] Wrote {len(all_rows)} rows to:")
    print(f"       {OUTPUT_FILE}")
    print()
    print("  This CSV has the same format as PROD (from Athena).")
    print("  Column 'part2' = ground truth for the test harness.")


def _list_objects(s3, bucket, prefix):
    """List all non-zero-byte objects under a prefix (paginated)."""
    objects = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            size = obj["Size"]

            # Skip zero-byte folder markers
            if size == 0:
                continue

            objects.append(key)

    return objects


def _parse_aa_from_key(key, prefix):
    """
    Try to extract an assigning authority from the S3 key.
    If the key has a subfolder structure like prefix/someAA/file.xml,
    use the subfolder. Otherwise derive from the prefix name.
    """
    relative = key.replace(prefix, "", 1)
    parts = relative.split("/")

    if len(parts) >= 2:
        # There's a subfolder — use it as the AA
        return parts[0]
    else:
        # Flat structure — derive from pool prefix
        if "42CFR" in prefix:
            return "42cfr-dev"
        else:
            return "rawccd-dev"


if __name__ == "__main__":
    main()
