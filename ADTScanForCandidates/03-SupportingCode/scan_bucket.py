"""
scan_bucket.py — ADT Scan Driver
==================================

Reads every ADT file in the configured bucket (at/after MIN_FILE_DATE),
extracts PID-3 patient identifiers, and checks each against the ~35,000 known
AA|MRN pairs (people NOT added to the Opt-Out database). Answers:

    "Of the MRNs that were NOT added to Opt-Out, do we see those same MRNs
     showing up in the ADT traffic?"

Implements every requirement in:
  - 01-RequirementsAndPlans/adt-scan-requirements.md
      * date cutoff (MIN_FILE_DATE) applied at listing time
      * restart-safe ledger; a file is marked done ONLY after its result is
        durably written
      * never process the same file twice
      * flush to disk at least every FLUSH_EVERY (50) processed files
      * four outputs: candidate coverage (A), match detail (B), summary (C),
        ADT tracking records (D)
  - 01-RequirementsAndPlans/parallelism-requirement.md
      * configurable WORKERS (default 1 = sequential, unchanged behavior)
      * single producer hands each S3 key to a worker exactly once (no two
        workers can ever grab the same file)
      * all output writes serialized through a single lock
      * thread-safe per-candidate tallies
  - 01-RequirementsAndPlans/adt-tracking-database-requirement.md
      * one tracking row per ADT message, in EVERY successfully parsed file
        (match or not) — columns mirror NYEC_EG_Operational_Database_Schema.csv
        (lookup/crosswalk-dependent columns omitted) plus an appended
        found_in_missing_mrn_list yes/no column

Usage:
    python scan_bucket.py
"""

import boto3
import csv
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from config import (
    get_config,
    LEDGER_FILENAME,
    MATCHES_FILENAME,
    COVERAGE_FILENAME,
    TRACKING_FILENAME,
    ERRORS_FILENAME,
    SUMMARY_FILENAME,
    FLUSH_EVERY,
    MIN_FILE_DATE,
    WORKERS,
)
from load_lookup import load_lookup, make_key
import parse_adt
import capture_adt_record


# ============================================================================
# Shared, thread-safe state
# ============================================================================

class ScanState:
    """
    Holds everything workers touch concurrently. All mutation goes through
    the single lock, so writes to the ledger/matches/errors files are never
    interleaved, and per-candidate tallies stay accurate under concurrency.
    """

    def __init__(self, lookup_set, paths):
        self.lock = threading.Lock()

        self.lookup_set = lookup_set
        self.paths = paths

        # Per-candidate coverage: key -> {"times_seen": int, "first_key": str,
        #                                  "first_type": str, "first_time": str}
        self.coverage = {k: {"times_seen": 0, "first_key": "", "first_type": "", "first_time": ""}
                         for k in lookup_set}

        # Counters for the run summary
        self.files_processed = 0        # newly processed this run (not skipped)
        self.files_skipped_ledger = 0   # already in ledger at startup
        self.files_skipped_cutoff = 0   # excluded by MIN_FILE_DATE
        self.files_errored = 0
        self.match_rows_written = 0
        self.tracking_rows_written = 0

        self._since_flush = 0

        # Open output files in APPEND mode so a restart continues the same
        # files rather than clobbering prior progress.
        self._ledger_f = open(paths["ledger"], "a", encoding="utf-8", newline="")
        self._matches_f = open(paths["matches"], "a", encoding="utf-8", newline="")
        self._tracking_f = open(paths["tracking"], "a", encoding="utf-8", newline="")
        self._errors_f = open(paths["errors"], "a", encoding="utf-8", newline="")

        self._matches_writer = csv.writer(self._matches_f)
        if self._matches_f.tell() == 0:
            self._matches_writer.writerow([
                "assigning_authority", "mrn", "bucket", "s3_key", "path",
                "message_type", "message_time", "matched_pid3_raw",
            ])
            self._matches_f.flush()

        # Output D: ADT tracking records (see adt-tracking-database-requirement.md).
        # Mirrors NYEC_EG_Operational_Database_Schema.csv column order, plus
        # one appended found_in_missing_mrn_list column. One row per ADT
        # message (encounter-level), in every successfully parsed file.
        self._tracking_writer = csv.writer(self._tracking_f)
        if self._tracking_f.tell() == 0:
            self._tracking_writer.writerow(capture_adt_record.TRACKING_COLUMNS)
            self._tracking_f.flush()

    # ------------------------------------------------------------------
    # Called by a worker after it has fully processed one file. This is
    # the ONLY place that writes matches, updates coverage, and appends to
    # the ledger — so it must run under the lock.
    # ------------------------------------------------------------------
    def record_result(self, s3_key, bucket, path, matches, tracking_records):
        """
        matches: list of dicts with aa, mrn, message_type, message_time, raw_pid3
        (empty list if the file had no hits).
        tracking_records: list of dicts from capture_adt_record.build_records()
        — one per PID-3 identifier found in the file, regardless of match
        (empty list only if the file had zero PID-3 identifiers at all).
        Called once per successfully processed file (download + parse succeeded).
        """
        with self.lock:
            # 1) Write match detail rows (Output B) and update coverage (Output A)
            for m in matches:
                self._matches_writer.writerow([
                    m["aa"], m["mrn"], bucket, s3_key, path,
                    m["message_type"], m["message_time"], m["raw_pid3"],
                ])
                self.match_rows_written += 1

                key = (m["aa"], m["mrn"])
                cov = self.coverage.get(key)
                if cov is not None:
                    cov["times_seen"] += 1
                    if not cov["first_key"]:
                        cov["first_key"] = s3_key
                        cov["first_type"] = m["message_type"]
                        cov["first_time"] = m["message_time"]

            # 2) Write ADT tracking rows (Output D) — one per ADT message,
            #    match or not. Same file, same pass, no extra download/parse.
            for rec in tracking_records:
                self._tracking_writer.writerow(
                    [rec[col] for col in capture_adt_record.TRACKING_COLUMNS]
                )
                self.tracking_rows_written += 1

            # 3) Mark the file done in the ledger — ONLY after the results
            #    above have been written. If the process dies before this
            #    line, the file is simply retried next run.
            self._ledger_f.write(s3_key + "\n")

            self.files_processed += 1
            self._since_flush += 1

            # 4) Flush at least every FLUSH_EVERY processed files (hard
            #    requirement — never lose more than this to a crash).
            if self._since_flush >= FLUSH_EVERY:
                self._flush_all()
                self._since_flush = 0

    def record_error(self, s3_key, error_msg):
        """A file that failed download/parse. NOT added to the ledger, so it
        will be retried on the next run."""
        with self.lock:
            self._errors_f.write(f"{s3_key}\t{error_msg}\n")
            self.files_errored += 1
            self._since_flush += 1
            if self._since_flush >= FLUSH_EVERY:
                self._flush_all()
                self._since_flush = 0

    def _flush_all(self):
        """Actual write + flush + fsync to disk. Called only while holding lock."""
        for f in (self._ledger_f, self._matches_f, self._tracking_f, self._errors_f):
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # best-effort; some filesystems/streams don't support fsync

    def final_flush(self):
        with self.lock:
            self._flush_all()

    def close(self):
        self.final_flush()
        self._ledger_f.close()
        self._matches_f.close()
        self._tracking_f.close()
        self._errors_f.close()


# ============================================================================
# Ledger + date-cutoff (used before any file is queued for work)
# ============================================================================

def load_ledger(ledger_path):
    """Read the processed-files ledger into a set of already-done S3 keys."""
    done = set()
    if not os.path.isfile(ledger_path):
        return done
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            key = line.strip()
            if key:
                done.add(key)
    return done


def is_after_cutoff(last_modified):
    """
    last_modified: a datetime (aware, from boto3) for the S3 object.
    Returns True if the object's date is on/after MIN_FILE_DATE.
    """
    obj_date = last_modified.astimezone(timezone.utc).date()
    return obj_date >= MIN_FILE_DATE


# ============================================================================
# Per-file work (runs in a worker thread)
# ============================================================================

def process_one_file(s3_client, bucket, key, state):
    """
    Download, parse, and match ONE file. Returns nothing — writes results
    into `state` via the thread-safe methods above.
    """
    path = f"s3://{bucket}/{key}"

    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        raw = resp["Body"].read()
        text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        state.record_error(key, f"download_error: {e}")
        return

    try:
        messages = parse_adt.parse(text)
    except Exception as e:
        state.record_error(key, f"parse_error: {e}")
        return

    matches = []
    for msg in messages:
        for ident in msg["identifiers"]:
            k = (ident["aa"], ident["id"])
            if k in state.lookup_set:
                matches.append({
                    "aa": ident["aa"],
                    "mrn": ident["id"],
                    "message_type": msg["message_type"],
                    "message_time": msg["message_time"],
                    "raw_pid3": ident["raw_pid3"],
                })

    # Output D: one tracking record per ADT message, match or not — see
    # adt-tracking-database-requirement.md. Cheap: we already have `messages`
    # in memory from the parse above, no extra download/parse needed.
    tracking_records = capture_adt_record.build_records(messages, lookup_set=state.lookup_set)

    state.record_result(key, bucket, path, matches, tracking_records)


# ============================================================================
# Producer: lists the bucket and hands out work exactly once per key
# ============================================================================

def iter_candidate_keys(s3_client, bucket, prefix, ledger_done, state):
    """
    Generator that yields S3 keys still needing work: not empty, at/after the
    date cutoff, and not already in the ledger. This is the single point of
    "who gets dispatched" — workers never pick their own files, so two
    workers can never receive the same key.
    """
    paginator = s3_client.get_paginator("list_objects_v2")
    list_kwargs = {"Bucket": bucket}
    if prefix:
        list_kwargs["Prefix"] = prefix

    for page in paginator.paginate(**list_kwargs):
        for obj in page.get("Contents", []):
            key = obj["Key"]

            if obj.get("Size", 0) == 0:
                continue  # folder marker / empty object

            if not is_after_cutoff(obj["LastModified"]):
                state.files_skipped_cutoff += 1
                continue

            if key in ledger_done:
                state.files_skipped_ledger += 1
                continue

            yield key


# ============================================================================
# Main
# ============================================================================

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    cfg = get_config()
    output_dir = cfg["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    paths = {
        "ledger": os.path.join(output_dir, LEDGER_FILENAME),
        "matches": os.path.join(output_dir, MATCHES_FILENAME),
        "coverage": os.path.join(output_dir, COVERAGE_FILENAME),
        "tracking": os.path.join(output_dir, TRACKING_FILENAME),
        "errors": os.path.join(output_dir, ERRORS_FILENAME),
        "summary": os.path.join(output_dir, SUMMARY_FILENAME),
    }

    print("=" * 70)
    print("ADT SCAN — known AA|MRN coverage check")
    print("=" * 70)
    print(f"  Profile:      {os.environ.get('ACTIVE_PROFILE', '')}")
    print(f"  AWS profile:  {cfg['aws_profile']}")
    print(f"  Bucket:       {cfg['bucket']}  prefix={cfg.get('prefix', '') or '(none)'}")
    print(f"  Min date:     {MIN_FILE_DATE}  (files before this are skipped entirely)")
    print(f"  Workers:      {WORKERS}")
    print(f"  Flush every:  {FLUSH_EVERY} processed files")
    print(f"  Output dir:   {output_dir}")
    print("=" * 70)

    # ---- Load the ~35k known AA|MRN pairs -------------------------------
    print("\nLoading lookup list...")
    lookup_set, lookup_stats = load_lookup(cfg["lookup_csv"])
    print(f"  Loaded {lookup_stats['pairs_loaded']} known AA|MRN pairs "
          f"(from {lookup_stats['rows_read']} rows, {lookup_stats['skipped']} skipped).")

    # ---- Load the restart ledger ----------------------------------------
    ledger_done = load_ledger(paths["ledger"])
    print(f"  Already processed (ledger): {len(ledger_done):,} files — will be skipped.")

    # ---- Shared state + S3 session --------------------------------------
    state = ScanState(lookup_set, paths)
    session = boto3.Session(profile_name=cfg["aws_profile"])

    max_files = cfg.get("max_files")
    dispatched = 0
    start_time = time.time()

    print(f"\nScanning s3://{cfg['bucket']}/{cfg.get('prefix', '')} ...\n")

    try:
        if WORKERS <= 1:
            # ---- Sequential path (default; unchanged, simplest behavior) --
            s3_client = session.client("s3")
            for key in iter_candidate_keys(s3_client, cfg["bucket"], cfg.get("prefix", ""),
                                            ledger_done, state):
                process_one_file(s3_client, cfg["bucket"], key, state)
                dispatched += 1
                _maybe_report_progress(dispatched, start_time)
                if max_files and dispatched >= max_files:
                    print(f"\n  Reached max_files={max_files}. Stopping this run.")
                    break
        else:
            # ---- Parallel path: one producer, N worker threads ------------
            # Each worker gets its own S3 client (boto3 clients are not
            # guaranteed thread-safe to share). The producer (this thread)
            # is the ONLY place that decides which key goes to which future,
            # so no two workers can ever receive the same key.
            clients = [session.client("s3") for _ in range(WORKERS)]
            producer_client = session.client("s3")  # separate client for listing only

            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futures = {}
                key_gen = iter_candidate_keys(
                    producer_client, cfg["bucket"], cfg.get("prefix", ""),
                    ledger_done, state,
                )

                # Simple monotonically-increasing counter for round-robin
                # client assignment. NOTE: len(futures) is NOT safe to use
                # here — it shrinks as futures complete, so it does not give
                # a stable round-robin sequence. A dedicated counter does.
                dispatch_counter = [0]

                def submit_next():
                    try:
                        key = next(key_gen)
                    except StopIteration:
                        return False
                    client = clients[dispatch_counter[0] % WORKERS]
                    dispatch_counter[0] += 1
                    fut = pool.submit(process_one_file, client, cfg["bucket"], key, state)
                    futures[fut] = key
                    return True

                # Prime the pool
                for _ in range(WORKERS * 2):
                    if max_files and dispatched >= max_files:
                        break
                    if not submit_next():
                        break
                    dispatched += 1

                while futures:
                    for fut in list(as_completed(futures, timeout=None)):
                        futures.pop(fut, None)
                        fut.result()  # re-raise unexpected exceptions
                        _maybe_report_progress(state.files_processed + state.files_errored,
                                                start_time)
                        if not (max_files and dispatched >= max_files):
                            if submit_next():
                                dispatched += 1
                        break  # re-check the outer while with updated futures dict

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Flushing what we have so far...")

    finally:
        state.close()

    # ---- Write the candidate coverage file (Output A) -------------------
    _write_coverage(paths["coverage"], state)

    # ---- Write the run summary (Output C) --------------------------------
    elapsed = time.time() - start_time
    _write_summary(paths["summary"], state, lookup_stats, elapsed)

    print("\nDone. See:")
    print(f"  Coverage (primary): {paths['coverage']}")
    print(f"  Match detail:       {paths['matches']}")
    print(f"  ADT tracking:       {paths['tracking']}")
    print(f"  Run summary:        {paths['summary']}")


def _maybe_report_progress(count, start_time, every=50):
    if count % every == 0 and count > 0:
        elapsed = time.time() - start_time
        rate = count / elapsed if elapsed > 0 else 0
        print(f"  [{count:,} processed]  {rate:.1f} files/sec")


def _write_coverage(coverage_path, state):
    """Output A: one row per known AA|MRN pair — the primary deliverable."""
    with open(coverage_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "assigning_authority", "mrn", "seen_in_adt", "times_seen",
            "first_s3_key", "first_message_type", "first_message_time",
        ])
        for (aa, mrn), cov in sorted(state.coverage.items()):
            seen = cov["times_seen"] > 0
            writer.writerow([
                aa, mrn, "yes" if seen else "no", cov["times_seen"],
                cov["first_key"], cov["first_type"], cov["first_time"],
            ])


def _write_summary(summary_path, state, lookup_stats, elapsed_sec):
    total_candidates = len(state.coverage)
    seen_candidates = sum(1 for c in state.coverage.values() if c["times_seen"] > 0)

    lines = [
        "ADT SCAN — RUN SUMMARY",
        "=" * 50,
        f"Known AA|MRN pairs loaded:      {lookup_stats['pairs_loaded']:,}",
        f"Candidates seen in ADT feed:    {seen_candidates:,} "
        f"({(seen_candidates/total_candidates*100 if total_candidates else 0):.2f}%)",
        f"Candidates NOT seen:            {total_candidates - seen_candidates:,}",
        "",
        f"Files processed this run:       {state.files_processed:,}",
        f"Files skipped (already done):   {state.files_skipped_ledger:,}",
        f"Files skipped (before cutoff):  {state.files_skipped_cutoff:,}",
        f"Files errored (will retry):     {state.files_errored:,}",
        f"Match detail rows written:      {state.match_rows_written:,}",
        f"ADT tracking rows written:      {state.tracking_rows_written:,}",
        "",
        f"Elapsed this run:                {elapsed_sec/60:.1f} min",
    ]
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
