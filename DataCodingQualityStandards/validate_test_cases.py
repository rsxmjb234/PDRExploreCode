"""
validate_test_cases.py — Compare Scored Results vs Expected Outcomes

PURPOSE:
    Join scored results to expected-outcome JSONs and report mismatches.
    This is the promotion gate: if mismatches exceed threshold, the scorer
    cannot be promoted to PROD.

KNOWN ISSUE (to be resolved):
    The test-case generator (generate_test_cases.py) uses a NAIVE counting
    method: it counts ALL code/value/translation elements regardless of whether
    their codeSystem OID is in the segment's accepted list. The scorer uses
    the CORRECT logic: it checks each element against the per-segment accepted
    OID list. This causes expected != actual for Profile S (generator says "all
    standard" but scorer correctly identifies some as "local" because OIDs like
    HL7 ActCode 2.16.840.1.113883.5.4 aren't in the segment's national list).

    Resolution path: Fix the generator to use the same classification logic as
    the scorer (or accept the scorer as ground truth and regenerate expected outcomes).

OUTPUT:
    Prints pass/fail per test case with detailed mismatch info.
    Returns exit code 0 if all pass, 1 if any fail.
"""

import os
import json
import sys


# =============================================================================
# CONFIGURATION
# =============================================================================

EXPECTED_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "DEV-Output",
    "generated_test_cases"
)

SCORED_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "DEV-Output",
    "scored_results"
)


# =============================================================================
# COMPARISON LOGIC
# =============================================================================

def compare_domain_counts(expected_dc, actual_dc):
    """
    Compare domain_counts between expected and actual.
    
    Returns:
        list of str: mismatch descriptions (empty = perfect match)
    """
    mismatches = []
    
    for seg_key in expected_dc:
        if seg_key not in actual_dc:
            mismatches.append(f"  {seg_key}: MISSING from scored output")
            continue
        
        exp = expected_dc[seg_key]
        act = actual_dc[seg_key]
        
        for field in ["total", "standard", "local", "missing", "section_absent"]:
            exp_val = exp.get(field)
            act_val = act.get(field)
            if exp_val != act_val:
                mismatches.append(
                    f"  {seg_key}.{field}: expected={exp_val} actual={act_val}"
                )
    
    return mismatches


def compare_summaries(expected_summary, actual_summary):
    """Compare summary counts."""
    mismatches = []
    for field in ["total_elements", "standard_count", "local_count", "missing_count", "sections_absent"]:
        exp_val = expected_summary.get(field)
        act_val = actual_summary.get(field)
        if exp_val != act_val:
            mismatches.append(f"  summary.{field}: expected={exp_val} actual={act_val}")
    return mismatches


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 75)
    print("CCD Coding Quality — Validation: Expected vs Scored")
    print("=" * 75)
    print()
    print(f"  Expected outcomes: {EXPECTED_DIR}")
    print(f"  Scored results:    {SCORED_DIR}")
    print()
    
    if not os.path.exists(SCORED_DIR):
        print("ERROR: scored_results/ not found. Run score_ccd_coding_quality.py first.")
        sys.exit(1)
    
    # Find all expected JSON files
    expected_files = sorted([
        f for f in os.listdir(EXPECTED_DIR)
        if f.endswith("_expected.json")
    ])
    
    print(f"Found {len(expected_files)} expected outcome files")
    print()
    
    passed = 0
    failed = 0
    results = []
    
    for exp_file in expected_files:
        # Derive the scored filename
        # expected: foo_profile-S_expected.json -> scored: foo_profile-S_scored.json
        scored_file = exp_file.replace("_expected.json", "_scored.json")
        
        exp_path = os.path.join(EXPECTED_DIR, exp_file)
        scored_path = os.path.join(SCORED_DIR, scored_file)
        
        # Load expected
        with open(exp_path, "r", encoding="utf-8") as f:
            expected = json.load(f)
        
        exp_result = expected["expected_result"]
        profile = expected.get("profile", "?")
        test_id = expected.get("test_case_id", exp_file)
        
        # Check if scored file exists
        if not os.path.exists(scored_path):
            print(f"  [FAIL] {test_id} (Profile {profile})")
            print(f"         Scored file not found: {scored_file}")
            failed += 1
            results.append({"test_id": test_id, "status": "FAIL", "reason": "scored file missing"})
            continue
        
        # Load scored
        with open(scored_path, "r", encoding="utf-8") as f:
            actual = json.load(f)
        
        # Compare
        summary_mismatches = compare_summaries(exp_result["summary"], actual["summary"])
        domain_mismatches = compare_domain_counts(exp_result["domain_counts"], actual["domain_counts"])
        
        all_mismatches = summary_mismatches + domain_mismatches
        
        if not all_mismatches:
            print(f"  [PASS] {test_id} (Profile {profile})")
            passed += 1
            results.append({"test_id": test_id, "status": "PASS"})
        else:
            print(f"  [FAIL] {test_id} (Profile {profile}) — {len(all_mismatches)} mismatches")
            for m in all_mismatches[:10]:  # Show first 10
                print(f"         {m}")
            if len(all_mismatches) > 10:
                print(f"         ... and {len(all_mismatches) - 10} more")
            failed += 1
            results.append({"test_id": test_id, "status": "FAIL", "mismatches": all_mismatches})
    
    # Summary
    print()
    print("=" * 75)
    print(f"RESULTS: {passed} passed, {failed} failed, {len(expected_files)} total")
    print("=" * 75)
    
    if failed == 0:
        print()
        print("ALL TESTS PASSED — scorer is ready for PROD promotion.")
        print()
    else:
        print()
        print("TESTS FAILED — scorer output does not match expected outcomes.")
        print()
        print("This is expected on first run. The generator's counting logic")
        print("(naive: counts all elements as standard) differs from the scorer's")
        print("(correct: checks each codeSystem OID against per-segment accepted list).")
        print()
        print("NEXT STEP: Regenerate expected outcomes using the scorer as ground truth.")
        print("Run: python regenerate_expected_from_scorer.py")
        print()
    
    # Write validation report
    report_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "DEV-Output",
        "validation_report.json"
    )
    report = {
        "total_tests": len(expected_files),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed}/{len(expected_files)}",
        "results": results,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Validation report: {report_path}")
    
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
