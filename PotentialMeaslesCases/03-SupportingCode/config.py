"""
config.py — Measles Candidate Detection Configuration
=========================================================

DEV/PROD profile switch, AWS settings, thresholds, and shared constants.
Same pattern as 42CFRQualityCheck/run_pipeline_config.py and
FindEHR/findandsaveEHRfromCCD-EntireCCD.py.

Edit ACTIVE_PROFILE to switch between DEV and PROD.

SCOPE FOR THIS PASS (explicit user instruction): only CCD and TRN candidates.
ADT and Lab/ORU are out of scope entirely for now — there is no
adt_input_csv or lab_input_csv here; adding them back is a follow-on, not a
gap to silently work around.

Two candidate CSVs are expected (one per in-scope data type — see
01-RequirementsAndPlans/measles-detection-technical-plan.md Section 3):
    ccd_input_csv, trn_input_csv
Each has columns: bucket, key, qe, assigning_authority (same shape every
other project in this repo already uses for its candidate CSV).
"""

import os

# ============================================================================
# CHOOSE YOUR PROFILE -- set to "DEV" or "PROD"
# ============================================================================

ACTIVE_PROFILE = "DEV"

# ============================================================================
# DEV PROFILE -- small sample from the learning bucket
# ============================================================================

DEV = {
    "aws_profile": "student1",
    "default_bucket": "nyec.ccda.learning",
    "allowed_buckets": ["nyec.ccda.learning"],
    "ccd_input_csv": os.path.join("..", "05-Candidates", "DEV-CCD-CandidatePaths.csv"),
    "trn_input_csv": os.path.join("..", "05-Candidates", "DEV-TRN-CandidatePaths.csv"),
    "output_dir": os.path.join("..", "06-Results", "Output", "DEV"),
    "max_files": 2000,
}

# ============================================================================
# PROD PROFILE -- multi-bucket, reads bucket from each CSV row
# ============================================================================

PROD = {
    "aws_profile": "default",
    "default_bucket": None,  # PROD rows must specify their bucket in the CSV
    "allowed_buckets": [
        "nyec-pdr-prod-hixny", "nyec-pdr-prod-hixny-part2",
        "nyec-pdr-prod-techbd", "nyec-pdr-prod-techbd-part2",
        "nyec-pdr-prod-healtheconnections", "nyec-pdr-prod-healtheconnections-part2",
        "nyec-pdr-prod-rochester", "nyec-pdr-prod-rochester-part2",
        "nyec-pdr-prod-bronx", "nyec-pdr-prod-bronx-part2",
        "nyec-pdr-prod-healthix", "nyec-pdr-prod-healthix-part2",
    ],
    "ccd_input_csv": os.path.join("..", "05-Candidates", "PROD-CCD-CandidatePaths.csv"),
    "trn_input_csv": os.path.join("..", "05-Candidates", "PROD-TRN-CandidatePaths.csv"),
    "output_dir": os.path.join("..", "06-Results", "Output", "PROD"),
    "max_files": 30000,
}

# ============================================================================
# Resolve active config
# ============================================================================


def get_config():
    """Return the active profile dict."""
    if ACTIVE_PROFILE == "DEV":
        return DEV
    elif ACTIVE_PROFILE == "PROD":
        return PROD
    else:
        raise ValueError(f"Unknown ACTIVE_PROFILE: {ACTIVE_PROFILE}. Use 'DEV' or 'PROD'.")


# ============================================================================
# CDA NAMESPACE — used by the CCD (XML) parser
# ============================================================================

CDA_NS = "urn:hl7-org:v3"

# ============================================================================
# OUTPUT FILE NAMES (inside output_dir)
# ============================================================================

FINDINGS_FILENAME = "candidate_findings.csv"      # Output A: one row per file scanned
PATIENT_CANDIDATES_FILENAME = "patient_candidates.csv"  # Output B: one row per patient (primary deliverable)
ERRORS_FILENAME = "errors.log"
SUMMARY_FILENAME = "run_summary.txt"

# ============================================================================
# FLUSH INTERVAL — write + flush to disk every N processed files
# ============================================================================
# Same default used across most of this repo (42CFRQualityCheck,
# FindEHR). No prior crash history reported for this project, so no reason
# to tighten to 50 the way ADTScanForCandidates did after its crash.

FLUSH_EVERY = 200

# ============================================================================
# SCORING THRESHOLDS — two concern tiers (see GUIDANCE.md Section 6 and
# measles-detection-technical-plan.md Section 5)
# ============================================================================
# Points, not percentages. A coded measles diagnosis alone reaches HIGH.
# A three-C's+rash pattern reaches HIGH only if corroborated by a second
# data type; otherwise it sits at MODERATE. A single bare keyword is weak.

SCORE_CODED_DIAGNOSIS = 70       # ICD-10 B05.x or SNOMED measles concept hit
SCORE_THREE_CS_PATTERN = 40      # fever + (cough/coryza/conjunctivitis) + rash, same note/section
SCORE_BARE_KEYWORD = 15          # a single measles-related keyword, no code, no three-C's pattern
SCORE_CROSS_DATA_TYPE_BONUS = 20 # added once if signals came from 2+ distinct data types for this patient

THRESHOLD_HIGH = 60              # >= 60 = HIGH
# < 60 (but > 0) = MODERATE
# 0 = not a candidate (no row written)

# ============================================================================
# MEASLES SIGNAL DEFINITIONS (see GUIDANCE.md Section 5 and
# measles-detection-technical-plan.md Section 4)
# ============================================================================
# STARTING POINTS, NOT VALIDATED AGAINST REAL PDR DATA YET.
# Per GUIDANCE.md Section 7, Q2: "don't trust Section 5 as ground truth —
# validate against real data." Kept here, centralized, specifically so they
# are easy to find and revise once real DEV/PROD data has been examined —
# the same way 42CFRQualityCheck's SNOMED/ICD-10 lists in this file's sibling
# (run_pipeline_config.py) were revised multiple times after looking at real
# data.

# ICD-10: B05 (measles) and all its decimal children, matched by prefix.
ICD10_MEASLES_PREFIX = "B05"

# SNOMED-CT concept IDs for measles disease/findings (curated starting set).
SNOMED_MEASLES_CODES = [
    "14189004",     # Measles (disorder)
    "409448004",    # Congenital measles
    "186561007",    # Measles encephalitis
    "23685000",     # Postmeasles encephalitis
]

# Text keyword fallback (case-insensitive substring match) — used against
# problem/encounter display text (CCD), chief-complaint text (ADT), and
# discharge-summary/transition-note narrative text (TRN). These are
# deliberately broad/crude per GUIDANCE.md's "pattern-matching, not a
# validated clinical score" framing.
MEASLES_TEXT_KEYWORDS = [
    "measles",
    "rubeola",
    "febrile rash illness",
    "rule out measles",
    "r/o measles",
    "viral exanthem",
    "koplik",
]

# "Three C's" co-occurrence pattern (fever + cough/coryza/conjunctivitis +
# rash) — shared by all three checkers via three_cs_pattern.py.
THREE_CS_FEVER_KEYWORDS = ["fever", "febrile", "pyrexia"]
THREE_CS_COUGH_CORYZA_CONJUNCTIVITIS_KEYWORDS = [
    "cough", "coryza", "conjunctivitis", "runny nose", "red eyes", "pink eye",
]
THREE_CS_RASH_KEYWORDS = ["rash", "exanthem", "maculopapular"]

# NOTE: an isolation/airborne-precaution text signal (GUIDANCE.md Section 5,
# ADT row) was planned here but ADT is out of scope for this pass — removed
# rather than left as dead config. Re-add alongside ADT support.
