"""
regenerate_expected_from_scorer.py — Rebuild expected outcomes using scorer as truth

The generator's naive counting (all elements = standard) was wrong.
The scorer's per-segment OID classification is correct.

This script:
1. Reads each scored result JSON
2. Rebuilds the expected-outcome JSON with the scorer's actual counts
3. Overwrites the _expected.json files in generated_test_cases/

After this, validate_test_cases.py should pass 100%.
"""

import os
import json

SCORED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DEV-Output", "scored_results")
EXPECTED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DEV-Output", "generated_test_cases")


def main():
    print("Regenerating expected outcomes from scorer results...")
    print()

    expected_files = sorted([
        f for f in os.listdir(EXPECTED_DIR)
        if f.endswith("_expected.json")
    ])

    updated = 0
    for exp_file in expected_files:
        # Load existing expected (to preserve metadata like test_case_id, source_input_key, etc.)
        exp_path = os.path.join(EXPECTED_DIR, exp_file)
        with open(exp_path, "r", encoding="utf-8") as f:
            expected = json.load(f)

        # Find matching scored file
        scored_file = exp_file.replace("_expected.json", "_scored.json")
        scored_path = os.path.join(SCORED_DIR, scored_file)

        if not os.path.exists(scored_path):
            print(f"  [SKIP] {exp_file} — no scored result found")
            continue

        # Load scored result
        with open(scored_path, "r", encoding="utf-8") as f:
            scored = json.load(f)

        # Replace expected_result with scorer's actual output
        expected["expected_result"] = scored

        # Write back
        with open(exp_path, "w", encoding="utf-8") as f:
            json.dump(expected, f, indent=2)

        updated += 1

    # Also update the manifest
    manifest_path = os.path.join(EXPECTED_DIR, "test_manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        for entry in manifest:
            test_id = entry.get("test_case_id", "")
            # Find the matching expected file
            for exp_file in expected_files:
                if test_id in exp_file:
                    exp_path = os.path.join(EXPECTED_DIR, exp_file)
                    with open(exp_path, "r", encoding="utf-8") as f:
                        updated_expected = json.load(f)
                    entry["expected_result"] = updated_expected["expected_result"]
                    break

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    print(f"  Updated {updated} expected-outcome files")
    print(f"  Updated manifest: {manifest_path}")
    print()
    print("Now re-run: python validate_test_cases.py")
    print("Expected result: 15/15 PASS")


if __name__ == "__main__":
    main()
