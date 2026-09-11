"""
config.py — ADT Scan Configuration
====================================

DEV/PROD profile switch, S3 settings, lookup-list location, output/ledger
paths, flush interval, and CSV column mappings.

Edit ACTIVE_PROFILE to switch between DEV (safe sample) and PROD (the real
encounter-gateway-incoming-prod bucket).
"""

import os

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

LEDGER_FILENAME = "processed_files.log"   # append-only list of finished S3 keys
MATCHES_FILENAME = "matches.csv"          # one row per (file, matched pair)
ERRORS_FILENAME = "errors.log"            # files that failed download/parse
SUMMARY_FILENAME = "run_summary.txt"      # end-of-run tallies

# ============================================================================
# FLUSH INTERVAL — write progress to disk every N files processed
# ============================================================================

FLUSH_EVERY = 200
