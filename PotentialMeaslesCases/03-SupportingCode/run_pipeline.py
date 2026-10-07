"""
run_pipeline.py — Measles Candidate Detection Pipeline Orchestrator
=============================================================================

SCOPE FOR THIS PASS: CCD and TRN only (see
01-RequirementsAndPlans/measles-detection-technical-plan.md Section 2).
ADT and Lab/ORU are not scored — there is no ADT/lab candidate CSV read
here.

End-to-end orchestrator:
  Step 1: Read the CCD and TRN candidate CSVs, skip already-processed files
          (restart-safe, same pattern as findandsaveEHRfromCCD-EntireCCD.py)
  Step 2: Score each candidate file (download + parse + checker)
  Step 3: Aggregate results per patient (Output B)

Usage:
    python run_pipeline.py                (score + aggregate)
    python run_pipeline.py --score-only   (just score, no aggregate)
    python run_pipeline.py --agg-only     (just aggregate, skip scoring)
"""

import boto3
import csv
import os
import sys
import time

from config import get_config, FLUSH_EVERY, FINDINGS_FILENAME, PATIENT_CANDIDATES_FILENAME, ERRORS_FILENAME, SUMMARY_FILENAME
from score_candidate import score_one_candidate
from aggregate_candidates import aggregate


def main():
    # Auto-set working directory to the folder this script lives in
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    cfg = get_config()
    os.makedirs(cfg["output_dir"], exist_ok=True)

    findings_csv = os.path.join(cfg["output_dir"], FINDINGS_FILENAME)
    patient_csv = os.path.join(cfg["output_dir"], PATIENT_CANDIDATES_FILENAME)
    errors_log = os.path.join(cfg["output_dir"], ERRORS_FILENAME)
    summary_txt = os.path.join(cfg["output_dir"], SUMMARY_FILENAME)

    print()
    print("=" * 70)
    print("  Potential Measles Cases — Candidate Detection Pipeline")
    print("  SCOPE THIS PASS: CCD + TRN only (ADT and Lab/ORU are out)")
    print("=" * 70)
    print(f"  AWS Profile:  {cfg['aws_profile']}")
    print(f"  CCD input:    {cfg['ccd_input_csv']}")
    print(f"  TRN input:    {cfg['trn_input_csv']}")
    print(f"  Output dir:   {cfg['output_dir']}")
    print(f"  Max files:    {cfg['max_files']}")
    print(f"  Flush every:  {FLUSH_EVERY}")
    print("=" * 70)
    print()

    score_only = "--score-only" in sys.argv
    agg_only = "--agg-only" in sys.argv

    if not agg_only:
        _run_scoring(cfg, findings_csv, errors_log)

    if not score_only:
        print()
        print("-" * 70)
        print("STEP: Aggregating results by patient...")
        print("-" * 70)
        patient_rows = aggregate(findings_csv, patient_csv)
        _write_summary(summary_txt, patient_rows)

    print()
    print("=" * 70)
    print("Pipeline complete.")
    print("=" * 70)


def _run_scoring(cfg, findings_csv, errors_log):
    print("-" * 70)
    print("STEP 1: Loading candidate CSVs and checking for already-processed files...")
    print("-" * 70)

    already_processed = _load_already_processed(findings_csv)
    print(f"  Already processed (findings CSV): {len(already_processed)} distinct files — will skip.")

    candidates = []
    candidates.extend(_load_candidates(cfg["ccd_input_csv"], cfg["default_bucket"], "CCD"))
    candidates.extend(_load_candidates(cfg["trn_input_csv"], cfg["default_bucket"], "TRN"))
    print(f"  Candidates loaded (CCD + TRN): {len(candidates)}")

    to_process = [c for c in candidates if c["path"] not in already_processed]
    print(f"  Remaining to process: {len(to_process)}")

    allowed = cfg.get("allowed_buckets")
    if allowed:
        before = len(to_process)
        to_process = [c for c in to_process if c["bucket"] in allowed]
        if len(to_process) != before:
            print(f"  After bucket filter: {len(to_process)} (dropped {before - len(to_process)})")

    max_files = cfg.get("max_files")
    if max_files and len(to_process) > max_files:
        to_process = to_process[:max_files]
        print(f"  Limited to max_files: {max_files}")

    if not to_process:
        print("  [OK] All candidates already scored. Nothing new to process.")
        return

    print()
    print("-" * 70)
    print(f"STEP 2: Scoring {len(to_process)} candidate files...")
    print("-" * 70)

    session = boto3.Session(profile_name=cfg["aws_profile"])
    s3 = session.client("s3")

    results_buffer = []
    error_buffer = []
    total = len(to_process)
    start_time = time.time()
    errors = 0
    findings_found = 0

    for i, candidate in enumerate(to_process, 1):
        bucket = candidate["bucket"]
        key = candidate["key"]
        qe = candidate.get("qe", "")
        aa = candidate.get("assigning_authority", "")
        data_type = candidate["data_type"]

        rows = score_one_candidate(s3, bucket, key, qe, aa, data_type)

        # A file with zero findings still needs to be marked "processed" in
        # the restart ledger. We encode that as a single zero-finding marker
        # row rather than skipping the file entirely from the output CSV —
        # otherwise a restart would see it as never-processed and re-download
        # it forever. (Same idea as ADTScanForCandidates: a file is only
        # skippable next run if it has a durable record of being handled.)
        if not rows:
            rows = [{
                "path": f"s3://{bucket}/{key}", "bucket": bucket, "key": key,
                "data_type": data_type, "qe": qe, "assigning_authority": aa,
                "mrn": "", "patient_last_name": "", "patient_first_name": "",
                "patient_dob": "", "encounter_date": "", "encounter_location": "",
                "signal_type": "", "signal_detail": "", "section": "",
                "error": "", "processing_time_ms": 0,
            }]

        for r in rows:
            if r.get("error"):
                errors += 1
                error_buffer.append(f"{r['path']}\t{r['error']}")
            elif r.get("signal_type"):
                findings_found += 1

        results_buffer.extend(rows)

        if i % 50 == 0 or i == total:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate if rate > 0 else 0
            print(f"  [{i:,}/{total:,}] {rate:.1f} files/sec | "
                  f"findings: {findings_found} | errors: {errors} | "
                  f"ETA: {remaining/60:.1f} min")

        # Flush every FLUSH_EVERY FILES processed (not rows written — a file
        # with 5 findings still only counts once toward the flush interval).
        if i % FLUSH_EVERY == 0:
            _flush_results(results_buffer, findings_csv)
            _flush_errors(error_buffer, errors_log)
            results_buffer = []
            error_buffer = []

    if results_buffer:
        _flush_results(results_buffer, findings_csv)
    if error_buffer:
        _flush_errors(error_buffer, errors_log)

    elapsed_total = time.time() - start_time
    print()
    print(f"  Scoring complete: {total} files in {elapsed_total/60:.1f} min")
    print(f"  Findings: {findings_found}   Errors: {errors}")


def _load_candidates(csv_path, default_bucket, data_type):
    """Load one candidate CSV (CCD or TRN). Each row needs at least 'key'."""
    candidates = []

    if not os.path.isfile(csv_path):
        print(f"  [WARNING] Candidate CSV not found ({data_type}): {os.path.abspath(csv_path)}")
        return candidates

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print(f"  [WARNING] Candidate CSV has no header row: {csv_path}")
            return candidates

        header_map = {name.strip().lower(): name for name in reader.fieldnames}
        key_col = header_map.get("key")
        bucket_col = header_map.get("bucket")
        qe_col = header_map.get("qe")
        aa_col = header_map.get("assigning_authority")

        if not key_col:
            print(f"  [WARNING] Candidate CSV missing 'key' column: {csv_path}")
            return candidates

        for row in reader:
            key = (row.get(key_col) or "").strip()
            if not key:
                continue
            bucket = (row.get(bucket_col) or "").strip() if bucket_col else ""
            bucket = bucket or default_bucket
            if not bucket:
                continue

            candidates.append({
                "bucket": bucket,
                "key": key,
                "path": f"s3://{bucket}/{key}",
                "qe": (row.get(qe_col) or "").strip() if qe_col else "",
                "assigning_authority": (row.get(aa_col) or "").strip() if aa_col else "",
                "data_type": data_type,
            })

    return candidates


def _load_already_processed(findings_csv_path):
    """Load the set of S3 paths already present in the findings CSV
    (restart support — a path shows up here whether it had findings or not,
    see the zero-finding marker row logic in _run_scoring)."""
    processed = set()
    if not os.path.isfile(findings_csv_path):
        return processed
    try:
        with open(findings_csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                path = (row.get("path") or "").strip()
                if path:
                    processed.add(path)
    except (IOError, csv.Error) as e:
        print(f"  [WARNING] Could not read existing findings CSV: {e}")
        return set()
    return processed


_FINDINGS_FIELDS = [
    "path", "bucket", "key", "data_type", "qe", "assigning_authority", "mrn",
    "patient_last_name", "patient_first_name", "patient_dob",
    "encounter_date", "encounter_location",
    "signal_type", "signal_detail", "section", "error", "processing_time_ms",
]


def _flush_results(rows, findings_csv_path):
    """Append rows to the findings CSV (Output A). Write header if new."""
    if not rows:
        return
    file_exists = os.path.exists(findings_csv_path) and os.path.getsize(findings_csv_path) > 0
    with open(findings_csv_path, "a" if file_exists else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FINDINGS_FIELDS)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in _FINDINGS_FIELDS})


def _flush_errors(lines, errors_log_path):
    if not lines:
        return
    with open(errors_log_path, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def _write_summary(summary_path, patient_rows):
    high = sum(1 for r in patient_rows if r["concern_level"] == "HIGH")
    moderate = sum(1 for r in patient_rows if r["concern_level"] == "MODERATE")

    lines = [
        "MEASLES CANDIDATE DETECTION — RUN SUMMARY",
        "=" * 50,
        "Scope this pass: CCD + TRN only (ADT and Lab/ORU are out)",
        "",
        f"Distinct patient candidates: {len(patient_rows)}",
        f"  HIGH concern:     {high}",
        f"  MODERATE concern: {moderate}",
    ]
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
