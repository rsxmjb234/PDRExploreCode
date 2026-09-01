"""
make_dev_candidates_42cfr.py — Build DEV Candidates CSV (Unified Format)
=========================================================================

Lists all CCD files from BOTH DEV folders:
  s3://nyec.ccda.learning/42CFRStyleCCDs/        (known Part 2 sources)
  s3://nyec.ccda.learning/42CFRTesting-Not42CFR/  (known non-Part 2 sources)

Downloads each CCD and parses the assigningAuthorityName field from the
document's first <id> element to get the real QE and Assigning Authority:
  assigningAuthorityName="qe|assigning_authority"
  e.g., "rochester|FLACRA" or "bronx|START TREATMENT AND RECOVERY CENTERS"

Produces a SINGLE CSV with the same columns that PROD uses:
  bucket, key, qe, assigning_authority, part2

Output: ../05-Candidates/DEV-42CFR-CandidateS3Paths.csv

Usage:
    python make_dev_candidates_42cfr.py
"""

import boto3
import csv
import os
import xml.etree.ElementTree as ET

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
    },
    {
        "prefix": "42CFRTesting-Not42CFR/",
        "part2": "No",
    },
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "05-Candidates")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "DEV-42CFR-CandidateS3Paths.csv")

# CDA namespace
CDA_NS = "urn:hl7-org:v3"


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
        print(f"    {pool['prefix']:30s} part2={pool['part2']}")
    print()

    # Connect to S3
    session = boto3.Session(profile_name=AWS_PROFILE)
    s3 = session.client("s3")

    all_rows = []

    for pool in POOLS:
        prefix = pool["prefix"]
        part2 = pool["part2"]

        print(f"  Listing {prefix}...", end=" ")
        keys = _list_xml_objects(s3, BUCKET, prefix)
        print(f"{len(keys)} XML files")

        print(f"  Parsing assigningAuthorityName from each CCD...")
        parsed = 0
        failed = 0

        for key in keys:
            qe, aa = _get_qe_aa_from_ccd(s3, BUCKET, key)

            if qe and aa:
                parsed += 1
            else:
                failed += 1
                # Fall back to placeholder if parsing fails
                qe = qe or "unknown"
                aa = aa or "unknown"

            all_rows.append({
                "bucket": BUCKET,
                "key": key,
                "qe": qe,
                "assigning_authority": aa,
                "part2": part2,
            })

            # Progress
            total_done = parsed + failed
            if total_done % 50 == 0:
                print(f"    [{total_done}/{len(keys)}] parsed={parsed} failed={failed}")

        print(f"    Done: {parsed} parsed, {failed} failed")
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


def _list_xml_objects(s3, bucket, prefix):
    """List all non-zero-byte XML files under a prefix (paginated)."""
    objects = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            size = obj["Size"]

            if size == 0:
                continue
            if not key.lower().endswith(".xml"):
                continue

            objects.append(key)

    return objects


def _get_qe_aa_from_ccd(s3, bucket, key):
    """
    Download a CCD and parse the assigningAuthorityName from the first <id>.
    Format: "qe|assigning_authority" (e.g., "rochester|FLACRA")
    Returns: (qe, assigning_authority) tuple, or ("", "") on failure.
    """
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read()
        root = ET.fromstring(body.decode("utf-8", errors="replace"))

        ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

        # Find the first <id> element with assigningAuthorityName
        for el in root.iter(f"{{{ns}}}id" if ns else "id"):
            aan = el.get("assigningAuthorityName", "")
            if aan and "|" in aan:
                parts = aan.split("|", 1)
                qe = parts[0].strip()
                aa = parts[1].strip()
                return (qe, aa)

        return ("", "")

    except Exception:
        return ("", "")


if __name__ == "__main__":
    main()
