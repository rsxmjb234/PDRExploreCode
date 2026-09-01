"""
score_model.py — Weighted 0-100 Point Scoring Model
=====================================================

Takes the raw results from the checker modules for a single CCD and computes
a weighted 0-100 point score, broken down by the five signal categories:

  SUD diagnoses ................... up to 25 points
  MAT medications ................. up to 20 points
  OTP/SUD billing & procedures .... up to 25 points (billing + procedures)
  Treatment-model encounters ...... up to 25 points
  Facility name ................... up to  5 points
  --------------------------------------------------
  TOTAL ........................... up to 100 points

The caps and per-hit increments are all defined in run_pipeline_config.py so
they can be tuned during Phase 1 calibration without touching this logic.

See 01-RequirementsAndPlans/42cfr-detection-plan.md ("Scoring Approach").
"""

from run_pipeline_config import (
    SCORE_MAX_DIAGNOSES,
    SCORE_MAX_MEDICATIONS,
    SCORE_MAX_BILLING,
    SCORE_MAX_ENCOUNTERS,
    SCORE_MAX_FACILITY_NAME,
    SCORE_DIAG_PER_HIT,
    SCORE_DIAG_WEAK_PER_HIT,
    SCORE_MED_STRONG,
    SCORE_MED_MODERATE,
    SCORE_MED_WEAK,
    SCORE_BILLING_PER_HIT,
    SCORE_ENCOUNTER_PER_HIT,
    SCORE_FACILITY_HIT,
)


def score_ccd(diag_result, meds_result, billing_result, enc_result,
              proc_result, facility_result):
    """
    Compute the weighted per-CCD score from the checker outputs.

    Args:
        diag_result:     dict from check_diagnoses.check()
        meds_result:     dict from check_medications.check()
        billing_result:  dict from check_billing_codes.check()
        enc_result:      dict from check_encounters.check()
        proc_result:     dict from check_procedures.check()
        facility_result: dict from check_facility_name.check()

    Returns:
        dict with:
            ccd_score            — total 0-100
            score_diagnoses      — 0-25
            score_medications    — 0-20
            score_billing_codes  — 0-25
            score_encounters     — 0-25
            score_facility_name  — 0-5
    """
    # -----------------------------------------------------------------------
    # 1. SUD Diagnoses (up to 25)
    # Encounter diagnoses count full; problem-list-only count reduced.
    # -----------------------------------------------------------------------
    diag_points = (
        diag_result.get("sud_diagnoses_count", 0) * SCORE_DIAG_PER_HIT
        + diag_result.get("sud_diagnoses_weak_count", 0) * SCORE_DIAG_WEAK_PER_HIT
    )
    score_diagnoses = min(diag_points, SCORE_MAX_DIAGNOSES)

    # -----------------------------------------------------------------------
    # 2. MAT Medications (up to 20)
    # Sum credit by signal strength, capped.
    # -----------------------------------------------------------------------
    med_points = (
        meds_result.get("mat_strong_signal_count", 0) * SCORE_MED_STRONG
        + meds_result.get("mat_moderate_signal_count", 0) * SCORE_MED_MODERATE
        + meds_result.get("mat_weak_signal_count", 0) * SCORE_MED_WEAK
    )
    score_medications = min(med_points, SCORE_MAX_MEDICATIONS)

    # -----------------------------------------------------------------------
    # 3. OTP / SUD Billing & Procedure codes (up to 25)
    # Billing code hits + procedure hits both count toward this category.
    # -----------------------------------------------------------------------
    billing_points = (
        billing_result.get("sud_billing_code_count", 0) * SCORE_BILLING_PER_HIT
        + proc_result.get("sud_procedures_count", 0) * SCORE_BILLING_PER_HIT
    )
    score_billing_codes = min(billing_points, SCORE_MAX_BILLING)

    # -----------------------------------------------------------------------
    # 4. Treatment-model Encounters (up to 25)
    # -----------------------------------------------------------------------
    enc_points = enc_result.get("sud_encounters_count", 0) * SCORE_ENCOUNTER_PER_HIT
    score_encounters = min(enc_points, SCORE_MAX_ENCOUNTERS)

    # -----------------------------------------------------------------------
    # 5. Facility name (up to 5)
    # Any keyword match earns the (small) facility-name credit.
    # -----------------------------------------------------------------------
    facility_flagged = bool(facility_result.get("facility_name_flags", ""))
    score_facility_name = SCORE_FACILITY_HIT if facility_flagged else 0
    score_facility_name = min(score_facility_name, SCORE_MAX_FACILITY_NAME)

    # -----------------------------------------------------------------------
    # Total (already bounded by the per-category caps summing to 100)
    # -----------------------------------------------------------------------
    ccd_score = (
        score_diagnoses
        + score_medications
        + score_billing_codes
        + score_encounters
        + score_facility_name
    )

    return {
        "ccd_score": ccd_score,
        "score_diagnoses": score_diagnoses,
        "score_medications": score_medications,
        "score_billing_codes": score_billing_codes,
        "score_encounters": score_encounters,
        "score_facility_name": score_facility_name,
    }


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    # Example: a strong Part 2 CCD
    example = score_ccd(
        diag_result={"sud_diagnoses_count": 2, "sud_diagnoses_weak_count": 0},
        meds_result={"mat_strong_signal_count": 1, "mat_moderate_signal_count": 0,
                     "mat_weak_signal_count": 0},
        billing_result={"sud_billing_code_count": 2},
        enc_result={"sud_encounters_count": 1},
        proc_result={"sud_procedures_count": 1},
        facility_result={"facility_name_flags": "recovery"},
    )
    print("Example strong Part 2 CCD score:")
    for k, v in example.items():
        print(f"  {k}: {v}")
