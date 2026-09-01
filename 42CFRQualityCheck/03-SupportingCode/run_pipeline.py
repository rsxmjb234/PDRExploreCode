"""
run_pipeline.py — 42 CFR Candidate Identification Pipeline Orchestrator
=========================================================================

End-to-end orchestrator that runs the full pipeline:
  Step 1: Read candidate CSV, skip already-processed files (restart-safe)
  Step 2: Score each CCD (download + parse + all checkers)
  Step 3: Aggregate results by source and location
  Step 4: Generate QE letters for candidates

Usage:
    python run_pipeline.py              (score + aggregate + letters)
    python run_pipeline.py --score-only (just score, no aggregate/letters)
    python run_pipeline.py --agg-only   (just aggregate + letters, skip scoring)
"""

import boto3
import csv
import json
import os
import shutil
import sys
import time


# ============================================================================
# Destination for the published "sample" QE letter used by the docs site
# (ExplainMedallionArch/explore/42cfr-sample-qe-letter.html).
#
# *** DEV ONLY ***  This is a documentation/demo convenience. It is never run
# under PROD, because PROD letters describe real sources and must not be copied
# into a public docs site. The sample is built from a KNOWN 42 CFR source with
# its routing status rewritten to "STANDARD" so it reads as a realistic
# "misrouted Part 2 source" scenario.
#
# Set to None to disable publishing entirely.
# ============================================================================

SAMPLE_LETTER_DEST = os.path.join(
    "..", "..", "..", "ExplainMedallionArch", "explore", "42cfr-sample-qe-letter.html"
)

# Routing status text to force onto the sample, so the demo shows a Part 2
# source sitting in the wrong (standard) pipeline.
SAMPLE_FORCED_ROUTING_STATUS = "GENERAL BUCKET (potentially misrouted)"


# ============================================================================
# CHOOSE YOUR PROFILE -- set to "DEV" or "PROD"
# ============================================================================

ACTIVE_PROFILE = "DEV"

# ============================================================================
# DEV PROFILE — known good, uses the learning bucket (42 CFR test CCDs)
# ============================================================================

DEV = {
    "aws_profile": "student1",
    "default_bucket": "nyec.ccda.learning",
    "allowed_buckets": ["nyec.ccda.learning"],
    "input_csv": os.path.join("..", "05-Candidates", "DEV-42CFR-CandidateS3Paths.csv"),
    "output_dir": os.path.join("..", "06-Results", "Output", "DEV"),
    "output_json_dir": os.path.join("..", "06-Results", "Output", "DEV", "scored_jsons"),
    "output_aggregate_csv": os.path.join("..", "06-Results", "Output", "DEV", "aggregate_results.csv"),
    "output_letters_dir": os.path.join("..", "06-Results", "Output", "DEV", "qe_letters"),
    "max_files": 5000,
}

# ============================================================================
# PROD PROFILE — multi-bucket, reads bucket from each CSV row
# ============================================================================

PROD = {
    "aws_profile": "student1",
    "default_bucket": None,  # PROD must have bucket in CSV
    "allowed_buckets": [
        "nyec-pdr-prod-healthix",
        "nyec-pdr-prod-hixny",
        "nyec-pdr-prod-rochester",
        "nyec-pdr-prod-hie-buffalo",
    ],
    "input_csv": os.path.join("..", "05-Candidates", "PROD-CandidateS3PathsForEvaluation.csv"),
    "output_dir": os.path.join("..", "06-Results", "Output", "PROD"),
    "output_json_dir": os.path.join("..", "06-Results", "Output", "PROD", "scored_jsons"),
    "output_aggregate_csv": os.path.join("..", "06-Results", "Output", "PROD", "aggregate_results.csv"),
    "output_letters_dir": os.path.join("..", "06-Results", "Output", "PROD", "qe_letters"),
    "max_files": 30000,
}

# ============================================================================


def _get_config():
    """Return the active profile dict."""
    if ACTIVE_PROFILE == "DEV":
        return DEV
    elif ACTIVE_PROFILE == "PROD":
        return PROD
    else:
        raise ValueError(f"Unknown ACTIVE_PROFILE: {ACTIVE_PROFILE}. Use 'DEV' or 'PROD'.")


# Push into config module so checkers/aggregator can read thresholds from there
import run_pipeline_config
run_pipeline_config.ACTIVE_PROFILE = ACTIVE_PROFILE

from run_pipeline_config import FLUSH_EVERY, CFR42_BUCKET_MARKERS
from score_ccd import score_one_ccd
from aggregate_sources import aggregate
from generate_qe_letters import generate_letters, render_sample_letter


def main():
    # Auto-set working directory to the folder this script lives in
    # (so relative paths work regardless of where you run it from)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    cfg = _get_config()

    print()
    print("=" * 70)
    print(f"  42 CFR Part 2 — Candidate Identification Pipeline")
    print(f"  *** RUNNING AS: {ACTIVE_PROFILE} ***")
    print("=" * 70)
    print(f"  AWS Profile:  {cfg['aws_profile']}")
    print(f"  Input CSV:    {cfg['input_csv']}")
    print(f"  Output dir:   {cfg['output_dir']}")
    print(f"  Max files:    {cfg['max_files']}")
    print(f"  Flush every:  {FLUSH_EVERY}")
    print("=" * 70)
    print(f"  To switch: change ACTIVE_PROFILE at the top of this file")
    print("=" * 70)
    print()

    # Parse CLI flags
    score_only = "--score-only" in sys.argv
    agg_only = "--agg-only" in sys.argv

    # -----------------------------------------------------------------------
    # Step 1+2: Score CCDs (unless --agg-only)
    # -----------------------------------------------------------------------
    if not agg_only:
        _run_scoring(cfg)

    # -----------------------------------------------------------------------
    # Step 3: Aggregate (unless --score-only)
    # -----------------------------------------------------------------------
    if not score_only:
        print()
        print("-" * 70)
        print("STEP 3: Aggregating results by source and location...")
        print("-" * 70)
        aggregate(cfg["output_json_dir"], cfg["output_aggregate_csv"])

        # -------------------------------------------------------------------
        # Step 4: Generate QE letters
        # -------------------------------------------------------------------
        print()
        print("-" * 70)
        print("STEP 4: Generating QE letters for candidates...")
        print("-" * 70)
        stats_json = cfg["output_aggregate_csv"].replace(".csv", "_gen_pop_stats.json")
        generated_letters = generate_letters(
            cfg["output_aggregate_csv"], stats_json, cfg["output_letters_dir"]
        )

        # -------------------------------------------------------------------
        # Step 5: Publish one letter as the docs-site sample (DEV ONLY)
        # -------------------------------------------------------------------
        print()
        print("-" * 70)
        print("STEP 5: Publishing sample QE letter to the docs site (DEV only)...")
        print("-" * 70)
        if ACTIVE_PROFILE == "DEV":
            _publish_sample_letter(generated_letters)
        else:
            print(f"  [SKIP] Profile is {ACTIVE_PROFILE}. Sample publishing only runs in DEV.")

    print()
    print("=" * 70)
    print("Pipeline complete.")
    print("=" * 70)


def _publish_sample_letter(generated_letters):
    """DEV ONLY. Publish a realistic sample QE letter to the docs site.

    Picks a candidate that is a genuine 42 CFR source, then re-renders its
    letter with the routing status forced to "standard" — so the docs site
    demonstrates the scenario we care about: a Part 2 source that landed in
    the wrong (non-protected) pipeline.
    """
    if not SAMPLE_LETTER_DEST:
        print("  [SKIP] SAMPLE_LETTER_DEST is not set.")
        return

    if not generated_letters:
        print("  [SKIP] No letters were generated, nothing to publish as sample.")
        return

    dest = os.path.abspath(SAMPLE_LETTER_DEST)
    dest_dir = os.path.dirname(dest)
    if not os.path.isdir(dest_dir):
        print(f"  [SKIP] Destination folder not found: {dest_dir}")
        print(f"         (Expected the ExplainMedallionArch docs project alongside PDRExploreCode.)")
        return

    # Pick a candidate that is genuinely a 42 CFR source.
    chosen = _pick_known_42cfr_candidate(generated_letters)
    if chosen is None:
        print("  [SKIP] No known-42-CFR candidate found among the letters; "
              "not publishing a sample (a real misrouted scenario is required).")
        return

    org = chosen["source"].get("custodian_org_name") or chosen["source"].get("assigning_authority")
    try:
        render_sample_letter(chosen, dest, force_routing_status=SAMPLE_FORCED_ROUTING_STATUS)
        print(f"  [OK] Published sample letter (routing forced to standard):")
        print(f"       source: {org}")
        print(f"       to:     {dest}")
    except OSError as e:
        print(f"  [ERROR] Could not write sample letter: {e}")


# Path/key markers that identify DEV known-Part-2 test data. The DEV candidate
# set lives under a "42CFRStyleCCDs/" prefix — every file there is a genuine
# 42 CFR source, which is exactly what we want for the sample.
KNOWN_42CFR_PATH_MARKERS = ["42cfrstyleccds", "42cfr", "part2", "cfr-part-2"]


def _pick_known_42cfr_candidate(generated_letters):
    """Return the letter entry for a candidate whose data actually sits in the
    42 CFR pipeline (i.e. a genuine Part 2 source). Prefers the highest-scoring
    such source. Returns None if none are found."""
    markers = set(m.lower() for m in (list(CFR42_BUCKET_MARKERS) + KNOWN_42CFR_PATH_MARKERS))

    def is_42cfr(entry):
        src = entry["source"]
        # A source already flagged as being in the 42 CFR bucket by the
        # aggregator's routing check is a genuine Part 2 source.
        routing = src.get("routing_status", "").lower()
        if "42 cfr" in routing or "segregated" in routing:
            return True
        # Otherwise, check the representative path/bucket/AA against the markers
        # (in DEV the path prefix "42CFRStyleCCDs/" is the reliable signal).
        blob = (src.get("path", "") + " " + src.get("bucket", "") + " "
                + src.get("assigning_authority", "")).lower()
        return any(m in blob for m in markers)

    known = [e for e in generated_letters if is_42cfr(e)]
    if not known:
        return None

    # Prefer the strongest candidate for the most compelling sample.
    known.sort(key=lambda e: float(e["source"].get("source_score", 0)), reverse=True)
    return known[0]


def _run_scoring(cfg):
    """Score CCDs from the candidate CSV."""
    print("-" * 70)
    print("STEP 1: Loading candidate CSV and checking for already-processed files...")
    print("-" * 70)

    # Ensure output directories exist
    os.makedirs(cfg["output_json_dir"], exist_ok=True)

    # Load already-processed paths (restart support)
    already_processed = _load_already_processed(cfg["output_json_dir"])
    print(f"  Already processed: {len(already_processed)} files (will skip)")

    # Load candidate list
    candidates = _load_candidates(cfg["input_csv"], cfg["default_bucket"])
    print(f"  Candidates in CSV: {len(candidates)}")

    # Filter to unprocessed only
    to_process = [
        c for c in candidates
        if f"s3://{c['bucket']}/{c['key']}" not in already_processed
    ]
    print(f"  Remaining to process: {len(to_process)}")

    # Apply max_files limit
    max_files = cfg["max_files"]
    if len(to_process) > max_files:
        to_process = to_process[:max_files]
        print(f"  Limited to max_files: {max_files}")

    if not to_process:
        print("  [OK] All candidates already scored. Nothing new to process.")
        print("       (Delete scored_jsons/ to re-process from scratch.)")
        return

    # Validate buckets
    allowed = cfg["allowed_buckets"]
    if allowed:
        to_process = [c for c in to_process if c["bucket"] in allowed]
        print(f"  After bucket filter: {len(to_process)}")

    # -----------------------------------------------------------------------
    # Step 2: Score each CCD
    # -----------------------------------------------------------------------
    print()
    print("-" * 70)
    print(f"STEP 2: Scoring {len(to_process)} CCDs...")
    print("-" * 70)

    session = boto3.Session(profile_name=cfg["aws_profile"])
    s3 = session.client("s3")

    results_buffer = []
    total = len(to_process)
    start_time = time.time()
    errors = 0

    for i, candidate in enumerate(to_process, 1):
        bucket = candidate["bucket"]
        key = candidate["key"]
        qe = candidate.get("qe", "")
        aa = candidate.get("assigning_authority", "")

        # Score
        result = score_one_ccd(s3, bucket, key, qe, aa)
        results_buffer.append(result)

        if result.get("error"):
            errors += 1

        # Progress reporting
        if i % 50 == 0 or i == total:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate if rate > 0 else 0
            print(f"  [{i:,}/{total:,}] "
                  f"{rate:.1f} files/sec | "
                  f"errors: {errors} | "
                  f"ETA: {remaining/60:.1f} min")

        # Flush to disk periodically
        if len(results_buffer) >= FLUSH_EVERY:
            _flush_results(results_buffer, cfg["output_json_dir"])
            results_buffer = []

    # Final flush
    if results_buffer:
        _flush_results(results_buffer, cfg["output_json_dir"])

    elapsed_total = time.time() - start_time
    print()
    print(f"  Scoring complete: {total} files in {elapsed_total/60:.1f} min")
    print(f"  Errors: {errors}")


def _load_candidates(csv_path, default_bucket):
    """Load candidate CSV. Each row needs at minimum a 'key' column."""
    candidates = []

    if not os.path.isfile(csv_path):
        print(f"[ERROR] Candidate CSV not found:")
        print(f"        {os.path.abspath(csv_path)}")
        print()
        print("  Make sure you are running this script from the 03-SupportingCode/ folder.")
        print("  Or run: python make_dev_candidates_42cfr.py  to create the CSV first.")
        return candidates

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("key", "").strip()
            if not key:
                continue

            bucket = row.get("bucket", "").strip()
            if not bucket and default_bucket:
                bucket = default_bucket

            candidates.append({
                "bucket": bucket,
                "key": key,
                "qe": row.get("qe", "").strip(),
                "assigning_authority": row.get("assigning_authority", "").strip(),
            })

    return candidates


def _load_already_processed(json_dir):
    """Load set of already-processed S3 paths from existing JSON output."""
    processed = set()

    if not os.path.isdir(json_dir):
        return processed

    for filename in os.listdir(json_dir):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(json_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        path = rec.get("path", "")
                        if path:
                            processed.add(path)
                    except json.JSONDecodeError:
                        pass
        except IOError:
            pass

    return processed


def _flush_results(results, json_dir):
    """Append results to an NDJSON file (one line per record)."""
    # Use a single NDJSON file, append mode
    output_file = os.path.join(json_dir, "scored_results.json")
    with open(output_file, "a", encoding="utf-8") as f:
        for rec in results:
            f.write(json.dumps(rec, default=str) + "\n")


# ============================================================================
# Entry point
# ============================================================================
if __name__ == "__main__":
    main()
