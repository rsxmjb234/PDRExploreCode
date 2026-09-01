"""
cleanup_run.py — Delete all results for a DEV or PROD run so you can start fresh.
==================================================================================

Removes scored JSONs, aggregate CSVs, gen-pop stats, and QE letters.
Does NOT touch the candidates CSV — just the output from a pipeline run.

Usage:
    python cleanup_run.py DEV
    python cleanup_run.py PROD
"""

import os
import sys
import shutil

# Add this directory to path so we can import run_pipeline_config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    # Auto-set working directory to the folder this script lives in
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if len(sys.argv) < 2 or sys.argv[1].upper() not in ("DEV", "PROD"):
        print("Usage: python cleanup_run.py DEV")
        print("       python cleanup_run.py PROD")
        print()
        print("Deletes all results (scored JSONs, aggregates, letters) so you")
        print("can re-run the pipeline from scratch. Does NOT delete candidates.")
        sys.exit(1)

    profile_name = sys.argv[1].upper()
    if profile_name == "DEV":
        output_dir = os.path.abspath(os.path.join("..", "06-Results", "Output", "DEV"))
    else:
        output_dir = os.path.abspath(os.path.join("..", "06-Results", "Output", "PROD"))

    print("=" * 60)
    print(f"Cleanup {profile_name} Results")
    print("=" * 60)
    print(f"  Will delete: {output_dir}")
    print()

    if not os.path.isdir(output_dir):
        print("  [OK] Nothing to clean — directory does not exist.")
        return

    # Show what's there
    file_count = 0
    for root, dirs, files in os.walk(output_dir):
        file_count += len(files)

    print(f"  Found {file_count} files to remove.")
    print()

    # Confirm
    confirm = input("  Type YES to delete: ").strip()
    if confirm != "YES":
        print("  Cancelled.")
        return

    # Delete contents (keep the top-level folder — OneDrive can hold locks on it)
    deleted = 0
    for root, dirs, files in os.walk(output_dir, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
                deleted += 1
            except OSError as e:
                print(f"  [WARNING] Could not delete: {os.path.join(root, f)} ({e})")
        # Remove subdirectories (but not the top-level output_dir itself)
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass  # OK if OneDrive holds it briefly

    print()
    print(f"  [OK] Removed {deleted} files from: {output_dir}")
    print(f"  Run 'python run_pipeline.py' to score again from scratch.")


if __name__ == "__main__":
    main()
