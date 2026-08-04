"""
run_PROD_full_pipeline.py — PROD run of the CCD coding quality pipeline

PREREQUISITES:
  1. DEV pipeline must have passed validation first (run DEV pipeline, confirm 15/15 pass)
  2. Athena candidate CSV must exist (exported from findcandidatesforexplore.sql)
  3. AWS CLI "default" profile must have access to all PROD buckets

This script:
  1. Reads the PROD candidates CSV (from Athena export)
  2. Downloads each CCD from its S3 bucket
  3. Scores all 14 segments for coding quality
  4. Writes one JSON per CCD to PROD-Output/scored_results/
  5. Generates HTML reports (per-QE + summary)

Unlike DEV, there is NO test data generation or validation step.
The scorer has already been validated in DEV. This just runs it at scale.
"""

import os
import subprocess
import sys
import time

# =============================================================================
# PROD CONFIGURATION
# =============================================================================

# AWS CLI profile for PROD S3 access
AWS_PROFILE = "default"

# Maximum files to process per run (set to None for unlimited)
MAX_FILES = 30000

# Input: Athena candidate CSV (exported from findcandidatesforexplore.sql)
# Must have columns: assigning_authority, qe, bucket, key, size, last_modified
# For first run: using the same candidates as findandsaveEHRfromCCD-EntireCCD.py
CANDIDATES_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "Export-Athena-10-ccds-per-source.csv"
)

# Allowed PROD buckets (same as findandsaveEHRfromCCD-EntireCCD.py)
ALLOWED_BUCKETS = [
    "nyec-pdr-prod-hixny",
    "nyec-pdr-prod-hixny-part2",
    "nyec-pdr-prod-techbd",
    "nyec-pdr-prod-techbd-part2",
    "nyec-pdr-prod-healtheconnections",
    "nyec-pdr-prod-healtheconnections-part2",
    "nyec-pdr-prod-rochester",
    "nyec-pdr-prod-rochester-part2",
    "nyec-pdr-prod-bronx",
    "nyec-pdr-prod-bronx-part2",
    "nyec-pdr-prod-healthix",
    "nyec-pdr-prod-healthix-part2",
]

# Output directory
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "PROD-Output"
)

SCORED_DIR = os.path.join(OUTPUT_DIR, "scored_results")
REPORTS_DIR = os.path.join(OUTPUT_DIR, "reports")

# =============================================================================
# All paths relative to this script's directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    print()
    print("#" * 75)
    print("#  CCD Coding Quality — PROD PIPELINE")
    print("#" * 75)
    print()
    print("CONFIGURATION:")
    print(f"  AWS Profile:     {AWS_PROFILE}")
    print(f"  Candidates CSV:  {CANDIDATES_CSV}")
    print(f"  Max files/run:   {MAX_FILES}")
    print(f"  Allowed buckets: {len(ALLOWED_BUCKETS)}")
    print(f"  Output dir:      {OUTPUT_DIR}")
    print()

    # Check candidates CSV exists
    candidates_path = CANDIDATES_CSV
    if not os.path.exists(candidates_path):
        # Try relative to BASE_DIR as fallback
        candidates_path = os.path.join(BASE_DIR, os.path.basename(CANDIDATES_CSV))
    
    if not os.path.exists(candidates_path):
        print(f"ERROR: Candidates CSV not found: {candidates_path}")
        print()
        print("To create it:")
        print("  1. Run findcandidatesforexplore.sql in Athena")
        print("  2. Export results as CSV")
        print(f"  3. Save as: {candidates_path}")
        print()
        print("Required columns: assigning_authority, qe, bucket, key, size, last_modified")
        sys.exit(1)

    # Create output directories
    os.makedirs(SCORED_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # =========================================================================
    # STEP 1: Score all PROD candidates
    # =========================================================================
    print()
    print(f"{'='*75}")
    print("STEP 1: Score PROD candidate CCDs")
    print(f"{'='*75}")
    print()

    # Use the scorer in batch mode against PROD candidates
    # The scorer reads the CSV, downloads from S3 per-row bucket, scores, writes JSON
    print(f"  Running scorer against: {CANDIDATES_CSV}")
    print(f"  Output: {SCORED_DIR}")
    print()

    # Import and run the scorer directly with PROD config
    sys.path.insert(0, BASE_DIR)
    import score_ccd_coding_quality as scorer
    import csv
    import json
    import boto3
    import xml.etree.ElementTree as ET
    import io

    # Read candidates
    with open(candidates_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header_map = {name.strip().lower(): name for name in reader.fieldnames}
        key_col = header_map.get("key")
        bucket_col = header_map.get("bucket")
        qe_col = header_map.get("qe")
        aa_col = header_map.get("assigning_authority")

        candidates = []
        for row in reader:
            key = (row.get(key_col) or "").strip()
            bucket = (row.get(bucket_col) or "").strip()
            if key and bucket and key.lower().endswith(".xml"):
                candidates.append({
                    "key": key,
                    "bucket": bucket,
                    "qe": (row.get(qe_col) or "").strip(),
                    "assigning_authority": (row.get(aa_col) or "").strip(),
                    "path": f"s3://{bucket}/{key}",
                })

    print(f"  Found {len(candidates)} candidates in CSV")

    # Check which S3 paths are already scored (restart + dedup protection)
    # We track by full S3 path to ensure the same file is NEVER processed twice
    already_scored_paths = set()
    if os.path.exists(SCORED_DIR):
        for f in os.listdir(SCORED_DIR):
            if f.endswith("_scored.json"):
                try:
                    with open(os.path.join(SCORED_DIR, f), "r", encoding="utf-8") as jf:
                        scored = json.load(jf)
                    s3_path = scored.get("source", {}).get("path", "")
                    if s3_path:
                        already_scored_paths.add(s3_path)
                except Exception:
                    pass

    # Filter to unprocessed candidates only (dedup by S3 path)
    to_process = []
    seen_paths = set()  # Also catch duplicates WITHIN the CSV itself
    for c in candidates:
        if c["path"] in already_scored_paths:
            continue  # Already scored in a previous run
        if c["path"] in seen_paths:
            continue  # Duplicate row in the CSV
        seen_paths.add(c["path"])
        
        # Build output filename
        output_filename = os.path.basename(c["key"]).replace(".xml", "_scored.json")
        output_filename = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in output_filename)
        c["output_filename"] = output_filename
        to_process.append(c)

    # Apply max_files limit AFTER dedup
    if MAX_FILES and len(to_process) > MAX_FILES:
        to_process = to_process[:MAX_FILES]

    skipped = len(candidates) - len(to_process)
    if skipped > 0:
        print(f"  Skipping {skipped} already-scored or duplicate files")
    print(f"  Processing {len(to_process)} candidates this run (max_files={MAX_FILES})")
    print()

    if not to_process:
        print("  All candidates already scored! Nothing to do.")
    else:
        # Connect to S3
        session = boto3.Session(profile_name=AWS_PROFILE)
        s3 = session.client("s3")

        run_start = time.time()

        for idx, candidate in enumerate(to_process, 1):
            file_start = time.time()
            filename = os.path.basename(candidate["key"])

            print(f"  [{idx:4d}/{len(to_process)}] {filename[:60]}")

            # Download
            try:
                response = s3.get_object(Bucket=candidate["bucket"], Key=candidate["key"])
                xml_bytes = response["Body"].read()
            except Exception as e:
                print(f"    [ERROR] Download: {e}")
                continue

            # Score (write to temp file for the scorer)
            try:
                temp_path = os.path.join(SCORED_DIR, "_temp_scoring.xml")
                with open(temp_path, "wb") as tf:
                    tf.write(xml_bytes)

                source_metadata = {
                    "assigning_authority": candidate["assigning_authority"],
                    "qe": candidate["qe"],
                    "bucket": candidate["bucket"],
                    "key": candidate["key"],
                    "path": candidate["path"],
                }

                result = scorer.score_ccd(temp_path, source_metadata=source_metadata)

                # Add timing
                elapsed_ms = int((time.time() - file_start) * 1000)
                result["processing_time_ms"] = elapsed_ms
                result["file_size_bytes"] = len(xml_bytes)

                # Write scored JSON
                output_path = os.path.join(SCORED_DIR, candidate["output_filename"])
                with open(output_path, "w", encoding="utf-8") as jf:
                    json.dump(result, jf, indent=2)

                # Clean temp
                os.remove(temp_path)

                std = result["summary"]["standard_count"]
                total = result["summary"]["total_elements"]
                pct = int(100 * std / total) if total > 0 else 0
                print(f"    {pct}% standard ({elapsed_ms}ms)")

            except Exception as e:
                print(f"    [ERROR] Scoring: {e}")
                continue

        total_time = int(time.time() - run_start)
        avg_ms = int(total_time * 1000 / len(to_process)) if to_process else 0
        print()
        print(f"  Scored {len(to_process)} files in {total_time}s (avg {avg_ms}ms/file)")

    # =========================================================================
    # STEP 2: Generate HTML reports
    # =========================================================================
    print()
    print(f"{'='*75}")
    print("STEP 2: Generate HTML reports")
    print(f"{'='*75}")
    print()

    report_script = os.path.join(BASE_DIR, "generate_report.py")
    result = subprocess.run(
        [sys.executable, report_script, "--output-dir", "PROD-Output"],
        cwd=BASE_DIR,
        capture_output=False,
    )
    if result.returncode != 0:
        print("  [WARNING] Report generation had issues")
    else:
        print("  [OK] Reports generated")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print()
    print("#" * 75)
    print("#  PROD PIPELINE COMPLETE")
    print("#" * 75)
    print()
    print(f"  Scored results: {SCORED_DIR}")
    print(f"  Reports:        {REPORTS_DIR}")
    print()


if __name__ == "__main__":
    main()
