"""
findandsaveEHRfromTRN.py — Extract Sending Facility & Application from TRN Files
                           (FULL FILE DOWNLOAD + HL7v2 PARSING)

================================================================================
GOAL
================================================================================
For each TRN (HL7v2 transaction) file, extract:
  - MSH-3: Sending Application (the software/system that created the message)
  - MSH-4: Sending Facility (the organization that sent it)

These two fields tell us WHO is sending data and WHAT system they use.

================================================================================
STRATEGY
================================================================================
1. Read a list of TRN S3 paths from an input CSV (with bucket per row)
2. Download the TRN file from S3
3. Parse the first line (MSH segment) to extract fields 3 and 4
4. Write results to an output CSV

TRN files are HL7v2 pipe-delimited messages. The MSH segment is always the
first line and follows this structure:
  MSH|^~\&|SendingApp|SendingFacility|ReceivingApp|ReceivingFacility|...
       [1]  [2]       [3]            [4]           [5]              [6]

================================================================================
RESILIENCY / RESTART CAPABILITY
================================================================================
Same pattern as findandsaveEHRfromCCD-EntireCCD.py:
  - Load already-processed paths from output CSV at startup
  - Skip files already processed
  - Flush to disk every 200 records
  - max_files applied AFTER filtering (next batch, not first batch)

TO RE-PROCESS: Delete the output CSV and run again.

================================================================================
INPUT / OUTPUT
================================================================================

INPUT CSV (from findcandidatesforexplore.sql — filter to TRN data_type):
  Required columns: "bucket", "key"
  Optional columns: "qe", "assigning_authority"

OUTPUT CSV:
  One row per TRN with: Path, FileName, QE, Input_Assigning_Authority,
  ProcessingTimeMS, FileSizeBytes, MSH3_SendingApplication,
  MSH4_SendingFacility, Parse_type

================================================================================
CONFIGURATION -- Edit the DEV/PROD profiles below before running
================================================================================
"""

import boto3
import csv
import os
import time
from datetime import datetime


# ============================================================================
# CHOOSE YOUR PROFILE -- set to "DEV" or "PROD"
# ============================================================================

ACTIVE_PROFILE = "PROD"

# ============================================================================
# DEV PROFILE
# ============================================================================

DEV = {
    "aws_profile": "student1",
    "default_bucket": "nyec.ccda.learning",
    "allowed_buckets": ["nyec.ccda.learning"],
    "input_csv": "DEV-CandidateTRNs.csv",
    "output_csv": "DEV-TRN_SendingFacility.csv",
    "max_files": 2000,
}

# ============================================================================
# PROD PROFILE -- Multi-bucket, reads bucket from each CSV row
# ============================================================================

PROD = {
    "aws_profile": "default",
    "default_bucket": None,
    "allowed_buckets": [
        "nyec-pdr-prod-hixny",
        "nyec-pdr-prod-hixny-part2",
        "nyec-pdr-prod-techbd",
        "nyec-pdr-prod-techbd-part2",
        "nyec-pdr-prod-healtheconnections",
        "nyec-pdr-prod-healtheconnections-part2",
        "nyec-pdr-prod-rochester",
        "nyec-pdr-prod-rochester-part2",
        "nyec-pdr-prod-bronx",
        "nyec-pdr-prod-bronx-part2",
        "nyec-pdr-prod-healthix",
        "nyec-pdr-prod-healthix-part2",
    ],
    "input_csv": "Export-Athena-TRN-candidates.csv",
    "output_csv": "PROD-TRN_SendingFacility.csv",
    "max_files": 30000,
}

# ============================================================================
# LOAD THE ACTIVE PROFILE
# ============================================================================

if ACTIVE_PROFILE.upper() == "PROD":
    config = PROD
else:
    config = DEV

AWS_PROFILE = config["aws_profile"]
DEFAULT_BUCKET = config.get("default_bucket")
ALLOWED_BUCKETS = set(config.get("allowed_buckets", []))
INPUT_CSV_FILENAME = config["input_csv"]
OUTPUT_CSV_FILENAME = config["output_csv"]
MAX_FILES = config["max_files"]

# Add today's date to output filename
_date_stamp = datetime.now().strftime("%m-%d-%Y")
_base, _ext = os.path.splitext(OUTPUT_CSV_FILENAME)
OUTPUT_CSV_FILENAME = f"{_base}_{_date_stamp}{_ext}"

INPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "05-Candidates", INPUT_CSV_FILENAME)
_output_landscape = "DEV" if ACTIVE_PROFILE == "DEV" else "PROD"
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "06-Results", "Output", _output_landscape, OUTPUT_CSV_FILENAME)

# Ensure Results folder exists
os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)


# ============================================================================
# COLUMN DEFINITIONS
# ============================================================================

OUTPUT_FIELDS = [
    "Path",                           # Full S3 path (s3://bucket/key)
    "FileName",                       # Just the filename
    "QE",                             # QE from input CSV
    "Input_Assigning_Authority",      # Assigning authority from input CSV
    "ProcessingTimeMS",               # Time to download + extract (milliseconds)
    "FileSizeBytes",                  # File size downloaded
    "MSH3_SendingApplication",        # MSH-3: what software/system sent this
    "MSH4_SendingFacility",           # MSH-4: what organization sent this
    "Parse_type",                     # Always "TRN" for this script
    "Data_Type",                      # Always "TRN" — distinguishes from CCD results
]

PARSE_TYPE = "TRN"
FLUSH_EVERY_N_RECORDS = 200


# ============================================================================
# HELPER: Restart Support
# ============================================================================

def load_already_processed_paths(output_csv_path):
    """Read existing output CSV and return set of already-processed S3 paths."""
    already_done = set()
    if not os.path.exists(output_csv_path):
        return already_done
    try:
        with open(output_csv_path, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                path = row.get("Path", "").strip()
                if path:
                    already_done.add(path)
    except Exception as e:
        print(f"  [WARNING] Could not read existing output CSV: {e}")
        return set()
    return already_done


# ============================================================================
# HELPER: AWS / S3
# ============================================================================

def create_s3_client(profile_name):
    """Create a boto3 S3 client using the specified AWS CLI profile."""
    session = boto3.Session(profile_name=profile_name)
    return session.client("s3")


# ============================================================================
# HELPER: Read Input CSV
# ============================================================================

def read_input_csv_file(csv_path, default_bucket=None, allowed_buckets=None, max_files=None):
    """
    Read bucket/key locations from the input CSV.
    Accepts .xml files (TRNs in PDR are stored as .xml despite being HL7v2).
    """
    documents = []
    allowed_buckets = set(allowed_buckets or [])

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        if not reader.fieldnames:
            raise ValueError("Input CSV has no header row")

        header_map = {name.strip().lower(): name for name in reader.fieldnames}
        key_column = header_map.get("key")
        bucket_column = header_map.get("bucket")
        qe_column = header_map.get("qe")
        aa_column = header_map.get("assigning_authority")

        if not key_column:
            raise ValueError('Input CSV must contain a "key" column')
        if not bucket_column and not default_bucket:
            raise ValueError('PROD input CSV must contain a "bucket" column.')

        for row_number, row in enumerate(reader, start=2):
            raw_key = (row.get(key_column) or "").strip()
            bucket = (row.get(bucket_column) or "").strip() if bucket_column else ""
            qe = (row.get(qe_column) or "").strip() if qe_column else ""
            aa = (row.get(aa_column) or "").strip() if aa_column else ""

            if not raw_key:
                continue

            if raw_key.lower().startswith("s3://"):
                s3_location = raw_key[5:]
                parsed_bucket, separator, parsed_key = s3_location.partition("/")
                if not separator or not parsed_key:
                    continue
                bucket = bucket or parsed_bucket
                key = parsed_key
            else:
                key = raw_key

            bucket = bucket or default_bucket
            if not bucket:
                continue

            if allowed_buckets and bucket not in allowed_buckets:
                continue

            documents.append({
                "bucket": bucket,
                "key": key,
                "path": f"s3://{bucket}/{key}",
                "qe": qe,
                "assigning_authority": aa,
            })

            if max_files and len(documents) >= max_files:
                break

    return documents


# ============================================================================
# CORE: Extract MSH-3 and MSH-4 from HL7v2 TRN content
# ============================================================================

def extract_trn_signals(file_bytes):
    """
    Parse an HL7v2 message and extract MSH-3 (Sending Application)
    and MSH-4 (Sending Facility).

    HL7v2 MSH segment structure (pipe-delimited):
      MSH|^~\\&|SendingApp|SendingFacility|ReceivingApp|ReceivingFacility|...
      [0] [1]   [2]        [3]             [4]          [5]              [6]

    Note: MSH-1 is the field separator (|) itself, so MSH-2 = "^~\\&",
    MSH-3 = sending app, MSH-4 = sending facility.
    In zero-indexed split: fields[2] = MSH-3, fields[3] = MSH-4.

    Args:
        file_bytes (bytes): The raw TRN file content from S3

    Returns:
        dict: {"MSH3_SendingApplication": ..., "MSH4_SendingFacility": ...}
    """
    # Decode the file (HL7v2 is typically ASCII or UTF-8)
    try:
        text = file_bytes.decode("utf-8", errors="replace")
    except Exception:
        text = file_bytes.decode("latin-1", errors="replace")

    # Find the MSH segment (first line, or first line starting with "MSH")
    msh_line = ""
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("MSH"):
            msh_line = line
            break

    if not msh_line:
        return {
            "MSH3_SendingApplication": "(MSH segment not found)",
            "MSH4_SendingFacility": "(MSH segment not found)",
        }

    # Split by pipe delimiter
    fields = msh_line.split("|")

    # MSH-3 = fields[2], MSH-4 = fields[3] (zero-indexed after split)
    sending_app = fields[2].strip() if len(fields) > 2 else ""
    sending_facility = fields[3].strip() if len(fields) > 3 else ""

    return {
        "MSH3_SendingApplication": sending_app,
        "MSH4_SendingFacility": sending_facility,
    }


# ============================================================================
# HELPER: Flush to Disk
# ============================================================================

def _flush_results_to_csv(results, already_processed):
    """Write batch of results to output CSV (append or create)."""
    if not results:
        return
    file_exists = os.path.exists(OUTPUT_CSV) and os.path.getsize(OUTPUT_CSV) > 0
    if file_exists:
        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writerows(results)
    else:
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(results)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "=" * 75)
    print("findandsaveEHRfromTRN.py -- TRN HL7v2 MSH Parser")
    print("=" * 75)
    print()
    print("CONFIGURATION:")
    print(f"  Active Profile:   {ACTIVE_PROFILE}")
    print(f"  AWS CLI Profile:  {AWS_PROFILE}")
    if DEFAULT_BUCKET:
        print(f"  Default Bucket:   {DEFAULT_BUCKET}")
    else:
        print(f"  S3 Buckets:       Read from input CSV ({len(ALLOWED_BUCKETS)} allowed)")
    print(f"  Input CSV:        {os.path.basename(INPUT_CSV)}")
    print(f"  Output CSV:       {os.path.basename(OUTPUT_CSV)}")
    print(f"  Max files:        {MAX_FILES if MAX_FILES else 'ALL'}")
    print(f"  Parse mode:       HL7v2 MSH segment (MSH-3, MSH-4)")
    print()
    print("=" * 75)
    print()

    # STEP 1: Read input CSV
    print("STEP 1: Reading input CSV...")
    try:
        input_rows = read_input_csv_file(
            INPUT_CSV,
            default_bucket=DEFAULT_BUCKET,
            allowed_buckets=ALLOWED_BUCKETS,
            max_files=None,
        )
        print(f"  [OK] Found {len(input_rows)} total TRN documents in input CSV")
    except Exception as e:
        print(f"  [ERROR] {e}")
        return
    if not input_rows:
        print("  No files found. Exiting.")
        return
    print()

    # STEP 2: Check restart state
    print("STEP 2: Checking for previously processed files...")
    already_processed = load_already_processed_paths(OUTPUT_CSV)
    initial_processed_count = len(already_processed)

    if already_processed:
        remaining_rows = [
            r for r in input_rows if r["path"] not in already_processed
        ]
        skipped = len(input_rows) - len(remaining_rows)
        print(f"  [OK] Found {len(already_processed)} already done, skipping {skipped}")
        print(f"       {len(remaining_rows)} remaining")
        input_rows = remaining_rows
    else:
        print("  [OK] Starting fresh")

    # Apply max_files AFTER filtering
    if MAX_FILES and len(input_rows) > MAX_FILES:
        print(f"       Limiting this run to {MAX_FILES} files")
        input_rows = input_rows[:MAX_FILES]

    if not input_rows:
        print("\n  All files already processed! Nothing to do.")
        print(f"  Output: {OUTPUT_CSV}")
        return
    print()

    # STEP 3: Connect to S3
    print("STEP 3: Connecting to S3...")
    try:
        s3_client = create_s3_client(AWS_PROFILE)
        print("  [OK] Connected")
    except Exception as e:
        print(f"  [ERROR] {e}")
        return
    print()

    # STEP 4: Process TRN files
    print("STEP 4: Processing TRN files...")
    print()

    results = []
    run_start_time = time.time()

    for file_index, input_row in enumerate(input_rows, 1):
        bucket = input_row["bucket"]
        s3_key = input_row["key"]
        s3_path = input_row["path"]
        file_name = os.path.basename(s3_key)
        file_start_time = time.time()

        print(f"  [{file_index:3d}/{len(input_rows):3d}] {file_name[:60]}")

        # --- Download file from S3 ---
        try:
            response = s3_client.get_object(Bucket=bucket, Key=s3_key)
            file_bytes = response["Body"].read()
            file_size = len(file_bytes)
        except Exception as e:
            print(f"               [ERROR] Download: {e}")
            error_row = {field: "(download error)" for field in OUTPUT_FIELDS}
            error_row["Path"] = s3_path
            error_row["FileName"] = file_name
            results.append(error_row)
            continue

        # --- Extract MSH-3 and MSH-4 ---
        try:
            signals = extract_trn_signals(file_bytes)
        except Exception as e:
            print(f"               [ERROR] Parse: {e}")
            error_row = {field: "(parse error)" for field in OUTPUT_FIELDS}
            error_row["Path"] = s3_path
            error_row["FileName"] = file_name
            results.append(error_row)
            continue

        # --- Build result row ---
        row = {
            "Path": s3_path,
            "FileName": file_name,
            "QE": input_row["qe"],
            "Input_Assigning_Authority": input_row["assigning_authority"],
            "ProcessingTimeMS": int((time.time() - file_start_time) * 1000),
            "FileSizeBytes": file_size,
            "MSH3_SendingApplication": signals["MSH3_SendingApplication"],
            "MSH4_SendingFacility": signals["MSH4_SendingFacility"],
            "Parse_type": PARSE_TYPE,
            "Data_Type": "TRN",
        }

        print(f"               MSH-3 (App):      {row['MSH3_SendingApplication'][:50]}")
        print(f"               MSH-4 (Facility): {row['MSH4_SendingFacility'][:50]}")
        print(f"               >> Time: {row['ProcessingTimeMS']} ms")
        print()

        results.append(row)

        # --- Flush every 200 records ---
        if len(results) % FLUSH_EVERY_N_RECORDS == 0:
            _flush_results_to_csv(results, already_processed)
            already_processed.update(r["Path"] for r in results)
            results.clear()
            print(f"  [FLUSH] Saved progress ({file_index} files complete)")
            print()

    # STEP 5: Write remaining
    print()
    print("STEP 5: Writing remaining results...")
    _flush_results_to_csv(results, already_processed)
    print(f"  [OK] Wrote final {len(results)} rows")

    # Summary
    total_elapsed_ms = int((time.time() - run_start_time) * 1000)
    total_processed = len(input_rows)
    avg_ms = total_elapsed_ms // total_processed if total_processed else 0
    final_csv_count = len(load_already_processed_paths(OUTPUT_CSV))

    print()
    print("=" * 75)
    print("DONE!")
    print("=" * 75)
    print()
    print("DEBUG SUMMARY:")
    print(f"  Previously processed:    {initial_processed_count}")
    print(f"  Processed this run:      {total_processed}")
    print(f"  Total in output CSV:     {final_csv_count}")
    print()
    print(f"  Total time this run:     {total_elapsed_ms:,} ms ({total_elapsed_ms / 1000:.1f} sec)")
    print(f"  Avg time per record:     {avg_ms} ms")
    print()
    print(f"Output: {OUTPUT_CSV}")
    print()


if __name__ == "__main__":
    main()
