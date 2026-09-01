"""
overnight_run.py — Unattended, self-restarting full DEV pipeline
=================================================================

Runs the 42 CFR pipeline to completion, retrying automatically if a pass
crashes or is interrupted. Safe to leave running overnight.

Why this is safe to loop:
  - The pipeline never re-scores a CCD already present in scored_jsons/
    (restart-safe by design). Each pass only picks up unscored candidates.
  - Once every candidate is scored, a pass processes 0 new files, and we stop.

What it does each pass:
  1. python run_pipeline.py   (score remaining -> aggregate -> letters)
  2. Check how many candidates in the CSV remain unscored.
  3. If none remain, do one final aggregate+letters pass and finish.
  4. If a pass errored, wait a bit and retry (up to MAX_PASSES).

Output/log: overnight_run.log (timestamped).
"""

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

CANDIDATES_CSV = os.path.join("..", "05-Candidates", "DEV-42CFR-CandidateS3Paths.csv")
SCORED_JSON = os.path.join("..", "06-Results", "Output", "DEV", "scored_jsons", "scored_results.json")
LOG_PATH = os.path.join(SCRIPT_DIR, "overnight_run.log")

MAX_PASSES = 40            # hard stop so it can't loop forever
SLEEP_BETWEEN_PASSES = 20  # seconds to wait after a crash before retrying


def log(msg):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def count_candidates():
    """How many rows are in the candidate CSV (paths we intend to score)."""
    if not os.path.isfile(CANDIDATES_CSV):
        return 0
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        return sum(1 for _ in csv.DictReader(f))


def count_scored_paths():
    """Distinct S3 paths already scored (restart set)."""
    scored = set()
    if not os.path.isfile(SCORED_JSON):
        return scored
    with open(SCORED_JSON, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                p = rec.get("path", "")
                if p:
                    scored.add(p)
            except json.JSONDecodeError:
                pass
    return scored


def candidate_paths():
    paths = set()
    if not os.path.isfile(CANDIDATES_CSV):
        return paths
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            bucket = (row.get("bucket") or "").strip()
            key = (row.get("key") or "").strip()
            if key:
                paths.add(f"s3://{bucket}/{key}")
    return paths


def run_pipeline(extra_args=None):
    """Run run_pipeline.py once; return exit code."""
    cmd = [sys.executable, "run_pipeline.py"] + (extra_args or [])
    log(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=True, text=True)
    # Tail the pipeline output into the log for visibility
    tail = (result.stdout or "").strip().split("\n")[-12:]
    for t in tail:
        log(f"    | {t}")
    if result.returncode != 0:
        err = (result.stderr or "").strip().split("\n")[-8:]
        for e in err:
            log(f"    ! {e}")
    return result.returncode


def main():
    log("=" * 60)
    log("OVERNIGHT RUN STARTED (DEV)")
    log("=" * 60)

    total_candidates = count_candidates()
    log(f"Candidate CSV rows: {total_candidates}")
    if total_candidates == 0:
        log("[FATAL] No candidate CSV found. Cannot proceed.")
        log("        Expected: " + os.path.abspath(CANDIDATES_CSV))
        return 1

    want = candidate_paths()

    for i in range(1, MAX_PASSES + 1):
        scored = count_scored_paths()
        remaining = want - scored
        log(f"--- Pass {i}: scored={len(scored)} / {len(want)}  remaining={len(remaining)} ---")

        if not remaining:
            log("All candidates already scored. Doing final aggregate + letters.")
            run_pipeline(["--agg-only"])
            log("DONE — full pipeline complete, all candidates scored.")
            return 0

        rc = run_pipeline()
        if rc == 0:
            # A clean pass; loop will re-check remaining count next iteration.
            log(f"  Pass {i} exited cleanly.")
        else:
            log(f"  Pass {i} exited with code {rc}. Will retry after {SLEEP_BETWEEN_PASSES}s.")
            time.sleep(SLEEP_BETWEEN_PASSES)

        # Safety: if a pass made no progress at all AND didn't error, avoid a
        # tight infinite loop.
        new_scored = count_scored_paths()
        if len(new_scored) == len(scored) and rc == 0 and (want - new_scored):
            log("  [WARN] No progress this pass despite clean exit. "
                "Remaining files may be persistently failing to download/parse.")
            log("         Continuing — restart logic will keep trying the rest.")
            time.sleep(SLEEP_BETWEEN_PASSES)

    log(f"[STOP] Reached MAX_PASSES ({MAX_PASSES}). "
        f"Scored {len(count_scored_paths())} / {len(want)}.")
    log("Doing a final aggregate + letters with whatever is scored.")
    run_pipeline(["--agg-only"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
