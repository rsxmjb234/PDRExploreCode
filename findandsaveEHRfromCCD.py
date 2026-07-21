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
1. Sample 100 CCDs per Assigning Authority from a single recent day
2. Extract 7 structural signals from each CCD (see SIGNALS below)
3. Write all raw signals to a CSV for downstream analysis
4. Optionally make a preliminary EHR guess (EPIC / NOT-EPIC / NOT SURE)

Note: We do NOT classify in this script. We extract facts. Classification
logic can then be reviewed and adjusted by domain experts or in Excel.


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

5. Section Order (LOINC codes)
   Where: Sequence of component/section elements in document body
   What:  The order in which sections appear (Allergies → Medications → Problems…)
   Why:   Epic follows a very predictable, distinctive section sequence

6. OID Families
   Where: Every id/@root attribute (patient IDs, encounter IDs, entry IDs, etc.)
   What:  The OID prefixes used throughout the document
   Why:   Epic is assigned OID family 1.2.840.114350; other vendors use different roots

7. Formatting Style
   Where: Whitespace, indentation, attribute ordering in the XML
   What:  Indentation pattern (2-space, 4-space, tabs, etc.)
   Why:   Epic's serializers produce consistent formatting; useful secondary signal


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
  - Contains all 7 signals plus filename, path, assigning authority
  - Optionally includes a preliminary EHR guess


================================================================================
CONFIGURATION — Edit these parameters before running
================================================================================
"""

import boto3
import csv
import os
import re
import time
from collections import Counter


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
    "max_files": 50,  # Quick test run; change to None to process all
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
    # File location info
    "Path",                           # Full S3 path (s3://bucket/key) - so you know what's done
    "FileName",                       # Just the filename (for quick scanning)
    
    # Performance tracking (POC diagnostics)
    "ProcessingTimeMS",               # Time to download + extract this file (milliseconds)
    
    # Source identification
    "Assigning-Authority",            # Who sent this document (source system ID)
    "OID",                            # Patient ID root OID
    
    # Signal 1: Software markers
    "softwareName",                   # From assignedAuthoringDevice
    "manufacturerModelName",          # Backup software identifier
    
    # Signal 2: Organization info
    "custodianOrgName",               # Organization hosting/sending the CCD
    
    # Signal 3: Template IDs
    "templateIds",                    # All document-level template OIDs
    
    # Signal 4: OID analysis
    "hasEpicOID",                     # YES/NO — contains 1.2.840.114350?
    "epicOIDsFound",                  # List of actual Epic OIDs (if any)
    "allOIDFamilies",                 # Unique OID family prefixes in document
    
    # Signal 5: XML formatting
    "indentStyle",                    # 2-space, 4-space, tabs, mixed, etc.
    
    # Preliminary classification (optional)
    "EHR-Guess",                      # EPIC, NOT-EPIC, or NOT SURE
    "EHR-GuessReason",                # Why we made that guess
]


# ============================================================================
# EPIC REFERENCE PATTERNS
# ============================================================================

# Epic's assigned OID family (registered with IANA)
EPIC_OID_FAMILY = "1.2.840.114350"

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
    Read the input CSV and extract a list of S3 object keys to process.
    
    The CSV must have at least a "key" column containing S3 paths.
    We filter to only .xml files (CCDs are XML documents).
    
    Args:
        csv_path (str): Path to the input CSV file
        max_files (int or None): Stop after processing this many files.
                                  None = process all rows
    
    Returns:
        list of str: S3 object keys (e.g., ["RawCCDs/doc1.xml", "RawCCDs/doc2.xml"])
    
    Example:
        >>> keys = read_input_csv_file("DEV-upto2000documentsfromdevbucket.csv", max_files=50)
        >>> print(f"Found {len(keys)} documents to process")
    """
    keys = []
    with open(csv_path, "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            # Extract the S3 key from the "key" column
            key = row["key"].strip()
            
            # Only process XML files (skip .pdf, .txt, etc.)
            if key.lower().endswith(".xml"):
                keys.append(key)
                
                # Stop if we've reached the limit (useful for testing)
                if max_files and len(keys) >= max_files:
                    break
    
    return keys


# ============================================================================
# HELPER: XML Formatting Analysis
# ============================================================================

def detect_xml_indentation_style(raw_xml_text):
    """
    Analyze the XML file's indentation pattern.
    
    By examining the leading whitespace of the first ~200 lines, we can
    infer whether the XML was serialized with 2-space, 4-space, tab, or
    mixed indentation. This is a minor fingerprint: Epic's serializers
    typically produce consistent 2-space indentation.
    
    Args:
        raw_xml_text (str): The raw XML as a string
    
    Returns:
        str: One of "2-space", "4-space", "tabs", "mixed", or "none"
    
    Example:
        >>> style = detect_xml_indentation_style(my_xml_string)
        >>> print(f"This XML uses {style} indentation")
    """
    lines = raw_xml_text.split("\n")[:200]  # Look at first 200 lines
    indent_counts = Counter()

    for line in lines:
        # Remove leading whitespace to measure how much was there
        stripped = line.lstrip()
        
        # Skip empty lines, XML declarations, and comments
        if not stripped or stripped.startswith("<?") or stripped.startswith("<!"):
            continue

        # Calculate how much leading whitespace we removed
        leading_whitespace = line[:len(line) - len(stripped)]
        if not leading_whitespace:
            continue

        # Categorize the indentation
        if "\t" in leading_whitespace:
            indent_counts["tabs"] += 1
        else:
            # Count spaces
            num_spaces = len(leading_whitespace)
            
            # If it's even and ≤20, likely 2-space indentation
            if num_spaces % 2 == 0 and num_spaces <= 20:
                indent_counts["2-space"] += 1
            # If it's divisible by 4, likely 4-space indentation
            elif num_spaces % 4 == 0:
                indent_counts["4-space"] += 1
            # Otherwise, it's irregular
            else:
                indent_counts["other"] += 1

    # If we found no indentation, return "none"
    if not indent_counts:
        return "none"

    # Find the most common indentation style
    most_common_style, count = indent_counts.most_common(1)[0]
    total_indented_lines = sum(indent_counts.values())

    # If the most common style appears in ≥70% of lines, call it that
    # Otherwise, call it "mixed"
    if total_indented_lines > 0 and count / total_indented_lines >= 0.7:
        return most_common_style
    else:
        return "mixed"


# ============================================================================
# HELPER: CCD Header Extraction (Regex-Based, for Partial Downloads)
# ============================================================================

def extract_all_fingerprint_signals(partial_xml_bytes):
    """
    Extract fingerprint signals from the FIRST 100KB of a CCD document.
    
    IMPORTANT: This function uses REGEX (not XML parsing) because we only
    download a partial file. A standard XML parser would fail on incomplete XML.
    
    This works because all our signals live in the CDA header (first ~50KB):
      - softwareName, manufacturerModelName (in assignedAuthoringDevice)
      - custodianOrgName (in custodian section)
      - templateIds (at document root, very near the top)
      - OIDs with @root attributes (patient IDs, author IDs in header)
      - Indentation style (first 200 lines)
    
    Args:
        partial_xml_bytes (bytes): The first 100KB of the CCD XML file
    
    Returns:
        dict: Extracted fingerprint signals (see OUTPUT_FIELDS for keys)
    """
    
    # Convert bytes to string for regex matching
    raw_text = partial_xml_bytes.decode("utf-8", errors="replace")

    # =========================================================================
    # SIGNAL 1: Software Name
    # =========================================================================
    # Look for: <softwareName>Epic - Version 2023</softwareName>
    # Regex: find content between softwareName tags
    
    software_name = ""
    match = re.search(r"<[^>]*softwareName[^>]*>([^<]+)</", raw_text)
    if match:
        software_name = match.group(1).strip()

    # =========================================================================
    # SIGNAL 2: Manufacturer Model Name
    # =========================================================================
    # Look for: <manufacturerModelName>EpicCare Ambulatory</manufacturerModelName>
    
    manufacturer_model = ""
    match = re.search(r"<[^>]*manufacturerModelName[^>]*>([^<]+)</", raw_text)
    if match:
        manufacturer_model = match.group(1).strip()

    # =========================================================================
    # SIGNAL 3: Custodian Organization Name
    # =========================================================================
    # Look for: <name>Strong Memorial Hospital</name> inside the custodian block
    # We look for representedCustodianOrganization...name pattern
    
    custodian_org = ""
    # Find the custodian block, then grab the <name> inside it
    custodian_block = re.search(
        r"<[^>]*custodian[^>]*>(.*?)</[^>]*custodian",
        raw_text, re.DOTALL
    )
    if custodian_block:
        name_match = re.search(r"<[^>]*name[^>]*>([^<]+)</", custodian_block.group(1))
        if name_match:
            custodian_org = name_match.group(1).strip()

    # =========================================================================
    # SIGNAL 4: Template IDs (Document-Level)
    # =========================================================================
    # Look for: <templateId root="2.16.840.1.113883.10.20.22.1.2" extension="2015-08-01"/>
    # These appear near the top of the document
    
    template_ids = []
    for match in re.finditer(r'<[^>]*templateId[^>]*root="([^"]*)"([^>]*)', raw_text):
        oid = match.group(1)
        # Check for extension attribute
        ext_match = re.search(r'extension="([^"]*)"', match.group(2))
        extension = ext_match.group(1) if ext_match else ""
        
        if extension:
            template_ids.append(f"{oid}:{extension}")
        else:
            template_ids.append(oid)

    # =========================================================================
    # SIGNAL 5: OID Families (from all root="" attributes in the header)
    # =========================================================================
    # Scan all root="..." attributes in the partial content
    # Epic's family: 1.2.840.114350
    
    all_oids = set()
    for match in re.finditer(r'root="([^"]*)"', raw_text):
        oid_value = match.group(1)
        # Only collect dotted OIDs (skip UUIDs like "abc123-def456-...")
        if re.match(r"^\d+\.\d+", oid_value):
            all_oids.add(oid_value)

    # Check specifically for Epic's OID family
    epic_oids_found = [o for o in all_oids if o.startswith(EPIC_OID_FAMILY)]
    has_epic_oid = "YES" if epic_oids_found else "NO"

    # Extract OID family prefixes (first 3 segments)
    oid_families = set()
    for oid in all_oids:
        parts = oid.split(".")
        if len(parts) >= 3:
            oid_families.add(".".join(parts[:3]))

    # =========================================================================
    # SIGNAL 6: XML Formatting Style
    # =========================================================================
    # Analyze indentation of the first 200 lines
    
    indent_style = detect_xml_indentation_style(raw_text)

    # =========================================================================
    # METADATA: Assigning Authority and Patient OID
    # =========================================================================
    # Look for: <id root="..." assigningAuthorityName="..." /> in recordTarget
    
    assigning_authority = ""
    patient_oid = ""
    
    # Find all id elements with assigningAuthorityName
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
    
    # Try alternate attribute order (root before assigningAuthorityName)
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
    
    # If we still didn't find one, take whatever is first
    if not assigning_authority:
        match = re.search(r'assigningAuthorityName="([^"]*)"', raw_text)
        if match:
            assigning_authority = match.group(1).strip()
        match = re.search(r'<[^>]*id[^>]*root="(\d+\.\d+[^"]*)"', raw_text)
        if match:
            patient_oid = match.group(1).strip()

    # =========================================================================
    # RETURN ALL SIGNALS
    # =========================================================================
    
    return {
        "Assigning-Authority": assigning_authority,
        "OID": patient_oid,
        "softwareName": software_name,
        "manufacturerModelName": manufacturer_model,
        "custodianOrgName": custodian_org,
        "templateIds": " | ".join(template_ids),
        "hasEpicOID": has_epic_oid,
        "epicOIDsFound": " | ".join(sorted(epic_oids_found)[:10]),
        "allOIDFamilies": " | ".join(sorted(oid_families)[:20]),
        "indentStyle": indent_style,
    }


# ============================================================================
# HELPER: EHR Classification (Preliminary Guess)
# ============================================================================

def make_preliminary_ehr_guess(fingerprints):
    """
    Use a simple weighted scoring system to make an educated guess at which
    EHR system created this CCD.
    
    This is NOT a definitive classification. It's a preliminary guess based
    on readily-available signals. The actual classification should be done
    by domain experts reviewing the raw CSV output.
    
    Scoring approach:
      - Each signal contributes points toward EPIC or away from it
      - Accumulate the score across all signals
      - If score >= 0.35: guess "EPIC"
      - If score <= -0.10: guess "NOT-EPIC"
      - Otherwise: guess "NOT SURE"
    
    Args:
        fingerprints (dict): Output from extract_all_fingerprint_signals()
    
    Returns:
        tuple: (guess, reason_string)
            - guess: "EPIC", "NOT-EPIC", or "NOT SURE"
            - reason_string: Semicolon-separated list of signals that contributed
    """
    
    score = 0.0
    reasons = []

    # =========================================================================
    # SIGNAL CHECK 1: Software Name
    # =========================================================================
    # If the CCD explicitly says "Epic" or "EpicCare", that's strong evidence.
    # If it says "Cerner", "MEDITECH", etc., that's strong evidence it's NOT Epic.
    
    software_combined = (
        (fingerprints.get("softwareName", "") + " " +
         fingerprints.get("manufacturerModelName", "")).lower()
    )
    
    if "epic" in software_combined:
        score += 0.35
        reasons.append("softwareName contains 'Epic'")
    elif "cerner" in software_combined or "millennium" in software_combined:
        score -= 0.35
        reasons.append("softwareName contains 'Cerner/Millennium'")
    elif "meditech" in software_combined:
        score -= 0.35
        reasons.append("softwareName contains 'MEDITECH'")
    elif "allscripts" in software_combined:
        score -= 0.35
        reasons.append("softwareName contains 'Allscripts'")
    elif "eclinicalworks" in software_combined or "ecw" in software_combined:
        score -= 0.35
        reasons.append("softwareName contains 'eClinicalWorks'")

    # =========================================================================
    # SIGNAL CHECK 2: Epic OID Family
    # =========================================================================
    # If the document contains OIDs from Epic's registered family (1.2.840.114350),
    # that's strong evidence it came from an Epic system.
    
    if fingerprints.get("hasEpicOID") == "YES":
        score += 0.30
        reasons.append("has Epic OID (1.2.840.114350)")

    # =========================================================================
    # SIGNAL CHECK 3: Standard CCD TemplateID
    # =========================================================================
    # The standard CCD template (2.16.840.1.113883.10.20.22.1.2) is expected
    # in almost all CCDs, so it's not distinctive on its own. But if we
    # already have other Epic signals, its presence adds slight confidence.
    
    template_str = fingerprints.get("templateIds", "").lower()
    
    if "2.16.840.1.113883.10.20.22.1.2" in template_str:
        # Only count this if we already have other signals
        if score > 0.2:
            score += 0.05
            reasons.append("standard CCD templateId with other Epic signals")

    # =========================================================================
    # SIGNAL CHECK 4: XML Formatting
    # =========================================================================
    # Epic's serializers typically use consistent 2-space indentation.
    # This is a weak signal on its own, but supporting evidence if we
    # already have Epic signals.
    
    indent_style = fingerprints.get("indentStyle", "")
    
    if indent_style == "2-space" and score > 0.1:
        score += 0.05
        reasons.append("2-space indentation (consistent with Epic)")

    # =========================================================================
    # MAKE THE FINAL CALL
    # =========================================================================
    
    if score >= 0.35:
        guess = "EPIC"
    elif score <= -0.10:
        guess = "NOT-EPIC"
    elif score == 0.0 and not reasons:
        guess = "NOT SURE"
        reasons.append("no strong signals detected")
    else:
        guess = "NOT SURE"
        if not reasons:
            reasons.append("weak or mixed signals")

    reason_text = "; ".join(reasons) if reasons else "no signals"
    return guess, reason_text


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
        xml_keys = read_input_csv_file(INPUT_CSV, max_files=MAX_FILES)
        print(f"  [OK] Found {len(xml_keys)} CCD documents to process")
    except Exception as e:
        print(f"  [ERROR] Reading CSV: {e}")
        return
    
    print()

    # Check if we found any documents
    if not xml_keys:
        print("ERROR: No XML files found in the input CSV. Stopping.")
        print()
        print("Troubleshooting:")
        print("  - Check that INPUT_CSV points to the correct file")
        print("  - Confirm the CSV has a 'key' column with S3 paths")
        print("  - Ensure the paths end with .xml")
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
        remaining_keys = [
            key for key in xml_keys
            if f"s3://{BUCKET}/{key}" not in already_processed
        ]
        
        skipped_count = len(xml_keys) - len(remaining_keys)
        print(f"       Skipping {skipped_count} already-processed files")
        print(f"       {len(remaining_keys)} files remaining to process")
        
        xml_keys = remaining_keys
    else:
        print("  [OK] No existing output found -- starting fresh")
    
    print()

    # Check if there's anything left to do
    if not xml_keys:
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

    for file_index, s3_key in enumerate(xml_keys, 1):
        file_name = os.path.basename(s3_key)
        file_dir = os.path.dirname(s3_key)
        
        # Start timing this file
        file_start_time = time.time()
        
        print(f"  [{file_index:3d}/{len(xml_keys):3d}] {file_name}")

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

        # --- Print key signals (for manual review during execution) ---
        print(f"               softwareName: {fingerprints.get('softwareName', '(blank)')[:50]}")
        print(f"               hasEpicOID:   {fingerprints.get('hasEpicOID', '')}")

        # --- Make a preliminary guess ---
        ehr_guess, guess_reason = make_preliminary_ehr_guess(fingerprints)
        fingerprints["EHR-Guess"] = ehr_guess
        fingerprints["EHR-GuessReason"] = guess_reason
        
        # --- Record processing time ---
        file_elapsed_ms = int((time.time() - file_start_time) * 1000)
        fingerprints["ProcessingTimeMS"] = file_elapsed_ms
        
        print(f"               >> EHR Guess:  {ehr_guess} ({guess_reason[:60]}...)")
        print(f"               >> Time: {file_elapsed_ms} ms")
        print()

        results.append(fingerprints)

        # --- Flush to disk every 200 records (crash protection) ---
        # This ensures we never lose more than 200 records of work if the
        # script crashes, gets interrupted, or loses network connectivity.
        if len(results) % 200 == 0:
            _flush_results_to_csv(results, already_processed)
            already_processed.update(f"s3://{BUCKET}/{k}" for k in xml_keys[:file_index])
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
    total_processed_this_run = len(xml_keys)
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
    print("     - Look for common softwareName, templateId, or section order values")
    print("     - Check if hasEpicOID is consistent across documents from same AA")
    print("  3. Validate the preliminary EHR guesses against known source systems")
    print("  4. Adjust the scoring logic in make_preliminary_ehr_guess() if needed")
    print()


if __name__ == "__main__":
    main()
