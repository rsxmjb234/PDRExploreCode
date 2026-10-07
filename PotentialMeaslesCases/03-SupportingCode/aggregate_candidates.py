"""
aggregate_candidates.py — Per-Patient Candidate Rollup
=============================================================================

Reads Output A (candidate_findings.csv — one row per file x finding) and
produces Output B (patient_candidates.csv — one row per patient, the
primary deliverable). Modeled on 42CFRQualityCheck/aggregate_sources.py, but
the grouping key changes: that project rolls up by source
(assigning_authority); this one rolls up by PATIENT — see
measles-detection-technical-plan.md Section 6.

SCOPE FOR THIS PASS: only CCD and TRN findings exist in Output A (ADT and
Lab/ORU are out of scope — see the technical plan Section 2), so
data_types_contributing will only ever contain "CCD" and/or "TRN" rows this
pass.

Per GUIDANCE.md Section 3a, this does NOT implement the already-reported
exclusion step — that's a named phase-2 feature. The output reserves a
column for it so phase 2 is a column-fill, not a schema change.

Usage:
    python aggregate_candidates.py
"""

import csv
import os
from collections import defaultdict

from normalize import patient_key
from score_model import score_patient


def aggregate(findings_csv_path, output_csv_path):
    """
    Read Output A and write Output B.

    Args:
        findings_csv_path: path to candidate_findings.csv
        output_csv_path: path for patient_candidates.csv

    Returns:
        list of dicts (the patient candidate rows), also written to CSV.
    """
    rows = _load_findings(findings_csv_path)
    if not rows:
        print("[WARNING] No findings found in:")
        print(f"         {os.path.abspath(findings_csv_path)}")
        print()
        print("  This usually means the scoring step hasn't been run yet.")
        print("  Run: python run_pipeline.py")
        return []

    # Only rows with an actual finding and a resolvable patient key count —
    # error rows and files with zero findings never reach Output A with a
    # signal_type, so this filter is mostly a safety net.
    scorable = [r for r in rows if r.get("signal_type") and r.get("mrn")]
    print(f"[OK] Loaded {len(rows)} finding rows ({len(scorable)} scorable).")

    groups = defaultdict(list)
    for r in scorable:
        key = patient_key(r["assigning_authority"], r["mrn"])
        groups[key].append(r)

    patient_rows = []
    for key, group_rows in groups.items():
        patient_rows.append(_build_patient_row(group_rows))

    # Sort: HIGH concern first, then by score descending.
    tier_order = {"HIGH": 0, "MODERATE": 1}
    patient_rows.sort(key=lambda r: (tier_order.get(r["concern_level"], 9), -r["score"]))

    _write_csv(patient_rows, output_csv_path)
    print(f"[OK] Patient candidates CSV written: {output_csv_path}")
    print(f"     Distinct patients: {len(patient_rows)}")

    high = sum(1 for r in patient_rows if r["concern_level"] == "HIGH")
    moderate = sum(1 for r in patient_rows if r["concern_level"] == "MODERATE")
    print(f"     HIGH: {high}   MODERATE: {moderate}")

    return patient_rows


def _build_patient_row(group_rows):
    """Build one Output B row from all Output A rows for a single patient."""
    first = group_rows[0]

    data_types = sorted({r["data_type"] for r in group_rows})

    findings_for_scoring = [{"signal_type": r["signal_type"]} for r in group_rows]
    score_result = score_patient(findings_for_scoring, data_types)

    # Most recent encounter: pick the max non-empty encounter_date string
    # (dates are stored as sortable strings: HL7 timestamps or YYYY-MM-DD).
    dated = [r for r in group_rows if r.get("encounter_date")]
    most_recent = max(dated, key=lambda r: r["encounter_date"]) if dated else first

    # Human-readable, de-duplicated signal summary, most informative first.
    tier_rank = {"coded_diagnosis": 0, "three_cs_pattern": 1, "keyword": 2}
    sorted_findings = sorted(
        group_rows,
        key=lambda r: tier_rank.get(r["signal_type"], 9),
    )
    seen = set()
    signal_summary_parts = []
    for r in sorted_findings:
        label = f"{r['signal_detail']} ({r['data_type']}, {r['section']})"
        if label not in seen:
            seen.add(label)
            signal_summary_parts.append(label)

    return {
        "assigning_authority": first["assigning_authority"],
        "qe": first.get("qe", ""),
        "mrn": first["mrn"],
        "patient_last_name": first.get("patient_last_name", ""),
        "patient_first_name": first.get("patient_first_name", ""),
        "patient_dob": first.get("patient_dob", ""),
        "most_recent_encounter_date": most_recent.get("encounter_date", ""),
        "most_recent_encounter_location": most_recent.get("encounter_location", ""),
        "data_types_contributing": "|".join(data_types),
        "signal_summary": "|".join(signal_summary_parts),
        "concern_level": score_result["concern_level"],
        "score": score_result["score"],
        "already_reported_status": "NOT CHECKED - v1",
        "source_file_count": len({r["path"] for r in group_rows}),
    }


def _load_findings(csv_path):
    """Load Output A rows from candidate_findings.csv."""
    rows = []
    if not os.path.isfile(csv_path):
        return rows
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _write_csv(rows, output_path):
    if not rows:
        return
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ============================================================================
# Standalone execution
# ============================================================================
if __name__ == "__main__":
    from config import get_config, FINDINGS_FILENAME, PATIENT_CANDIDATES_FILENAME

    cfg = get_config()
    findings_csv = os.path.join(cfg["output_dir"], FINDINGS_FILENAME)
    output_csv = os.path.join(cfg["output_dir"], PATIENT_CANDIDATES_FILENAME)

    print("Measles Candidate Aggregation")
    print("==============================")
    print(f"Findings CSV: {findings_csv}")
    print(f"Output CSV:   {output_csv}")
    print()

    results = aggregate(findings_csv, output_csv)

    if results:
        print()
        print("Top candidates:")
        for r in results[:10]:
            print(f"  {r['assigning_authority'][:30]:30s} MRN={r['mrn']:15s} "
                  f"{r['concern_level']:10s} score={r['score']} "
                  f"types={r['data_types_contributing']}")
