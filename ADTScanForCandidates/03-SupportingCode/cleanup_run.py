"""
cleanup_run.py — Delete all results + the ledger for a DEV or PROD run so you
can start a fresh scan from scratch.
==============================================================================

Removes the processed-files ledger, matches detail, candidate coverage, ADT
tracking records, errors log, and run summary for the given profile. Does NOT
touch the lookup CSV (05-Candidates/known_aa_mrn.csv) — just the output of a
scan run.

Without this, re-running scan_bucket.py after a cleanup would be impossible
to distinguish from a genuine restart — the ledger would still say every file
is "done." Use this only when you actually want to re-scan from zero.

Usage:
    python cleanup_run.py DEV
    python cleanup_run.py PROD
"""

import os
import sys


def main():
    # Auto-set working directory to the folder this script lives in
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if len(sys.argv) < 2 or sys.argv[1].upper() not in ("DEV", "PROD"):
        print("Usage: python cleanup_run.py DEV")
        print("       python cleanup_run.py PROD")
        print()
        print("Deletes the ledger, matches, coverage, tracking, errors, and")
        print("summary for that profile so scan_bucket.py starts fresh.")
        print("Does NOT delete the lookup CSV in 05-Candidates/.")
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
    print("  NOTE: this deletes the processed-files ledger too. The next run")
    print("  of scan_bucket.py will treat EVERY file as unprocessed and")
    print("  re-download/re-scan the whole bucket (or prefix/max_files cap).")
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
    print(f"  Run 'python scan_bucket.py' to scan again from scratch.")


if __name__ == "__main__":
    main()
