"""
findandsaveEHRfromCCD.py — Classify Data Sources by EHR Vendor

================================================================================
GOAL
================================================================================
Determine which EHR system (Epic, Cerner, MEDITECH, etc.) is behind each data
source (Assigning Authority) by analyzing structural fingerprints within CCD
(Continuity of Care Document) files.

The fingerprints are created by the EHR software itself during document
generation, not by the clinical content. So if a source runs Epic, virtually
every CCD it produces will carry the same structural markers.


================================================================================
STRATEGY
================================================================================
1. Read a list of CCD S3 paths from an input CSV
2. Download the first 100KB of each CCD (header only — see OPTIMIZATION below)
3. Extract structural signals using regex on the partial content
4. Write all raw signals to an output CSV for downstream analysis
5. Optionally make a preliminary EHR guess (EPIC / NOT-EPIC / NOT SURE)

Note: We extract facts. Classification logic can then be reviewed and adjusted
by domain experts in Excel or a separate script.


================================================================================
RESILIENCY / RESTART CAPABILITY
================================================================================
This script is designed to run over long periods (hours) against large datasets
(100K+ documents). It WILL crash at some point — network timeouts, S3 throttling,
or simply being interrupted. So we built in restart protection:

HOW IT WORKS:
  1. At startup, we read the  CSV containing results of evaluation 
     and load all "Path" values into memory
     as a set of already-processed files.
  
  2.  Now load in the CSV containing a list of candidate files.
    This CSV has the list of CSV's you want to look at for this user story.

  3. We skip any file in the input list that's already in that set.
  3. Every 200 records, we write the results of the evaluation of the candidates
     to disk by appending to CSV.
  4. If the script crashes, you lose at most ~200 records of work.
  5. On the next run, it picks up where it left off automatically.
  6.  this is important for all future scripts.

PERFORMANCE NOTE, on loading all 'done' S3 paths into memmory.:
  Loading 100K paths into a Python set uses ~12MB of RAM and takes ~1-2 seconds.
  The set lookup is O(1) per file. This scales without issue.

TO RE-PROCESS EVERYTHING FROM SCRATCH:
  Delete the output CSV file (or rename it) and run again.

TO RE-PROCESS SPECIFIC FILES:
  Delete those rows from the output CSV and run again.


================================================================================
SIGNALS WE EXTRACT (from businessidea-rules.html)
================================================================================

1. Software Name
   Where: assignedAuthoringDevice/softwareName in the CCD
   What:  Often directly states "Epic" or "EpicCare"
   Why:   Most obvious marker if the vendor hasn't sanitized it

2. Manufacturer Model Name
   Where: assignedAuthoringDevice/manufacturerModelName
   What:  Backup to software name; may contain vendor branding
   Why:   Redundancy if software name is blank

3. Custodian Organization Name
   Where: custodian/.../representedCustodianOrganization/name
   What:  The organization hosting/sending the CCD
   Why:   Context, though less vendor-specific than software name

4. Template IDs
   Where: ClinicalDocument/templateId elements (can be multiple)
   What:  OIDs declaring conformance to CDA standards (CCD, CCD-A, referral, etc.)
   Why:   Epic uses specific OID combinations; other vendors have different patterns

5. OID Families
   Where: Every id/@root attribute (patient IDs, encounter IDs, entry IDs, etc.)
   What:  The OID prefixes used throughout the document
   Why:   Epic is assigned OID family 1.2.840.114350; other vendors use different roots

6. Formatting Style
   Where: Whitespace, indentation, attribute ordering in the XML
   What:  Indentation pattern (2-space, 4-space, tabs, etc.)
   Why:   Epic's serializers produce consistent formatting; useful secondary signal


================================================================================
Optomization, for this use case: Partial Download (100KB Header Only)
================================================================================
We download ONLY the first 100KB of each CCD (S3 range request), not the full
multi-MB file. All our signals live in the CDA header. This gives us ~100x less
data transfer per file. See DOWNLOAD_BYTES constant below for details.

If you ever need to look deeper into the document body, increase DOWNLOAD_BYTES
or set it to None for full-file download.


================================================================================
INPUT / OUTPUT
================================================================================

INPUT CSV:
  - Must have at least a "key" column with S3 object paths
  - Typically produced by:
    * makelistofdevdocsfollowingprodcsvformat.py (DEV)
    * Athena query export (PROD)

OUTPUT CSV:
  - One row per input document
  - Contains extracted signals plus filename, full S3 path, assigning authority
  - Includes processing time per record (POC diagnostics)
  - Includes a preliminary EHR guess
  - Full S3 path in each row so you know what's done vs. what's left


================================================================================
CONFIGURATION — Edit the DEV/PROD profiles below before running
================================================================================
"""

import boto3
import csv
import os
import re
import time


# ============================================================================
# CHOOSE YOUR PROFILE — set to "DEV" or "PROD"
# ============================================================================

ACTIVE_PROFILE = "DEV"

# ============================================================================
# DEV PROFILE — known good, uses the learning bucket
# ============================================================================
# Use this for initial testing and development.
# This configuration references the DEV S3 bucket and local test CSVs.

DEV = {
    "aws_profile": "student1",
    "bucket": "nyec.ccda.learning",
    "input_csv": "DEV-upto2000documentsfromdevbucket.csv",
    "output_csv": "DEV-EHR_Software_Names.csv",
    "max_files": 200,  # Quick test run; change to None to process all
}

# ============================================================================
# PROD PROFILE — Dan, fill these in for your environment
# ============================================================================
# Use this when you're ready to run against the production PDR data.
# Dan: change these values to match your environment.

PROD = {
    "aws_profile": "dan-prod",                                      # Dan: your AWS CLI profile
    "bucket": "nyec-pdr-prod-hixny",                               # Dan: your PDR bucket (or QA bucket)
    "input_csv": "PROD-upto20documentsfromeveryAAForASingleDay.csv", # Dan: Athena export CSV
    "output_csv": "PROD-EHR_Software_Names.csv",
    "max_files": 20,                                             # None = process all documents
}

# ============================================================================
# LOAD THE ACTIVE PROFILE
# ============================================================================

if ACTIVE_PROFILE.upper() == "PROD":
    config = PROD
else:
    config = DEV

# Now all configuration comes from the active profile
AWS_PROFILE = config["aws_profile"]
BUCKET = config["bucket"]
INPUT_CSV_FILENAME = config["input_csv"]
OUTPUT_CSV_FILENAME = config["output_csv"]
MAX_FILES = config["max_files"]

# Build full paths for input and output CSVs
INPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    INPUT_CSV_FILENAME
)

OUTPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    OUTPUT_CSV_FILENAME
)


# ============================================================================
# COLUMN DEFINITIONS — What data we export to the output CSV
# ============================================================================

OUTPUT_FIELDS = [
    "Path",                           # Full S3 path (s3://bucket/key)
    "FileName",                       # Just the filename
    "QE",                             # QE from input CSV
    "Input_Assigning_Authority",      # Assigning authority from input CSV
    "ProcessingTimeMS",               # Time to download + extract (milliseconds)
    "FileSizeBytes",                  # File size downloaded (partial = 100KB)
    "Assigning-Authority-ParsedFromS3", # Assigning Authority derived from the S3 path
    "OID",                            # Patient ID root OID
    "softwareName",                   # From assignedAuthoringDevice
    "manufacturerModelName",          # Backup software identifier
    "custodianOrgName",               # Organization hosting/sending the CCD
    "EHR_Guess",                      # Canonical EHR vendor name
    "EHR_Guess_Confidence",           # High / Medium / Low
    "EHR_Guess_Reason",               # Which fields drove the guess
    "Parse_type",                     # "TopOnly" or "Entire" -- for comparison runs
]

# Constant value for the Parse_type column in this version of the script
PARSE_TYPE = "TopOnly"


# ============================================================================
# EPIC REFERENCE PATTERNS
# ============================================================================

# XML namespace used in all CDA documents
CDA_NAMESPACE = "urn:hl7-org:v3"


# ============================================================================
# PERFORMANCE OPTIMIZATION: Partial Download (S3 Range Request)
# ============================================================================
# 
# IMPORTANT NOTE FOR FUTURE DEVELOPERS:
#
# We download ONLY the first 100KB of each CCD file (not the full document).
# This is a deliberate optimization for speed at scale (100K+ documents).
#
# Why this works:
#   All of our strongest signals (softwareName, manufacturerModelName,
#   custodianOrgName, templateIds, patient OIDs, and Epic OIDs) live in the
#   CDA header, which is always within the first 50KB of the document.
#   We use 100KB (2x safety margin) to be sure we capture the full header.
#
# What we gave up:
#   - Section order analysis (removed) — this signal required parsing the
#     full document body. It was a MEDIUM-weight signal (0.15) and not worth
#     downloading multi-MB files for.
#   - OID scanning of deep document entries — we only see OIDs in the first
#     100KB. In practice, Epic's OID family appears in the header IDs, so
#     this is still effective.
#
# If you need to look deeper into the document in the future:
#   - Increase DOWNLOAD_BYTES below (e.g., to 500KB or None for full file)
#   - Re-enable section order extraction
#   - Switch back to full XML parsing (the old code used ET.parse)
#
# Speed gain: ~100x less data transfer per file (100KB vs 5-10MB avg)

DOWNLOAD_BYTES = 102400  # 100KB — covers the full CDA header with 2x margin


# ============================================================================
# HELPER: Restart Support (Skip Already-Processed Files)
# ============================================================================

def load_already_processed_paths(output_csv_path):
    """
    Read the existing output CSV and return a set of S3 paths that have
    already been processed.
    
    This enables restart behavior: if the script crashes or is interrupted,
    you can re-run it and it will skip files that already have results.
    
    Args:
        output_csv_path (str): Path to the output CSV file
    
    Returns:
        set: A set of full S3 paths (e.g., "s3://bucket/key") that are
             already in the output. Returns empty set if file doesn't exist.
    """
    already_done = set()
    
    # If the output CSV doesn't exist yet, nothing has been processed
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
        # If we can't read the file, assume nothing is done
        # (safer to re-process than to skip)
        print(f"  [WARNING] Could not read existing output CSV: {e}")
        print(f"            Will process all files from scratch.")
        return set()
    
    return already_done


# ============================================================================
# HELPER: AWS / S3 Operations
# ============================================================================

def create_s3_client(profile_name):
    """
    Create a boto3 S3 client authenticated with the specified AWS CLI profile.
    
    This connects to S3 using your stored AWS credentials from:
      ~/.aws/credentials or ~/.aws/config
    
    Args:
        profile_name (str): Name of AWS CLI profile (e.g., "student1", "dan-prod")
    
    Returns:
        boto3.client: Ready to call s3.get_object(), s3.list_objects(), etc.
    
    Raises:
        Exception: If profile doesn't exist or credentials are invalid
    
    Example:
        >>> s3 = create_s3_client("student1")
        >>> response = s3.get_object(Bucket="nyec.ccda.learning", Key="RawCCDs/file.xml")
    """
    session = boto3.Session(profile_name=profile_name)
    return session.client("s3")


# ============================================================================
# HELPER: Input Processing
# ============================================================================

def read_input_csv_file(csv_path, max_files=None):
    """
    Read input CSV and return list of dicts with key, qe, and assigning_authority.
    Only includes .xml files.
    """
    rows = []
    with open(csv_path, "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            key = row["key"].strip()
            if key.lower().endswith(".xml"):
                rows.append({
                    "key": key,
                    "qe": row.get("qe", "").strip(),
                    "assigning_authority": row.get("assigning_authority", "").strip(),
                })
                if max_files and len(rows) >= max_files:
                    break
    return rows


# ============================================================================
# HELPER: CCD Header Extraction (Regex-Based, for Partial Downloads)
# ============================================================================

def extract_all_fingerprint_signals(partial_xml_bytes):
    """
    Extract fingerprint signals from the FIRST 100KB of a CCD document.
    Uses REGEX (not XML parsing) because we only download a partial file.
    
    Args:
        partial_xml_bytes (bytes): The first 100KB of the CCD XML file
    
    Returns:
        dict: Extracted fingerprint signals
    """
    raw_text = partial_xml_bytes.decode("utf-8", errors="replace")

    # SIGNAL 1: Software Name
    software_name = ""
    match = re.search(r"<[^>]*softwareName[^>]*>([^<]+)</", raw_text)
    if match:
        software_name = match.group(1).strip()

    # SIGNAL 2: Manufacturer Model Name
    manufacturer_model = ""
    match = re.search(r"<[^>]*manufacturerModelName[^>]*>([^<]+)</", raw_text)
    if match:
        manufacturer_model = match.group(1).strip()

    # SIGNAL 3: Custodian Organization Name
    custodian_org = ""
    custodian_block = re.search(
        r"<[^>]*custodian[^>]*>(.*?)</[^>]*custodian",
        raw_text, re.DOTALL
    )
    if custodian_block:
        name_match = re.search(r"<[^>]*name[^>]*>([^<]+)</", custodian_block.group(1))
        if name_match:
            custodian_org = name_match.group(1).strip()

    # METADATA: Assigning Authority and Patient OID
    assigning_authority = ""
    patient_oid = ""
    
    for match in re.finditer(
        r'<[^>]*id[^>]*assigningAuthorityName="([^"]*)"[^>]*root="([^"]*)"',
        raw_text
    ):
        aa = match.group(1).strip()
        oid = match.group(2).strip()
        if aa and "synthea" not in aa.lower():
            assigning_authority = aa
            patient_oid = oid
            break
    
    if not assigning_authority:
        for match in re.finditer(
            r'<[^>]*id[^>]*root="([^"]*)"[^>]*assigningAuthorityName="([^"]*)"',
            raw_text
        ):
            oid = match.group(1).strip()
            aa = match.group(2).strip()
            if aa and "synthea" not in aa.lower():
                assigning_authority = aa
                patient_oid = oid
                break
    
    if not assigning_authority:
        match = re.search(r'assigningAuthorityName="([^"]*)"', raw_text)
        if match:
            assigning_authority = match.group(1).strip()
        match = re.search(r'<[^>]*id[^>]*root="(\d+\.\d+[^"]*)"', raw_text)
        if match:
            patient_oid = match.group(1).strip()

    return {
        "Assigning-Authority-ParsedFromS3": assigning_authority,
        "OID": patient_oid,
        "softwareName": software_name,
        "manufacturerModelName": manufacturer_model,
        "custodianOrgName": custodian_org,
    }


# ============================================================================
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
# HELPER: Flush Results to Disk (Crash Protection)
# ============================================================================

# How often to flush results to the output CSV (in number of records).
# Lower = safer (less lost work on crash), Higher = less disk I/O.
FLUSH_EVERY_N_RECORDS = 200

def _flush_results_to_csv(results, already_processed):
    """
    Write a batch of results to the output CSV.
    
    If the file doesn't exist yet, creates it with a header row.
    If it already exists, appends without re-writing the header.
    
    Args:
        results (list): List of result dictionaries to write
        already_processed (set): Set of paths already in the CSV (used to
                                  determine if we need a header)
    """
    if not results:
        return
    
    file_exists = os.path.exists(OUTPUT_CSV) and os.path.getsize(OUTPUT_CSV) > 0
    
    if file_exists:
        # Append mode — file already has header
        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writerows(results)
    else:
        # Fresh file — write header first
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(results)


# ============================================================================
# MAIN: Orchestrate the Workflow
# ============================================================================

def main():
    """
    Main workflow: Read input CSV → Download CCDs from S3 → Extract fingerprints
                   → Make preliminary guesses → Write output CSV
    
    This is the top-level orchestration function. It:
      1. Reads the list of S3 documents from the input CSV
      2. Connects to S3 using your AWS CLI profile
      3. For each document:
         - Downloads it from S3 (into memory)
         - Extracts all 7 fingerprint signals
         - Makes a preliminary EHR guess
         - Prints progress to the console
      4. Writes all results to the output CSV
    """
    
    # =========================================================================
    # STARTUP: Print configuration and confirm we're ready
    # =========================================================================
    
    print("\n" + "=" * 75)
    print("findandsaveEHRfromCCD.py — EHR Source Classification")
    print("=" * 75)
    print()
    print("CONFIGURATION:")
    print(f"  Active Profile:   {ACTIVE_PROFILE}")
    print(f"  AWS CLI Profile:  {AWS_PROFILE}")
    print(f"  S3 Bucket:        {BUCKET}")
    print(f"  Input CSV:        {os.path.basename(INPUT_CSV)}")
    print(f"  Output CSV:       {os.path.basename(OUTPUT_CSV)}")
    print(f"  Max files to process: {MAX_FILES if MAX_FILES else 'ALL (process entire input CSV)'}")
    print()
    print("=" * 75)
    print()

    # =========================================================================
    # STEP 1: Read input CSV
    # =========================================================================
    
    print("STEP 1: Reading input CSV file...")
    print(f"  File: {INPUT_CSV}")
    
    try:
        # Read ALL rows (no limit) — we apply max_files AFTER filtering
        input_rows = read_input_csv_file(INPUT_CSV, max_files=None)
        print(f"  [OK] Found {len(input_rows)} total CCD documents in input CSV")
    except Exception as e:
        print(f"  [ERROR] Reading CSV: {e}")
        return
    
    print()

    # Check if we found any documents
    if not input_rows:
        print("ERROR: No XML files found in the input CSV. Stopping.")
        print()
        return

    # =========================================================================
    # STEP 2: Check for already-processed files (restart support)
    # =========================================================================
    
    print("STEP 2: Checking for previously processed files (restart support)...")
    already_processed = load_already_processed_paths(OUTPUT_CSV)
    
    if already_processed:
        print(f"  [OK] Found {len(already_processed)} files already in output CSV")
        
        # Filter out files we've already done
        remaining_rows = [
            r for r in input_rows
            if f"s3://{BUCKET}/{r['key']}" not in already_processed
        ]
        
        skipped_count = len(input_rows) - len(remaining_rows)
        print(f"       Skipping {skipped_count} already-processed files")
        print(f"       {len(remaining_rows)} files remaining to process")
        
        input_rows = remaining_rows
    else:
        print("  [OK] No existing output found -- starting fresh")
    
    # Apply max_files AFTER filtering — this gives us the next batch, not the first batch
    if MAX_FILES and len(input_rows) > MAX_FILES:
        print(f"       Limiting this run to {MAX_FILES} files (max_files setting)")
        input_rows = input_rows[:MAX_FILES]
    
    print()

    # Check if there's anything left to do
    if not input_rows:
        print("All files have already been processed! Nothing to do.")
        print()
        print("DEBUG SUMMARY:")
        print(f"  Previously processed:    {len(already_processed)}")
        print(f"  Processed this run:      0")
        print(f"  Total in output CSV:     {len(already_processed)}")
        print()
        print(f"  Output CSV: {OUTPUT_CSV}")
        print()
        return

    # =========================================================================
    # STEP 3: Connect to S3
    # =========================================================================
    
    print("STEP 3: Connecting to S3...")
    print(f"  AWS Profile: {AWS_PROFILE}")
    print(f"  Bucket:      {BUCKET}")
    
    try:
        s3_client = create_s3_client(AWS_PROFILE)
        print("  [OK] Connected to S3")
    except Exception as e:
        print(f"  [ERROR] Connecting to S3: {e}")
        print()
        print("Troubleshooting:")
        print(f"  - Check that AWS CLI profile '{AWS_PROFILE}' is configured")
        print("  - Run: aws configure list-profiles")
        print("  - Run: aws sts get-caller-identity --profile <profile-name>")
        print()
        return

    print()

    # =========================================================================
    # STEP 4: Process each CCD
    # =========================================================================
    
    print("STEP 4: Processing documents...")
    print()

    results = []
    run_start_time = time.time()
    initial_processed_count = len(already_processed)

    for file_index, input_row in enumerate(input_rows, 1):
        s3_key = input_row["key"]
        file_name = os.path.basename(s3_key)
        
        # Start timing this file
        file_start_time = time.time()
        
        print(f"  [{file_index:3d}/{len(input_rows):3d}] {file_name}")

        # --- Download first 100KB from S3 (range request) ---
        try:
            range_header = f"bytes=0-{DOWNLOAD_BYTES - 1}"
            response = s3_client.get_object(
                Bucket=BUCKET,
                Key=s3_key,
                Range=range_header
            )
            xml_bytes = response["Body"].read()
            print(f"               Downloaded {len(xml_bytes):,} bytes (first 100KB)")
        except Exception as download_error:
            print(f"               [ERROR] Downloading: {download_error}")
            
            # Still write an error row to the output CSV
            error_row = {field: "(download error)" for field in OUTPUT_FIELDS}
            error_row["Path"] = f"s3://{BUCKET}/{s3_key}"
            error_row["FileName"] = file_name
            results.append(error_row)
            continue

        # --- Extract fingerprints from XML ---
        try:
            fingerprints = extract_all_fingerprint_signals(xml_bytes)
        except Exception as parse_error:
            print(f"               [ERROR] Parsing XML: {parse_error}")
            
            # Still write an error row to the output CSV
            error_row = {field: "(XML parse error)" for field in OUTPUT_FIELDS}
            error_row["Path"] = f"s3://{BUCKET}/{s3_key}"
            error_row["FileName"] = file_name
            results.append(error_row)
            continue

        # --- Add file path info ---
        fingerprints["Path"] = f"s3://{BUCKET}/{s3_key}"
        fingerprints["FileName"] = file_name
        fingerprints["QE"] = input_row["qe"]
        fingerprints["Input_Assigning_Authority"] = input_row["assigning_authority"]
        fingerprints["FileSizeBytes"] = len(xml_bytes)
        fingerprints["Parse_type"] = PARSE_TYPE

        # --- Print key signals (for manual review during execution) ---
        print(f"               softwareName: {fingerprints.get('softwareName', '(blank)')[:50]}")

        # --- Classify EHR vendor ---
        ehr_guess, confidence, reason = classify_ehr_vendor(fingerprints)
        fingerprints["EHR_Guess"] = ehr_guess
        fingerprints["EHR_Guess_Confidence"] = confidence
        fingerprints["EHR_Guess_Reason"] = reason
        
        # --- Record processing time ---
        file_elapsed_ms = int((time.time() - file_start_time) * 1000)
        fingerprints["ProcessingTimeMS"] = file_elapsed_ms
        
        print(f"               >> EHR Guess:  {ehr_guess} [{confidence}] ({reason[:55]}...)")
        print(f"               >> Time: {file_elapsed_ms} ms")
        print()

        results.append(fingerprints)

        # --- Flush to disk every 200 records (crash protection) ---
        # This ensures we never lose more than 200 records of work if the
        # script crashes, gets interrupted, or loses network connectivity.
        if len(results) % 200 == 0:
            _flush_results_to_csv(results, already_processed)
            already_processed.update(r["Path"] for r in results)
            results.clear()
            print(f"  [FLUSH] Saved progress to disk ({file_index} files complete)")
            print()

    # =========================================================================
    # STEP 5: Write remaining results to output CSV
    # =========================================================================
    
    print()
    print("STEP 5: Writing remaining results to output CSV...")
    print(f"  File: {OUTPUT_CSV}")
    
    try:
        _flush_results_to_csv(results, already_processed)
        print(f"  [OK] Wrote final {len(results)} rows")
    except Exception as e:
        print(f"  [ERROR] Writing CSV: {e}")
        return

    # =========================================================================
    # CLEANUP: Print summary
    # =========================================================================
    
    print()
    print("=" * 75)
    print("DONE!")
    print("=" * 75)
    print()
    
    total_elapsed_ms = int((time.time() - run_start_time) * 1000)
    total_processed_this_run = len(input_rows)
    avg_ms = total_elapsed_ms // total_processed_this_run if total_processed_this_run else 0
    
    # Count actual rows in CSV for accurate reporting
    final_csv_count = len(load_already_processed_paths(OUTPUT_CSV))
    
    print("DEBUG SUMMARY:")
    print(f"  Previously processed:    {initial_processed_count}")
    print(f"  Processed this run:      {total_processed_this_run}")
    print(f"  Total in output CSV:     {final_csv_count}")
    print()
    print(f"  Total time this run:     {total_elapsed_ms:,} ms ({total_elapsed_ms / 1000:.1f} sec)")
    print(f"  Avg time per record:     {avg_ms} ms")
    print()
    print(f"Output saved to: {OUTPUT_CSV}")
    print()
    print("NEXT STEPS:")
    print("  1. Open the output CSV in Excel or your preferred tool")
    print("  2. Review the extracted signals for patterns:")
    print("     - Look for common softwareName or manufacturerModelName values")
    print("  3. Validate the EHR guesses against known source systems")
    print()


if __name__ == "__main__":
    main()
