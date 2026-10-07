"""
score_model.py — Per-Patient Measles Concern Scoring
=============================================================================

Per GUIDANCE.md Section 6 and measles-detection-technical-plan.md Section 5:
  - Score is per PATIENT, not per document — this module scores a patient
    given ALL findings rolled up across their files (see
    aggregate_candidates.py for the rollup; this module is the pure
    point-scoring function, called once per patient after rollup).
  - A coded measles diagnosis is weighted highest.
  - The "three C's + rash" pattern is a secondary, moderate-weight signal.
  - A bare keyword hit alone is the weakest tier.
  - Independent signals from DIFFERENT data types raise concern more than
    the same signal repeated — a cross-data-type bonus is added once if 2+
    distinct data types contributed a signal.
  - Two tiers only: HIGH and MODERATE (anything that scored above zero).

This is intentionally simple point arithmetic, not a validated clinical
score — consistent with GUIDANCE.md's explicit framing throughout.
"""

from config import (
    SCORE_CODED_DIAGNOSIS,
    SCORE_THREE_CS_PATTERN,
    SCORE_BARE_KEYWORD,
    SCORE_CROSS_DATA_TYPE_BONUS,
    THRESHOLD_HIGH,
)

_TIER_POINTS = {
    "coded_diagnosis": SCORE_CODED_DIAGNOSIS,
    "three_cs_pattern": SCORE_THREE_CS_PATTERN,
    "keyword": SCORE_BARE_KEYWORD,
    # isolation_precaution is a corroborating-only signal (GUIDANCE.md
    # Section 5, ADT row) — contributes 0 points on its own.
    "isolation_precaution": 0,
}


def score_patient(findings, data_types):
    """
    Compute a concern score + tier for one patient, given all findings
    rolled up across every file that mentioned them.

    Args:
        findings: list of dicts, each with at least "signal_type"
            (one of "coded_diagnosis" / "three_cs_pattern" / "keyword" /
            "isolation_precaution") — pooled across every CCD/ADT/TRN file
            for this patient.
        data_types: set/list of data types ("CCD", "ADT", "TRN") that
            contributed at least one finding for this patient.

    Returns:
        dict:
            score (int) — the raw point total (not capped at 100; this is a
                concern score, not a percentage).
            concern_level (str) — "HIGH" or "MODERATE". Callers should not
                call this for a patient with zero findings (score is 0,
                tier is "NONE" — not a candidate, should not be surfaced).
    """
    if not findings:
        return {"score": 0, "concern_level": "NONE"}

    # Take the single highest-value signal type present, not a sum of every
    # finding — repeating the same signal many times should not alone push
    # a patient from MODERATE to HIGH (GUIDANCE.md Section 6, bullet 3: it's
    # DIFFERENT data types that should raise concern, not repetition).
    best_points = max(_TIER_POINTS.get(f.get("signal_type", ""), 0) for f in findings)

    distinct_types = set(data_types)
    cross_type_bonus = SCORE_CROSS_DATA_TYPE_BONUS if len(distinct_types) >= 2 else 0

    score = best_points + cross_type_bonus
    concern_level = "HIGH" if score >= THRESHOLD_HIGH else "MODERATE"

    return {"score": score, "concern_level": concern_level}


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    cases = [
        ([{"signal_type": "coded_diagnosis"}], {"CCD"}),
        ([{"signal_type": "three_cs_pattern"}], {"ADT"}),
        ([{"signal_type": "three_cs_pattern"}], {"ADT", "TRN"}),
        ([{"signal_type": "keyword"}], {"TRN"}),
        ([{"signal_type": "keyword"}, {"signal_type": "keyword"}], {"TRN"}),
        ([], set()),
    ]
    for findings, types in cases:
        result = score_patient(findings, types)
        print(f"findings={len(findings)} types={types}  ->  {result}")
