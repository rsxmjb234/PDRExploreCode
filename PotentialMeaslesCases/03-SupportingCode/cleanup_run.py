"""
cleanup_run.py — Delete all results for a DEV or PROD run so you can start fresh.
==================================================================================

Removes the findings CSV (Output A), patient candidates CSV (Output B),
errors log, and run summary. Does NOT touch the candidate CSVs in
05-Candidates/ — just the output of a scan run.

Usage:
    python cleanup_run.py DEV
    python cleanup_run.py PROD
"""

import os
import sys


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if len(sys.argv) < 2 or sys.argv[1].upper() not in ("DEV", "PROD"):
        print("Usage: python cleanup_run.py DEV")
        print("       python cleanup_run.py PROD")
        print()
        print("Deletes the findings CSV, patient candidates CSV, errors log,")
        print("and summary so run_pipeline.py starts fresh. Does NOT delete")
        print("the candidate CSVs in 05-Candidates/.")
        sys.exit(1)

    profile_name = sys.argv[1].upper()
    output_dir = os.path.abspath(os.path.join("..", "06-Results", "Output", profile_name))

    print("=" * 60)
    print(f"Cleanup {profile_name} Results")
    print("=" * 60)
    print(f"  Will delete files in: {output_dir}")
    print()

    if not os.path.isdir(output_dir):
        print("  [OK] Nothing to clean — directory does not exist.")
        return

    files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]

    if not files:
        print("  [OK] Nothing to clean — directory is already empty.")
        return

    print(f"  Found {len(files)} file(s) to remove:")
    for f in files:
        print(f"    - {f}")
    print()
    print("  NOTE: this deletes the restart ledger too (the findings CSV IS")
    print("  the ledger for this project). The next run will re-download and")
    print("  re-score every candidate file from scratch.")
    print()

    confirm = input("  Type YES to delete: ").strip()
    if confirm != "YES":
        print("  Cancelled.")
        return

    deleted = 0
    for f in files:
        try:
            os.remove(os.path.join(output_dir, f))
            deleted += 1
        except OSError as e:
            print(f"  [WARNING] Could not delete: {f} ({e})")

    print()
    print(f"  [OK] Removed {deleted} file(s) from: {output_dir}")
    print(f"  Run 'python run_pipeline.py' to score again from scratch.")


if __name__ == "__main__":
    main()
