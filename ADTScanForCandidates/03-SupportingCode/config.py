"""
config.py — ADT Scan Configuration
====================================

DEV/PROD profile switch, S3 settings, lookup-list location, output/ledger
paths, flush interval, and CSV column mappings.

Edit ACTIVE_PROFILE to switch between DEV (safe sample) and PROD (the real
encounter-gateway-incoming-prod bucket).
"""

import os
import datetime

# ============================================================================
# CHOOSE YOUR PROFILE -- set to "DEV" or "PROD"
# ============================================================================

ACTIVE_PROFILE = "DEV"

# ============================================================================
# DEV PROFILE -- small, safe sample we can actually read with student1
# ============================================================================

DEV = {
    "aws_profile": "student1",
    "bucket": "nyec.ccda.learning",
    # Optional prefix to limit the DEV scan to a sample folder.
    "prefix": "ADTSample/",
    # The ~35k AA|MRN lookup CSV (place it in 05-Candidates/).
    "lookup_csv": os.path.join("..", "05-Candidates", "known_aa_mrn.csv"),
    "output_dir": os.path.join("..", "06-Results", "Output", "DEV"),
    # Cap files processed per run (None = no cap). Useful for quick DEV checks.
    "max_files": 500,
}

# ============================================================================
# PROD PROFILE -- the real ADT bucket (requires PROD-capable AWS profile)
# ============================================================================

PROD = {
    "aws_profile": "default",   # must have read access to the ADT bucket
    "bucket": "encounter-gateway-incoming-prod",
    "prefix": "",               # scan the whole bucket
    "lookup_csv": os.path.join("..", "05-Candidates", "known_aa_mrn.csv"),
    "output_dir": os.path.join("..", "06-Results", "Output", "PROD"),
    "max_files": None,          # process everything
}

# ============================================================================
# Resolve active config
# ============================================================================


def get_config():
    if ACTIVE_PROFILE == "DEV":
        return DEV
    elif ACTIVE_PROFILE == "PROD":
        return PROD
    raise ValueError(f"Unknown ACTIVE_PROFILE: {ACTIVE_PROFILE}. Use 'DEV' or 'PROD'.")


# ============================================================================
# LOOKUP CSV COLUMN MAPPING
# ============================================================================
# The 35k list is expected to have an assigning authority column and an MRN
# column. If the real file uses different headers, list the accepted names
# here (first match wins, case-insensitive).

LOOKUP_AA_COLUMNS = ["assigning_authority", "aa", "assigningauthority", "authority"]
LOOKUP_MRN_COLUMNS = ["mrn", "medical_record_number", "patient_id", "id"]

# ============================================================================
# MRN NORMALIZATION
# ============================================================================
# Applied to BOTH the lookup list and the values parsed from ADT files, so
# formatting differences don't cause missed matches. Finalize on a real
# sample if needed.

NORMALIZE_UPPERCASE = True     # upper-case AA and MRN before comparing
NORMALIZE_STRIP = True         # strip surrounding whitespace
NORMALIZE_STRIP_LEADING_ZEROS_ON_MRN = False  # set True if MRNs differ only by leading zeros

# ============================================================================
# LEDGER / OUTPUT FILE NAMES (inside output_dir)
# ============================================================================

LEDGER_FILENAME = "processed_files.log"     # append-only list of finished S3 keys
MATCHES_FILENAME = "matches_detail.csv"     # Output B: one row per (file, matched pair)
COVERAGE_FILENAME = "candidate_coverage.csv"  # Output A: one row per known AA|MRN pair
ERRORS_FILENAME = "errors.log"              # files that failed download/parse
SUMMARY_FILENAME = "run_summary.txt"        # end-of-run tallies

# ============================================================================
# FLUSH INTERVAL — write + flush to disk at least every N processed files
# ============================================================================
# HARD REQUIREMENT (see adt-scan-requirements.md "Flush to disk every 50
# records"): we previously lost hours of work to a crash because output
# wasn't reliably hitting disk. 50 is the MAXIMUM acceptable gap between a
# file being processed and its result being safely flushed to disk. Writing
# more often (even every file) is fine; less often than this is not.
FLUSH_EVERY = 50

# ============================================================================
# DATE CUTOFF — exclude files older than this (good data starts 1/1/2026)
# ============================================================================
# Applied at LISTING time using the S3 object's LastModified timestamp, BEFORE
# a file is ever queued for download. Excluded files cost nothing (no GET, no
# parse) and are tallied separately as "skipped_before_cutoff" in the summary.
import datetime
MIN_FILE_DATE = datetime.date(2026, 1, 1)

# ============================================================================
# PARALLELISM  (see 01-RequirementsAndPlans/parallelism-requirement.md)
# ============================================================================
# Number of worker threads that download + parse + match files concurrently.
#   WORKERS = 1  -> pure sequential (default; behavior unchanged)
#   WORKERS = 8..16 -> good for a laptop run over the full bucket
# A single producer hands each S3 key to a worker exactly once, so two workers
# can never process the same file. All output writes are serialized by a lock.
WORKERS = 1
