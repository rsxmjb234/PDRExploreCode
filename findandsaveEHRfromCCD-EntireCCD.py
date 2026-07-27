"""
findandsaveEHRfromCCD-EntireCCD.py — Classify Data Sources by EHR Vendor
                                     (FULL FILE DOWNLOAD + XML PARSER)

================================================================================
GOAL
================================================================================
Determine which EHR system (Epic, Cerner, MEDITECH, Synthea, etc.) is behind
each data source (Assigning Authority) by analyzing structural fingerprints
within CCD (Continuity of Care Document) files.

This is the FULL FILE version. It downloads the entire CCD and uses a proper
XML parser (ElementTree) to extract signals.


================================================================================
STRATEGY
================================================================================
1. Read a list of CCD S3 paths from an input CSV (with bucket per row)
2. Download the ENTIRE CCD from S3 (full file, could be 1-10MB+)
3. Parse the XML with ElementTree and extract softwareName + manufacturerModelName
4. Classify the EHR vendor using pattern matching on those fields
5. Write results to an output CSV


================================================================================
RESILIENCY / RESTART CAPABILITY
================================================================================
This script is designed to run over long periods (hours) against large datasets
(100K+ documents). It WILL crash at some point -- network timeouts, S3 throttling,
or simply being interrupted. So we built in restart protection:

HOW IT WORKS:
  1. At startup, we read the output CSV and load all "Path" values into memory
     as a set of already-processed files.
  2. We skip any file in the input list that's already in that set.
  3. Every 200 records, we flush results to disk (append to CSV).
  4. If the script crashes, you lose at most ~200 records of work.
  5. On the next run, it picks up where it left off automatically.
  6. max_files is applied AFTER filtering, so each run processes the NEXT
     batch, not the first batch.

TO RE-PROCESS EVERYTHING FROM SCRATCH:
  Delete the output CSV file (or rename it) and run again.


================================================================================
SIGNALS WE EXTRACT
================================================================================

1. Software Name
   Where: assignedAuthoringDevice/softwareName
   What:  Often directly states the vendor (e.g., "Epic", "MEDENT", "Synthea")

2. Manufacturer Model Name
   Where: assignedAuthoringDevice/manufacturerModelName
   What:  Backup to software name; may contain vendor branding

3. Custodian Organization Name
   Where: custodian/.../representedCustodianOrganization/name
   What:  The organization hosting/sending the CCD (context, not used in guess)


================================================================================
EHR CLASSIFICATION LOGIC
================================================================================
We match softwareName + manufacturerModelName against known vendor patterns:
  Synthea, Epic, eClinicalWorks, athenahealth, MEDENT, Cerner, PointClickCare,
  Netsmart, Practice Fusion, NextGen, Greenway, SigmaCare, Office Practicum,
  MEDITECH, InterSystems

If no pattern matches => "UNKNOWN" with Low confidence.


================================================================================
INPUT / OUTPUT
================================================================================

INPUT CSV (from findcandidatesforexplore.sql or DEV-makelistofdevdocsfollowingprodcsvformat.py):
  Required columns: "bucket", "key"
  Optional columns: "qe", "assigning_authority"
  PROD: Each row specifies its own bucket (multi-bucket support)
  DEV: Can use a default_bucket if CSV omits bucket column

OUTPUT CSV:
  One row per document with: Path, FileName, QE, Input_Assigning_Authority,
  ProcessingTimeMS, FileSizeBytes, Assigning-Authority-ParsedFromS3, OID,
  softwareName, manufacturerModelName, custodianOrgName,
  EHR_Guess, EHR_Guess_Confidence, EHR_Guess_Reason, Parse_type


================================================================================
CONFIGURATION -- Edit the DEV/PROD profiles below before running
================================================================================
"""

import boto3
import xml.etree.ElementTree as ET
import csv
import io
import os
import re
import time


# ============================================================================
# CHOOSE YOUR PROFILE -- set to "DEV" or "PROD"
# ============================================================================

ACTIVE_PROFILE = "DEV"

# ============================================================================
# DEV PROFILE -- known good, uses the learning bucket
# ============================================================================

DEV = {
    "aws_profile": "student1",
    "default_bucket": "nyec.ccda.learning",
    "allowed_buckets": ["nyec.ccda.learning"],
    "input_csv": "DEV-CandidateS3PathsForEvaluation.csv",
    "output_csv": "DEV-EHR_Software_Names_EntireCCD.csv",
    "max_files": 2000,
}

# ============================================================================
# PROD PROFILE -- Multi-bucket, reads bucket from each CSV row
# ============================================================================
# Each PROD CSV row must identify its actual S3 bucket (from Athena export).
# Both primary and -part2 buckets are accepted for the six production QEs.

PROD = {
    "aws_profile": "default",
    "default_bucket": None,   # PROD rows must specify their bucket in the CSV
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
    "input_csv": "Export-Athena-10-ccds-per-source.csv",
    "output_csv": "PROD-EHR_Software_Names_EntireCCD.csv",
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

INPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), INPUT_CSV_FILENAME)
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_CSV_FILENAME)


# ============================================================================
# COLUMN DEFINITIONS
# ============================================================================

OUTPUT_FIELDS = [
    "Path",                           # Full S3 path (s3://bucket/key)
    "FileName",                       # Just the filename
    "QE",                             # QE from input CSV
    "Input_Assigning_Authority",      # Assigning authority from input CSV
    "ProcessingTimeMS",               # Time to download + extract (milliseconds)
    "FileSizeBytes",                  # Full file size (shows what we're downloading)
    "Assigning-Authority-ParsedFromS3", # Assigning Authority derived from the S3 path
    "OID",                            # Patient ID root OID
    "softwareName",                   # From assignedAuthoringDevice
    "manufacturerModelName",          # Backup software identifier
    "custodianOrgName",               # Organization hosting/sending the CCD
    "EHR_Guess",                      # Canonical EHR vendor name
    "EHR_Guess_Confidence",           # High / Medium / Low
    "EHR_Guess_Reason",               # Which fields drove the guess
    "Parse_type",                     # "Entire" or "TopOnly" -- for comparison runs
]

# Constant value for the Parse_type column in this version of the script
PARSE_TYPE = "Entire"


# ============================================================================
# CONSTANTS
# ============================================================================

CDA_NAMESPACE = "urn:hl7-org:v3"
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
    Read bucket/key locations from the input CSV for XML documents.
    
    PROD Athena exports must include separate "bucket" and "key" columns.
    DEV input may omit "bucket" and use the configured default bucket.
    A complete s3://bucket/key value in the key column is also accepted.
    
    Returns:
        list of dict: Each item has bucket, key, path, qe, assigning_authority.
    """
    documents = []
    allowed_buckets = set(allowed_buckets or [])

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        if not reader.fieldnames:
            raise ValueError("Input CSV has no header row")

        # Tolerate casing differences in column headers
        header_map = {name.strip().lower(): name for name in reader.fieldnames}
        key_column = header_map.get("key")
        bucket_column = header_map.get("bucket")
        qe_column = header_map.get("qe")
        aa_column = header_map.get("assigning_authority")

        if not key_column:
            raise ValueError('Input CSV must contain a "key" column')
        if not bucket_column and not default_bucket:
            raise ValueError(
                'PROD input CSV must contain a "bucket" column. '
                'Add i.bucket to the Athena SELECT.'
            )

        for row_number, row in enumerate(reader, start=2):
            raw_key = (row.get(key_column) or "").strip()
            bucket = (row.get(bucket_column) or "").strip() if bucket_column else ""
            qe = (row.get(qe_column) or "").strip() if qe_column else ""
            aa = (row.get(aa_column) or "").strip() if aa_column else ""

            if not raw_key:
                continue

            # Accept complete S3 URIs in the key column
            if raw_key.lower().startswith("s3://"):
                s3_location = raw_key[5:]
                parsed_bucket, separator, parsed_key = s3_location.partition("/")
                if not separator or not parsed_key:
                    raise ValueError(f"Invalid S3 URI on CSV row {row_number}: {raw_key}")
                bucket = bucket or parsed_bucket
                key = parsed_key
            else:
                key = raw_key

            bucket = bucket or default_bucket
            if not bucket:
                raise ValueError(f"Missing bucket on CSV row {row_number} for key: {key}")

            if allowed_buckets and bucket not in allowed_buckets:
                raise ValueError(
                    f"Unexpected bucket on CSV row {row_number}: {bucket}. "
                    f"Allowed: {', '.join(sorted(allowed_buckets))}"
                )

            if not key.lower().endswith(".xml"):
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
# CORE: Extract Fingerprints Using Full XML Parsing
# ============================================================================

def extract_all_fingerprint_signals(xml_bytes):
    """
    Parse the ENTIRE CCD XML document and extract fingerprint signals using
    proper XPath queries via ElementTree.
    
    Args:
        xml_bytes (bytes): The FULL CCD XML file as bytes from S3
    
    Returns:
        dict: Extracted fingerprint signals
    """
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()
    ns = CDA_NAMESPACE

    # SIGNAL 1: Software Name
    el = root.find(f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}softwareName")
    software_name = el.text.strip() if (el is not None and el.text) else ""

    # SIGNAL 2: Manufacturer Model Name
    el = root.find(f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}manufacturerModelName")
    manufacturer_model = el.text.strip() if (el is not None and el.text) else ""

    # SIGNAL 3: Custodian Organization Name
    el = root.find(
        f".//{{{ns}}}custodian/{{{ns}}}assignedCustodian"
        f"/{{{ns}}}representedCustodianOrganization/{{{ns}}}name"
    )
    custodian_org = el.text.strip() if (el is not None and el.text) else ""

    # SIGNAL 4: Custodian — already extracted above, no OID scanning needed

    # METADATA: Assigning Authority and Patient OID
    patient_id_elements = root.findall(
        f".//{{{ns}}}recordTarget/{{{ns}}}patientRole/{{{ns}}}id"
    )
    assigning_authority = ""
    patient_oid = ""

    for pid in patient_id_elements:
        aa = pid.get("assigningAuthorityName", "")
        oid = pid.get("root", "")
        if aa and "synthea" not in aa.lower():
            assigning_authority = aa
            patient_oid = oid
            break
    else:
        if patient_id_elements:
            first = patient_id_elements[0]
            assigning_authority = first.get("assigningAuthorityName", "")
            patient_oid = first.get("root", "")

    return {
        "Assigning-Authority-ParsedFromS3": assigning_authority,
        "OID": patient_oid,
        "softwareName": software_name,
        "manufacturerModelName": manufacturer_model,
        "custodianOrgName": custodian_org,
    }


# ============================================================================
# HELPER: EHR Classification (Smart Vendor Detection)
# ============================================================================

def classify_ehr_vendor(fingerprints):
    """
    Determine the EHR vendor using explicit name matching and OID signals.
    
    Returns: (ehr_guess, confidence, reason)
    """
    sw = fingerprints.get("softwareName", "").strip()
    mfr = fingerprints.get("manufacturerModelName", "").strip()
    
    sw_lower = sw.lower()
    mfr_lower = mfr.lower()
    combined = f"{sw_lower} {mfr_lower}"
    
    # --- Rule 2: Explicit EHR product/vendor signals ---
    vendor_patterns = [
        ("synthea", "Synthea"),
        ("epic", "EPIC"),
        ("eclinicalworks", "eClinicalWorks"),
        ("athenahealth", "athenahealth"),
        ("medent", "MEDENT"),
        ("cerner", "Cerner"),
        ("millennium", "Cerner"),
        ("pointclickcare", "PointClickCare"),
        ("netsmart", "Netsmart"),
        ("practice fusion", "Practice Fusion"),
        ("nextgen", "NextGen"),
        ("greenway", "Greenway"),
        ("intergy", "Greenway"),
        ("sigmacare", "SigmaCare"),
        ("office practicum", "Office Practicum"),
        ("meditech", "MEDITECH"),
        ("intersystems", "InterSystems"),
        ("healthshare", "InterSystems"),
    ]
    
    for pattern, vendor in vendor_patterns:
        if pattern in combined:
            return (vendor, "High", f"softwareName='{sw}' / manufacturer='{mfr}'")
    
    # --- Rule 3: Generic software name + specific manufacturer ---
    if "document generation engine" in sw_lower and "athenahealth" in mfr_lower:
        return ("athenahealth", "High", f"generic sw + manufacturer='{mfr}'")
    if "ccd generator" in sw_lower and "netsmart" in mfr_lower:
        return ("Netsmart", "High", f"generic sw + manufacturer='{mfr}'")
    if "millennium" in sw_lower and "cerner" in mfr_lower:
        return ("Cerner", "High", f"generic sw + manufacturer='{mfr}'")
    
    # --- Rule 5: Unknown ---
    return ("UNKNOWN", "Low", "no reliable signal in softwareName or OIDs")


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
    print("findandsaveEHRfromCCD-EntireCCD.py -- FULL FILE XML PARSER")
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
    print(f"  Download mode:    FULL FILE (entire CCD)")
    print(f"  Parse mode:       XML ElementTree (XPath)")
    print()
    print("=" * 75)
    print()

    # STEP 1: Read input CSV
    print("STEP 1: Reading input CSV...")
    try:
        # Read ALL rows (no limit) — we apply max_files AFTER filtering
        input_rows = read_input_csv_file(
            INPUT_CSV,
            default_bucket=DEFAULT_BUCKET,
            allowed_buckets=ALLOWED_BUCKETS,
            max_files=None,
        )
        print(f"  [OK] Found {len(input_rows)} total documents in input CSV")
    except Exception as e:
        print(f"  [ERROR] {e}")
        return
    if not input_rows:
        print("  No XML files found. Exiting.")
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

    # Apply max_files AFTER filtering — gives us the next batch, not the first batch
    if MAX_FILES and len(input_rows) > MAX_FILES:
        print(f"       Limiting this run to {MAX_FILES} files (max_files setting)")
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

    # STEP 4: Process documents
    print("STEP 4: Processing documents (FULL FILE download)...")
    print()

    results = []
    run_start_time = time.time()

    for file_index, input_row in enumerate(input_rows, 1):
        bucket = input_row["bucket"]
        s3_key = input_row["key"]
        s3_path = input_row["path"]
        file_name = os.path.basename(s3_key)
        file_start_time = time.time()

        print(f"  [{file_index:3d}/{len(input_rows):3d}] {file_name}")
        print(f"               Bucket: {bucket}")

        # --- Download ENTIRE file from S3 ---
        try:
            response = s3_client.get_object(Bucket=bucket, Key=s3_key)
            xml_bytes = response["Body"].read()
            file_size = len(xml_bytes)
            print(f"               Downloaded {file_size:,} bytes (full file)")
        except Exception as e:
            print(f"               [ERROR] Download: {e}")
            error_row = {field: "(download error)" for field in OUTPUT_FIELDS}
            error_row["Path"] = s3_path
            error_row["FileName"] = file_name
            results.append(error_row)
            continue

        # --- Parse XML and extract signals ---
        try:
            fingerprints = extract_all_fingerprint_signals(xml_bytes)
        except Exception as e:
            print(f"               [ERROR] XML parse: {e}")
            error_row = {field: "(XML parse error)" for field in OUTPUT_FIELDS}
            error_row["Path"] = s3_path
            error_row["FileName"] = file_name
            results.append(error_row)
            continue

        # --- Add metadata ---
        fingerprints["Path"] = s3_path
        fingerprints["FileName"] = file_name
        fingerprints["QE"] = input_row["qe"]
        fingerprints["Input_Assigning_Authority"] = input_row["assigning_authority"]
        fingerprints["FileSizeBytes"] = file_size
        fingerprints["Parse_type"] = PARSE_TYPE

        # --- Print key signals ---
        print(f"               softwareName: {fingerprints.get('softwareName', '(blank)')[:50]}")

        # --- Classify EHR vendor ---
        ehr_guess, confidence, reason = classify_ehr_vendor(fingerprints)
        fingerprints["EHR_Guess"] = ehr_guess
        fingerprints["EHR_Guess_Confidence"] = confidence
        fingerprints["EHR_Guess_Reason"] = reason

        # --- Record timing ---
        file_elapsed_ms = int((time.time() - file_start_time) * 1000)
        fingerprints["ProcessingTimeMS"] = file_elapsed_ms

        print(f"               >> EHR Guess:  {ehr_guess} [{confidence}] ({reason[:55]}...)")
        print(f"               >> Time: {file_elapsed_ms} ms")
        print()

        results.append(fingerprints)

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
    print(f"  Download mode:           FULL FILE")
    print(f"  Parse mode:              XML ElementTree")
    print()
    print(f"Output: {OUTPUT_CSV}")
    print()


if __name__ == "__main__":
    main()
