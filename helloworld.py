"""
helloworld.py — "Hello World" for PDR S3 Access

PURPOSE:
    Connectivity test for AWS CLI and PDR S3 bucket read access.
    
    This script confirms that:
      1. Your AWS CLI is set up correctly.
      2. Your account can read from the S3 bucket.
      3. You can download and parse a CCD document.
    
    As a hello world test, it downloads a single CCD, extracts:
      - Patient's last name
      - Software name (often indicates "Epic")
      - Epic OID family (1.2.840.114350 = Epic signature)
      - Section order (should follow Allergies → Meds → Problems pattern for Epic)

HOW TO USE:
    1. Choose a profile: set ACTIVE_PROFILE to "DEV" or "PROD"
    2. Run: python helloworld.py
    3. If you see a patient name and Epic detection results, your access works.

PROFILES:
    DEV  — Uses the learning bucket (nyec.ccda.learning) with a known
           Synthea test file. Always works if your AWS CLI is configured.

    PROD — Dan: this is yours. Fill in your AWS CLI profile, bucket, and a
           known PROD (or QA) CCD path below. Once this runs, your PROD
           access is confirmed.
"""

import boto3
import xml.etree.ElementTree as ET
import csv
import io
import os
import re


# =============================================================================
# CHOOSE YOUR PROFILE — set to "DEV" or "PROD"
# =============================================================================

ACTIVE_PROFILE = "DEV"

# =============================================================================
# DEV PROFILE — known good, uses the learning bucket
# =============================================================================
# Use this for initial testing and development.

DEV = {
    "aws_profile": "student1",
    "bucket": "nyec.ccda.learning",
    "csv_file": "DEV-upto2000documentsfromdevbucket.csv",
    # Optionally, override with a hardcoded key (if CSV reading fails):
    "fallback_key": "RawCCDs/Aaron697_Schiller186_d5d96071-fdff-d902-f487-de1a278fd864.xml",
}

# =============================================================================
# PROD PROFILE — Dan: fill these in for your environment
# =============================================================================
# Dan: change these values to match your environment.
#   - aws_profile: your AWS CLI profile name
#   - bucket: your PDR bucket (or QA bucket)
#   - csv_file: your Athena export CSV filename
#   - fallback_key: a known CCD file path (for testing if CSV read fails)

PROD = {
    "aws_profile": "dan-prod",                                      # Dan: your CLI profile
    "bucket": "nyec-pdr-prod-hixny",                               # Dan: your bucket
    "csv_file": "PROD-upto100documentsfromeveryAAForASingleDay.csv", # Dan: Athena export
    "fallback_key": "1003861782/ccd/2026/Jul/06/15/hixny_1003861782_59041906c701c0a83ac4ca3781382549a9569358a4bddab470f413fef9fb56a7_2.16.840.1.113883.3.227.3245.1.1.c1be4578.xml",
}

# =============================================================================
# End of configuration
# =============================================================================


# =============================================================================
# HELPER: Read CSV file
# =============================================================================

def read_first_ccd_path_from_csv(csv_filename):
    """
    Read the input CSV and extract the S3 path from the first line.
    
    This confirms that we can:
      1. Find and read the CSV file
      2. Parse CSV format
      3. Extract the 'key' column (S3 object path)
    
    Args:
        csv_filename (str): Just the filename (we'll build the full path)
    
    Returns:
        tuple: (success: bool, path: str, message: str)
            - success: True if we found and read the first line
            - path: The S3 object key from the first data row (not header)
            - message: Status message explaining what happened
    """
    
    # Build the full path to the CSV
    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        csv_filename
    )
    
    # Check if the file exists
    if not os.path.exists(csv_path):
        return False, None, f"CSV file not found: {csv_path}"
    
    try:
        with open(csv_path, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Get the first data row (after header)
            first_row = next(reader, None)
            
            if first_row is None:
                return False, None, "CSV file is empty (no data rows)"
            
            # Extract the 'key' column
            if "key" not in first_row:
                return False, None, "CSV missing 'key' column"
            
            key = first_row["key"].strip()
            
            if not key:
                return False, None, "First row has empty 'key' value"
            
            return True, key, f"Successfully read first line from CSV"
    
    except Exception as e:
        return False, None, f"Error reading CSV: {e}"


def extract_epic_signals(root, xml_bytes):
    """
    Extract Epic source detection signals from the CCD.
    
    Analyzes:
      1. Software name — does it say "Epic"?
      2. Epic OID family — does it have 1.2.840.114350?
      3. Section order — does it match Epic's typical pattern?
    
    Returns a dictionary with findings.
    """
    ns = "urn:hl7-org:v3"
    signals = {}
    
    # --------- Signal 1: Software Name ---------
    # Epic CCDs almost always have "Epic" or "EpicCare" in the software name.
    software_name_el = root.find(
        f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}softwareName"
    )
    software_name = (
        software_name_el.text.strip()
        if (software_name_el is not None and software_name_el.text)
        else "(not found)"
    )
    signals["softwareName"] = software_name
    signals["has_Epic_in_name"] = "Epic" in software_name or "epic" in software_name.lower()
    
    # --------- Signal 2: Epic OID Family ---------
    # Epic uses OIDs starting with 1.2.840.114350 (their registered family).
    # Scan all OID root attributes in the document.
    all_oids = set()
    for element in root.iter():
        root_oid = element.get("root", "")
        # Only collect dotted OIDs (not UUIDs).
        if root_oid and re.match(r"^\d+\.\d+", root_oid):
            all_oids.add(root_oid)
    
    epic_oids = [o for o in all_oids if o.startswith("1.2.840.114350")]
    signals["epicOIDsFound"] = epic_oids[:5]  # Show first 5
    signals["has_Epic_OID"] = len(epic_oids) > 0
    
    # --------- Signal 3: Section Order ---------
    # Epic almost always orders sections: Allergies → Medications → Problems → Results → Vitals
    sections = root.findall(
        f".//{{{ns}}}component/{{{ns}}}structuredBody/{{{ns}}}component/{{{ns}}}section"
    )
    if not sections:
        sections = root.findall(f".//{{{ns}}}component/{{{ns}}}section")
    
    section_titles = []
    section_loincs = []
    for section in sections:
        title_el = section.find(f"{{{ns}}}title")
        code_el = section.find(f"{{{ns}}}code")
        
        title = title_el.text.strip() if (title_el is not None and title_el.text) else ""
        loinc = code_el.get("code", "") if code_el is not None else ""
        
        if title:
            section_titles.append(title)
        if loinc:
            section_loincs.append(loinc)
    
    signals["sectionTitles"] = section_titles
    signals["sectionLOINCcodes"] = section_loincs
    
    # Epic's typical order (LOINC codes):
    # 48765-2 = Allergies
    # 10160-0 = Medications
    # 11450-4 = Problems
    # 30954-2 = Results
    # 8716-3 = Vital Signs
    epic_order = ["48765-2", "10160-0", "11450-4", "30954-2", "8716-3"]
    first_5_loincs = section_loincs[:5]
    matches_epic_order = first_5_loincs == epic_order[:len(first_5_loincs)]
    signals["matches_Epic_section_order"] = matches_epic_order
    
    return signals


def main():
    """Main workflow: read CSV, connect to S3, download CCD, extract Epic signals."""
    
    # Select the active config
    if ACTIVE_PROFILE.upper() == "PROD":
        config = PROD
    else:
        config = DEV

    aws_profile = config["aws_profile"]
    bucket = config["bucket"]
    csv_filename = config["csv_file"]
    fallback_key = config["fallback_key"]

    print("=" * 75)
    print("PDR Hello World - S3 Connectivity & Epic Detection Test")
    print("=" * 75)
    print(f"  Active profile:   {ACTIVE_PROFILE}")
    print(f"  AWS CLI profile:  {aws_profile}")
    print(f"  Bucket:           {bucket}")
    print(f"  CSV file:         {csv_filename}")
    print()

    # --------- Step 1: Read CSV to get first CCD path ---------
    print("Step 1: Reading CSV file to extract first CCD path...")
    csv_success, s3_key, csv_message = read_first_ccd_path_from_csv(csv_filename)
    
    if csv_success:
        print(f"  [OK] {csv_message}")
        print(f"       First CCD path: {s3_key[:70]}...")
    else:
        print(f"  [WARNING] {csv_message}")
        print(f"  [INFO] Falling back to hardcoded key for this test")
        s3_key = fallback_key

    print()

    # --------- Step 2: Connect to S3 ---------
    print("Step 2: Connecting to S3...")
    try:
        session = boto3.Session(profile_name=aws_profile)
        s3 = session.client("s3")
        print("  [OK] Connected to S3")
    except Exception as e:
        print(f"  [ERROR] Failed to connect: {e}")
        return

    # --------- Step 3: Download CCD ---------
    print("\nStep 3: Downloading CCD file...")
    try:
        response = s3.get_object(Bucket=bucket, Key=s3_key)
        xml_bytes = response["Body"].read()
        print(f"  [OK] Downloaded {len(xml_bytes):,} bytes")
    except Exception as e:
        print(f"  [ERROR] Failed to download: {e}")
        return

    # --------- Step 4: Parse XML ---------
    print("\nStep 4: Parsing XML and extracting data...")
    try:
        tree = ET.parse(io.BytesIO(xml_bytes))
        root = tree.getroot()
        print("  [OK] XML parsed successfully")
    except Exception as e:
        print(f"  [ERROR] Failed to parse XML: {e}")
        return

    # --------- Extract patient name ---------
    ns = "urn:hl7-org:v3"
    family_el = root.find(
        f".//{{{ns}}}recordTarget/{{{ns}}}patientRole/{{{ns}}}patient/{{{ns}}}name/{{{ns}}}family"
    )
    last_name = (
        family_el.text.strip() if (family_el is not None and family_el.text)
        else "(not found)"
    )

    # --------- Extract Epic signals ---------
    signals = extract_epic_signals(root, xml_bytes)

    # --------- Display Results ---------
    print()
    print("=" * 75)
    print("RESULTS")
    print("=" * 75)
    print()
    print(f"Patient Last Name:                {last_name}")
    print()
    print("Epic Source Detection Signals:")
    print(f"  . Software Name:                {signals['softwareName']}")
    print(f"    >> Contains 'Epic'?           {signals['has_Epic_in_name']}")
    print()
    print(f"  . Epic OID Family (1.2.840.114350):")
    if signals['has_Epic_OID']:
        print(f"    >> Found: {len(signals['epicOIDsFound'])} Epic OIDs")
        for oid in signals['epicOIDsFound']:
            print(f"       {oid}")
    else:
        print(f"    >> Not found")
    print()
    print(f"  . Section Order (LOINC codes):")
    print(f"    >> Sections: {' | '.join(signals['sectionTitles'][:5])}")
    print(f"    >> LOINC:    {' | '.join(signals['sectionLOINCcodes'][:5])}")
    print(f"    >> Matches Epic pattern?      {signals['matches_Epic_section_order']}")
    print()
    
    # --------- Summary ---------
    epic_signals_found = sum([
        signals['has_Epic_in_name'],
        signals['has_Epic_OID'],
        signals['matches_Epic_section_order']
    ])
    print(f"Epic Signals Found: {epic_signals_found}/3")
    print()
    if epic_signals_found >= 2:
        print("  >> This CCD appears to be from an EPIC system")
    elif epic_signals_found == 1:
        print("  >> Weak Epic signals; might be EPIC or another system")
    else:
        print("  >> This CCD does not show typical Epic markers")
    
    print()
    print("=" * 75)
    print("SUCCESS! Your S3 access is working and CCD parsing is functional.")
    print("=" * 75)


if __name__ == "__main__":
    main()
