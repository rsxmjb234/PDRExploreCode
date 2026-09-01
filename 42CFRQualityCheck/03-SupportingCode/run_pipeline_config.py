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
# WEIGHTED SCORING MODEL — per-CCD 0-100 point scale
# ============================================================================
# Each signal category contributes up to its cap. The caps sum to 100.
# These weights reflect how strongly each category indicates a Part 2 facility.

SCORE_MAX_DIAGNOSES = 25       # SUD diagnoses (ICD-10 F10-F19, excl F17)
SCORE_MAX_MEDICATIONS = 20     # MAT medications
SCORE_MAX_BILLING = 25         # OTP / SUD-specific billing & procedure codes
SCORE_MAX_ENCOUNTERS = 25      # Treatment-model encounter types
SCORE_MAX_FACILITY_NAME = 5    # Facility name keyword match
# TOTAL = 100

# ---- How each category ramps toward its cap -------------------------------
# Diagnoses: points per distinct encounter SUD diagnosis (capped).
SCORE_DIAG_PER_HIT = 12        # each encounter F10-F19 diagnosis
SCORE_DIAG_WEAK_PER_HIT = 4    # problem-list-only (historical) diagnosis

# Medications: points by signal strength (capped at SCORE_MAX_MEDICATIONS).
SCORE_MED_STRONG = 20          # methadone (near-full credit alone)
SCORE_MED_MODERATE = 10        # buprenorphine / naltrexone etc.
SCORE_MED_WEAK = 3             # naloxone / acamprosate etc.

# Billing/procedure codes: points per matching code (capped).
SCORE_BILLING_PER_HIT = 13     # each OTP/SUD billing or procedure code

# Encounters: points per matching SUD encounter (capped).
SCORE_ENCOUNTER_PER_HIT = 13   # each treatment-model encounter

# Facility name: full facility-name credit if any keyword matched.
SCORE_FACILITY_HIT = 5

# ---- Source-level weighted average ----------------------------------------
# CCDs with a strong signal (methadone or OTP billing code) get extra weight
# so a few clearly-Part-2 documents aren't washed out by routine records.
SCORE_STRONG_CCD_WEIGHT_BONUS = 2.0   # weight = 1 + bonus for strong-signal CCDs

# ============================================================================
# CANDIDATE CLASSIFICATION THRESHOLDS (source score, 0-100)
# ============================================================================
# These are starting points — refine during Phase 1 calibration.

THRESHOLD_HIGH = 60         # >= 60 = CANDIDATE - HIGH
THRESHOLD_MODERATE = 35     # 35-59 = CANDIDATE - MODERATE
THRESHOLD_LOW = 15          # 15-34 = CANDIDATE - LOW
# < 15 = NOT A CANDIDATE

# Any source with a strong signal present becomes at minimum LOW
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
# SUD DIAGNOSIS CODES — used by check_diagnoses.py
# ============================================================================
# Diagnoses may be coded in ICD-10 (F10-F19) OR SNOMED-CT. The checker matches
# both. ICD-10 is handled by regex (F10-F19 excl F17). Below is the curated
# SNOMED-CT SUD concept set, plus a displayName keyword fallback.

# Code system OIDs
CS_ICD10 = "2.16.840.1.113883.6.90"
CS_SNOMED = "2.16.840.1.113883.6.96"
CS_RXNORM = "2.16.840.1.113883.6.88"

# Curated SNOMED-CT concept IDs that indicate a substance use DISORDER.
# (Deliberately NOT keyword-matching "substance" — that hits allergy findings
#  like "Animal dander (substance)". We match specific SUD concept IDs.)
SNOMED_SUD_DIAGNOSES = [
    "5602001",     # Opioid abuse
    "6525002",     # Dependent drug abuse (disorder)
    "7200002",     # Alcoholism (disorder)
    "191816009",   # Drug dependence
    "66214007",    # Substance abuse
    "26416006",    # Drug abuse
    "15167005",    # Alcohol abuse
    "7947003",     # Alcohol dependence syndrome
    "228386002",   # Alcohol misuse
    "398752005",   # Cocaine dependence
    "37344009",    # Cocaine abuse
    "85005007",    # Cannabis abuse
    "35989003",    # Cannabis dependence
    # NOTE: "Unhealthy alcohol drinking behavior" (10939881000119105) is a
    # screening FINDING, not a diagnosed disorder, and appears in routine
    # primary care. It is intentionally EXCLUDED — screening everyone is
    # normal and must not flag a facility as a treatment program.
]

# displayName keyword fallback for SUD diagnoses (case-insensitive substring).
# Only clear disorder phrasing — avoids allergy/"substance" false positives.
SNOMED_SUD_DIAGNOSIS_KEYWORDS = [
    "opioid abuse", "opioid dependence", "opiate abuse", "opiate dependence",
    "alcoholism", "alcohol abuse", "alcohol dependence", "alcohol use disorder",
    "unhealthy alcohol",
    "drug abuse", "drug dependence", "dependent drug abuse",
    "cocaine abuse", "cocaine dependence",
    "cannabis abuse", "cannabis dependence",
    "substance abuse", "substance use disorder", "substance dependence",
    "heroin", "polysubstance",
    # Deliberately NOT including "unhealthy alcohol" / screening findings —
    # those are routine primary-care screening, not a treatment-program signal.
]

# Nicotine/tobacco SNOMED concepts to EXCLUDE (mirrors ICD-10 F17 exclusion).
SNOMED_NICOTINE_EXCLUDE = [
    "89765005",    # Nicotine dependence
    "56294008",    # Tobacco dependence syndrome
]

# ============================================================================
# MAT MEDICATION LISTS — used by check_medications.py
# ============================================================================

# RxNorm ingredient codes for MAT drugs (Synthea codes meds by RxNorm number).
# These are matched in addition to the displayName keywords below.
RXNORM_MAT_STRONG = [
    "6813",      # methadone (ingredient)
    "1013072",   # methadone-related products (family)
]
RXNORM_MAT_MODERATE = [
    "1819",      # buprenorphine (ingredient)
    "351266",    # buprenorphine/naloxone sublingual (Suboxone) — seen in DEV data
    "1010600",   # buprenorphine/naloxone family
    "7242",      # naltrexone
    "1996237",   # naltrexone extended-release (Vivitrol) family
]
RXNORM_MAT_WEAK = [
    "7238",      # naloxone
    "1191",      # acamprosate? (placeholder family)
    "3554",      # disulfiram
]

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
    "drug rehabilitation",
]

# SNOMED-CT concept IDs for SUD treatment encounters (backstop for coded data).
SNOMED_SUD_ENCOUNTERS = [
    "56876005",    # Drug rehabilitation and detoxification (regime/therapy)
    "20093000",    # Alcohol rehabilitation
    "310653000",   # Drug addiction therapy
    "266707007",   # Drug addiction counseling
]

# ============================================================================
# SUD PROCEDURE KEYWORDS — used by check_procedures.py
# ============================================================================

# NOTE ON SCREENING vs TREATMENT:
# Routine SUD screening (SBIRT, DAST-10, AUDIT-C, "screening for drug abuse",
# "assessment of substance use") happens in ordinary primary care for nearly
# every patient. It is NOT a signal that a facility is a treatment program, so
# those screening terms/codes are deliberately excluded here. We count only
# treatment-oriented procedures (counseling as active therapy, toxicology
# monitoring tied to a treatment program, drug testing done as part of care).
PROCEDURE_SUD_KEYWORDS = [
    "addiction counseling",
    "substance abuse counseling",
    "substance use counseling",
    "methadone",
    "medication assisted treatment",
]

# SNOMED-CT concept IDs for SUD TREATMENT procedures (not screening).
SNOMED_SUD_PROCEDURES = [
    "390857005",         # Drug addiction therapy (procedure)
    "266707007",         # Drug addiction counseling
    "413473000",         # Counseling for substance abuse
]
