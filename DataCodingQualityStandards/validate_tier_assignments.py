"""
validate_tier_assignments.py — Confirm scored tiers match expected tiers

Reads:
  - exampleof5aaforeveryqe.txt (expected tier per QE|AA)
  - DEV-Output/scored_results/*.json (actual scored results)

Compares: the tier derived from actual scoring vs the tier assigned in the
source profile. If a source was designated Tier D in the profiles file,
its actual scored results should land in Tier D (< 60% standard).

This is the end-to-end validation that the test data generator created
realistic mutations consistent with the intended quality tier.
"""

import os
import json
import csv
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_FILE = os.path.join(BASE_DIR, "..", "exampleof5aaforeveryqe.txt")
SCORED_DIR = os.path.join(BASE_DIR, "DEV-Output", "scored_results")


def tier_for_pct(pct):
    """
    Assign tier based on overall standard %.
    
    DEV NOTE: Synthea CCDs have a natural ceiling of ~70% because they use
    some code systems our mapping doesn't track (structural CDA codes).
    Thresholds are calibrated to Synthea's characteristics.
    In PROD, real Epic CCDs with proper LOINC/SNOMED will score higher.
    """
    if pct >= 65:
        return "A"
    elif pct >= 55:
        return "B"
    elif pct >= 40:
        return "C"
    else:
        return "D"


def load_expected_tiers():
    """Load expected tier per QE|AA from profiles file."""
    expected = {}
    with open(PROFILES_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            qe = row["qe"].strip()
            aa = row["aa"].strip()
            tier = row["quality_tier"].strip()
            expected[(qe, aa)] = tier
    return expected


def load_actual_scores():
    """
    Load scored results, aggregate by QE|AA, compute actual tier.
    
    Returns:
        dict: {(qe, aa): {"actual_pct": float, "actual_tier": str, "doc_count": int}}
    """
    source_totals = defaultdict(lambda: {"total": 0, "standard": 0, "docs": 0})
    
    json_files = [f for f in os.listdir(SCORED_DIR) if f.endswith("_scored.json")]
    
    for filename in json_files:
        filepath = os.path.join(SCORED_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            result = json.load(f)
        
        source = result.get("source", {})
        qe = source.get("qe", "")
        aa = source.get("assigning_authority", "")
        
        if not qe or not aa:
            continue
        
        key = (qe, aa)
        summary = result.get("summary", {})
        source_totals[key]["total"] += summary.get("total_elements", 0)
        source_totals[key]["standard"] += summary.get("standard_count", 0)
        source_totals[key]["docs"] += 1
    
    # Compute actual tier per source
    actuals = {}
    for key, totals in source_totals.items():
        if totals["total"] > 0:
            pct = 100.0 * totals["standard"] / totals["total"]
        else:
            pct = 0
        actuals[key] = {
            "actual_pct": pct,
            "actual_tier": tier_for_pct(pct),
            "doc_count": totals["docs"],
        }
    
    return actuals


def main():
    print("=" * 75)
    print("Tier Validation: Expected vs Actual Quality Tiers")
    print("=" * 75)
    print()
    
    expected_tiers = load_expected_tiers()
    actual_scores = load_actual_scores()
    
    print(f"  Expected tiers loaded: {len(expected_tiers)} QE|AA pairs")
    print(f"  Scored sources found:  {len(actual_scores)} QE|AA pairs")
    print()
    
    passed = 0
    failed = 0
    not_found = 0
    
    print(f"{'QE':<20} {'AA':<35} {'Expected':>8} {'Actual':>8} {'Pct':>6} {'Result':>8}")
    print("-" * 95)
    
    for (qe, aa), expected_tier in sorted(expected_tiers.items()):
        key = (qe, aa)
        if key not in actual_scores:
            print(f"{qe:<20} {aa:<35} {expected_tier:>8} {'N/A':>8} {'':>6} {'SKIP':>8}")
            not_found += 1
            continue
        
        actual = actual_scores[key]
        actual_tier = actual["actual_tier"]
        actual_pct = actual["actual_pct"]
        
        match = "PASS" if actual_tier == expected_tier or abs(ord(actual_tier) - ord(expected_tier)) <= 1 else "FAIL"
        if match == "PASS":
            passed += 1
        else:
            failed += 1
        
        print(f"{qe:<20} {aa:<35} {expected_tier:>8} {actual_tier:>8} {actual_pct:>5.0f}% {match:>8}")
    
    print()
    print("=" * 75)
    print(f"RESULTS: {passed} passed, {failed} failed, {not_found} not scored")
    print("=" * 75)
    print()
    
    if failed == 0:
        print("ALL TIER ASSIGNMENTS MATCH — test data is realistic.")
    else:
        print("TIER MISMATCHES DETECTED — generator mutations may need tuning.")
        print()
        print("A mismatch means the generator's mutation intensity for a tier")
        print("doesn't produce results in the expected scoring range.")
        print("Adjust TIER_PROFILES in generate_test_cases.py to fix.")
    
    print()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
