"""
config.py — 42 CFR Candidate Identification Configuration
==========================================================

DEV/PROD profile switch, AWS settings, thresholds, and shared constants.
Same pattern as FindEHR's findandsaveEHRfromCCD-EntireCCD.py.

Edit ACTIVE_PROFILE to switch between DEV and PROD.
"""

import os

# ============================================================================
# CHOOSE YOUR PROFILE -- set to "DEV" or "PROD"
# ============================================================================

ACTIVE_PROFILE = "DEV"

# ============================================================================
# DEV PROFILE — small sample from learning bucket
# ============================================================================

DEV = {
    "aws_profile": "student1",
    "default_bucket": "nyec.ccda.learning",
    "allowed_buckets": ["nyec.ccda.learning"],
    "input_csv": os.path.join("..", "05-Candidates", "DEV-42CFR-CandidateS3Paths.csv"),
    "output_dir": os.path.join("..", "06-Results", "DEV-Output"),
    "output_json_dir": os.path.join("..", "06-Results", "DEV-Output", "scored_jsons"),
    "output_aggregate_csv": os.path.join("..", "06-Results", "DEV-Output", "aggregate_results.csv"),
    "output_letters_dir": os.path.join("..", "06-Results", "DEV-Output", "qe_letters"),
    "max_files": 200,
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
    "output_dir": os.path.join("..", "06-Results", "PROD-Output"),
    "output_json_dir": os.path.join("..", "06-Results", "PROD-Output", "scored_jsons"),
    "output_aggregate_csv": os.path.join("..", "06-Results", "PROD-Output", "aggregate_results.csv"),
    "output_letters_dir": os.path.join("..", "06-Results", "PROD-Output", "qe_letters"),
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
# CDA NAMESPACE — used by all XML parsing
# ============================================================================

CDA_NS = "urn:hl7-org:v3"

# ============================================================================
# CANDIDATE CLASSIFICATION THRESHOLDS (SUD prevalence %)
# ============================================================================
# These are starting points — refine during Phase 1 calibration.

THRESHOLD_HIGH = 0.50       # > 50% = CANDIDATE - HIGH
THRESHOLD_MODERATE = 0.25   # 25-50% = CANDIDATE - MODERATE
THRESHOLD_LOW = 0.10        # 10-25% = CANDIDATE - LOW
# < 10% = NOT A CANDIDATE

# Any source with strong_signal_prevalence > 0 becomes at minimum LOW
STRONG_SIGNAL_OVERRIDE = True

# ============================================================================
# FLUSH INTERVAL — write progress to disk every N records
# ============================================================================

FLUSH_EVERY = 200

# ============================================================================
# 42 CFR BUCKET IDENTIFIERS — for routing check
# ============================================================================
# Substrings that indicate a path is in the protected 42 CFR pipeline.

CFR42_BUCKET_MARKERS = [
    "42cfr",
    "part2",
    "cfr-part-2",
]

# ============================================================================
# FACILITY NAME KEYWORDS — used by check_facility_name.py
# ============================================================================

FACILITY_SUD_KEYWORDS = [
    "recovery",
    "addiction",
    "substance",
    "methadone",
    "opioid treatment",
    "behavioral health",
    "detox",
    "suboxone",
    "mat clinic",
    "treatment center",
    "sober",
    "rehab",
]

# ============================================================================
# MAT MEDICATION LISTS — used by check_medications.py
# ============================================================================

# Strong signal: only dispensed in OTP context for OUD
MAT_STRONG = [
    "methadone",
]

# Moderate signal: used in SUD treatment but also in general practice
MAT_MODERATE = [
    "buprenorphine",
    "suboxone",
    "subutex",
    "sublocade",
    "naltrexone",
    "vivitrol",
]

# Weak signal: supportive only, not indicative alone
MAT_WEAK = [
    "naloxone",
    "narcan",
    "acamprosate",
    "campral",
    "disulfiram",
    "antabuse",
]

# ============================================================================
# OTP / SUD BILLING CODES — used by check_billing_codes.py
# ============================================================================

# Exact code matches
BILLING_CODES_EXACT = [
    "H0020",   # Methadone administration/dispensing
    "S0109",   # Methadone, oral, dispensed
    "H0015",   # Intensive outpatient treatment (SUD)
    "H0005",   # Group counseling, substance use
    "H0004",   # Individual counseling, substance use
    "H0001",   # Alcohol/drug assessment
    "99408",   # SBIRT screening
    "99409",   # SBIRT intervention
]

# Code range matches (prefix-based)
BILLING_CODES_PREFIXES = [
    "G2067", "G2068", "G2069", "G2070", "G2071", "G2072",
    "G2073", "G2074", "G2075", "G2076", "G2077", "G2078",  # OTP bundled payments
    "80305", "80306", "80307",  # Drug testing (context-dependent, weak alone)
]

# ============================================================================
# SUD ENCOUNTER KEYWORDS — used by check_encounters.py
# ============================================================================

ENCOUNTER_SUD_KEYWORDS = [
    "detox",
    "detoxification",
    "intensive outpatient",
    "iop",
    "residential treatment",
    "opioid treatment program",
    "otp",
    "substance abuse",
    "substance use",
    "addiction counseling",
    "medication assisted treatment",
    "mat",
    "methadone maintenance",
]

# ============================================================================
# SUD PROCEDURE KEYWORDS — used by check_procedures.py
# ============================================================================

PROCEDURE_SUD_KEYWORDS = [
    "drug screen",
    "urine drug",
    "uds",
    "sbirt",
    "addiction counseling",
    "substance abuse counseling",
    "substance use counseling",
    "toxicology",
    "drug test",
]
