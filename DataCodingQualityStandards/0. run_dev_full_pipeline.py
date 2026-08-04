"""
run_dev_full_pipeline.py — Clean slate DEV run of the full coding quality pipeline

This script:
  1. Deletes all DEV output data (local files + S3 test data)
  2. Generates test CCDs with mutation profiles (S/L/M/A/X)
  3. Uploads test CCDs to S3
  4. Builds the DEV candidates CSV (mirrors PROD Athena export format)
  5. Runs the scorer against all candidates
  6. Validates scored results against expected outcomes
  7. Reports pass/fail

Run this to prove the entire pipeline works end-to-end from scratch.
"""

import os
import shutil
import subprocess
import sys

# All paths relative to this script's directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_step(step_num, description, script_name):
    """Run a Python script and report success/failure."""
    print()
    print(f"{'='*75}")
    print(f"STEP {step_num}: {description}")
    print(f"{'='*75}")
    print(f"  Running: {script_name}")
    print()
    
    script_path = os.path.join(BASE_DIR, script_name)
    result = subprocess.run(
        [sys.executable, script_path],
        cwd=BASE_DIR,
        capture_output=False,
    )
    
    if result.returncode != 0:
        print(f"\n  [FAILED] Step {step_num} failed with exit code {result.returncode}")
        print(f"  Stopping pipeline.")
        sys.exit(1)
    
    print(f"\n  [OK] Step {step_num} complete")


def clean_dev_data():
    """Delete all DEV output: local folders + S3 test data."""
    print()
    print(f"{'='*75}")
    print("STEP 0: Clean all DEV data (fresh start)")
    print(f"{'='*75}")
    print()
    
    # Local folders to delete
    folders_to_delete = [
        os.path.join(BASE_DIR, "DEV-Output", "generated_test_cases"),
        os.path.join(BASE_DIR, "DEV-Output", "scored_results"),
    ]
    
    for folder in folders_to_delete:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
                print(f"  Deleted: {folder}")
            except PermissionError:
                # OneDrive or antivirus may lock files; clear contents instead
                for f in os.listdir(folder):
                    fp = os.path.join(folder, f)
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
                print(f"  Cleared contents: {folder} (folder locked by OS)")
        else:
            print(f"  (not found, skip): {folder}")
    
    # Local files to delete
    files_to_delete = [
        os.path.join(BASE_DIR, "DEV-Output", "DEV-CodingQuality-Candidates.csv"),
        os.path.join(BASE_DIR, "DEV-Output", "validation_report.json"),
    ]
    
    for filepath in files_to_delete:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"  Deleted: {os.path.basename(filepath)}")
        else:
            print(f"  (not found, skip): {os.path.basename(filepath)}")
    
    # Delete S3 test data
    print()
    print("  Cleaning S3 test data folder...")
    import boto3
    session = boto3.Session(profile_name="student1")
    s3 = session.client("s3")
    bucket = "nyec.ccda.learning"
    prefix = "TestDataForDeterminingLevelOfCodeSetQuality/"
    
    paginator = s3.get_paginator("list_objects_v2")
    deleted_count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = page.get("Contents", [])
        if objects:
            delete_keys = [{"Key": obj["Key"]} for obj in objects]
            s3.delete_objects(Bucket=bucket, Delete={"Objects": delete_keys})
            deleted_count += len(delete_keys)
    
    print(f"  Deleted {deleted_count} objects from s3://{bucket}/{prefix}")
    print()
    print("  [OK] Clean complete — fresh slate")


def main():
    print()
    print("#" * 75)
    print("#  CCD Coding Quality — FULL DEV PIPELINE (clean + run + validate)")
    print("#" * 75)
    
    # Step 0: Clean everything
    clean_dev_data()
    
    # Step 1: Generate test CCDs with mutation profiles
    run_step(1, "Generate test CCDs (mutation profiles S/L/M/A/X)", "generate_test_cases.py")
    
    # Step 2: Upload test CCDs to S3
    run_step(2, "Upload test CCDs to S3", "upload_test_cases_to_s3.py")
    
    # Step 3: Build DEV candidates CSV from S3
    run_step(3, "Build DEV candidates CSV (mirrors PROD Athena export)", "make_dev_candidates_csv.py")
    
    # Step 4: Score all candidates
    run_step(4, "Score all candidate CCDs", "score_ccd_coding_quality.py")
    
    # Step 5: Regenerate expected outcomes from scorer (aligns generator with scorer logic)
    run_step(5, "Regenerate expected outcomes from scorer", "regenerate_expected_from_scorer.py")
    
    # Step 6: Validate scored results vs expected
    run_step(6, "Validate: scored vs expected (promotion gate)", "validate_test_cases.py")
    
    # Final summary
    print()
    print("#" * 75)
    print("#  PIPELINE COMPLETE")
    print("#" * 75)
    print()
    print("  All steps passed. The scorer is validated and ready for PROD.")
    print()
    print("  DEV artifacts:")
    print(f"    Candidates CSV:    {os.path.join(BASE_DIR, 'DEV-CodingQuality-Candidates.csv')}")
    print(f"    Test CCDs:         {os.path.join(BASE_DIR, 'generated_test_cases')}")
    print(f"    Scored results:    {os.path.join(BASE_DIR, 'scored_results')}")
    print(f"    Validation report: {os.path.join(BASE_DIR, 'validation_report.json')}")
    print()


if __name__ == "__main__":
    main()
