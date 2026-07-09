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
import xml.etree.ElementTree as ET
import csv
import io
import os
import re
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
    "output_csv": "ehr_software_names_DEV.csv",
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
    "output_csv": "ehr_software_names_PROD.csv",
    "max_files": None,                                             # None = process all documents
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
    "Path",                           # S3 directory path
    "FileName",                       # Just the filename
    
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
    
    # Signal 4: Section sequence
    "sectionOrder",                   # Ordered list with titles and LOINC codes
    
    # Signal 5: OID analysis
    "hasEpicOID",                     # YES/NO — contains 1.2.840.114350?
    "epicOIDsFound",                  # List of actual Epic OIDs (if any)
    "allOIDFamilies",                 # Unique OID family prefixes in document
    
    # Signal 6: XML formatting
    "indentStyle",                    # 2-space, 4-space, tabs, mixed, etc.
    
    # Preliminary classification (optional)
    "EHR-Guess",                      # EPIC, NOT-EPIC, or NOT SURE
    "EHR-GuessReason",                # Why we made that guess
]


# ============================================================================
# EPIC REFERENCE PATTERNS
# ============================================================================

# Epic's standard section ordering (LOINC codes)
# These appear in almost every Epic-generated CCD
EPIC_SECTION_LOINC_ORDER = [
    "48765-2",  # Allergies / Adverse Reactions
    "10160-0",  # Medications / Current Medications
    "11450-4",  # Problems / Problem List
    "30954-2",  # Results / Diagnostic Results / Laboratory
    "8716-3",   # Vital Signs
    "47519-4",  # Procedures
]

# Epic's assigned OID family (registered with IANA)
EPIC_OID_FAMILY = "1.2.840.114350"

# XML namespace used in all CDA documents
CDA_NAMESPACE = "urn:hl7-org:v3"


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
# HELPER: CCD XML Parsing (Main Signal Extraction)
# ============================================================================

def extract_all_fingerprint_signals(xml_bytes):
    """
    Parse a CCD XML document and extract all 7 fingerprint signals.
    
    This is the core of the analysis. We pull out every structural marker
    that might indicate which EHR system created this CCD.
    
    Args:
        xml_bytes (bytes): The raw CCD XML file (as bytes from S3)
    
    Returns:
        dict: A dictionary with these keys:
            - Assigning-Authority: The source system ID
            - OID: Patient ID root OID
            - softwareName: From assignedAuthoringDevice
            - manufacturerModelName: Backup software ID
            - custodianOrgName: Organization name
            - templateIds: Pipe-separated list of template OIDs
            - sectionOrder: Arrow-separated section titles with LOINC codes
            - hasEpicOID: "YES" or "NO"
            - epicOIDsFound: Pipe-separated list of Epic OIDs (if any)
            - allOIDFamilies: Pipe-separated unique OID family prefixes
            - indentStyle: "2-space", "4-space", "tabs", "mixed", or "none"
    
    Raises:
        Exception: If the XML is malformed or cannot be parsed
    """
    
    # Convert bytes to string (we need this for indentation analysis)
    raw_xml_text = xml_bytes.decode("utf-8", errors="replace")
    
    # Parse the XML into a tree
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()

    # CDA namespace (all CDA elements live in this namespace)
    ns = CDA_NAMESPACE

    # =========================================================================
    # SIGNAL 1: Software Name
    # =========================================================================
    # Location: //assignedAuthoringDevice/softwareName
    # This is often the most direct indicator. If the document says
    # "Epic - Version 2023" or similar, we're done. But some vendors
    # sanitize this field (Synthea sets it to their GitHub URL, etc.).
    
    software_name_element = root.find(
        f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}softwareName"
    )
    software_name = (
        software_name_element.text.strip()
        if (software_name_element is not None and software_name_element.text)
        else ""
    )

    # =========================================================================
    # SIGNAL 2: Manufacturer Model Name
    # =========================================================================
    # Location: //assignedAuthoringDevice/manufacturerModelName
    # Backup field; sometimes contains vendor branding when softwareName
    # is generic.
    
    manufacturer_element = root.find(
        f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}manufacturerModelName"
    )
    manufacturer_model = (
        manufacturer_element.text.strip()
        if (manufacturer_element is not None and manufacturer_element.text)
        else ""
    )

    # =========================================================================
    # SIGNAL 3: Custodian Organization Name
    # =========================================================================
    # Location: //custodian/assignedCustodian/representedCustodianOrganization/name
    # This is the organization responsible for the document. Less vendor-specific
    # than software name, but useful for context.
    
    custodian_element = root.find(
        f".//{{{ns}}}custodian/{{{ns}}}assignedCustodian/{{{ns}}}representedCustodianOrganization/{{{ns}}}name"
    )
    custodian_org = (
        custodian_element.text.strip()
        if (custodian_element is not None and custodian_element.text)
        else ""
    )

    # =========================================================================
    # SIGNAL 4: Template IDs (Document-Level)
    # =========================================================================
    # Location: //ClinicalDocument/templateId elements
    # These OIDs declare which CDA standards/profiles the document conforms to.
    # Epic uses specific OID combinations; other vendors have different patterns.
    # (Note: templateId can have both @root and @extension attributes.)
    
    template_ids = []
    for template_element in root.findall(f"{{{ns}}}templateId"):
        oid = template_element.get("root", "")
        extension = template_element.get("extension", "")
        
        # Format as "OID:extension" if there's an extension, else just "OID"
        if extension:
            template_ids.append(f"{oid}:{extension}")
        else:
            template_ids.append(oid)

    # =========================================================================
    # SIGNAL 5: Section Order (with LOINC Codes)
    # =========================================================================
    # Location: //component/structuredBody/component/section (or alternate paths)
    # The order of sections is very distinctive. Epic almost always follows:
    #   Allergies(48765-2) → Medications(10160-0) → Problems(11450-4) →
    #   Results(30954-2) → Vital Signs(8716-3) → Procedures(47519-4)
    # Other vendors have different orderings.
    
    # Try the standard CDA path first
    sections = root.findall(
        f".//{{{ns}}}component/{{{ns}}}structuredBody/{{{ns}}}component/{{{ns}}}section"
    )
    
    # If that didn't work, try an alternate path (some CCDs nest differently)
    if not sections:
        sections = root.findall(f".//{{{ns}}}component/{{{ns}}}section")

    section_order = []
    for section in sections:
        # Get the section title (human-readable name, e.g., "Allergies")
        title_element = section.find(f"{{{ns}}}title")
        title = (
            title_element.text.strip()
            if (title_element is not None and title_element.text)
            else ""
        )

        # Get the LOINC code (machine-readable section type, e.g., "48765-2")
        code_element = section.find(f"{{{ns}}}code")
        loinc_code = code_element.get("code", "") if code_element is not None else ""

        # Format as "Title(LOINC)" for easy reading and parsing
        if loinc_code:
            section_order.append(f"{title}({loinc_code})")
        else:
            section_order.append(title)

    # =========================================================================
    # SIGNAL 6: OID Families
    # =========================================================================
    # Location: Every element's @root attribute (patient IDs, encounter IDs, etc.)
    # Epic is assigned OID family 1.2.840.114350. If we see OIDs from this
    # family, it's a strong signal the document came from an Epic system.
    # Other vendors use different OID roots.
    
    all_oids = set()
    
    # Iterate through every element in the XML
    for element in root.iter():
        root_oid = element.get("root", "")
        
        # Only collect dotted OIDs (e.g., "1.2.840.114350.x.x")
        # Skip UUIDs (which look like "123abc-456def-789...")
        if root_oid and re.match(r"^\d+\.\d+", root_oid):
            all_oids.add(root_oid)

    # Check specifically for Epic's OID family
    epic_oids_found = [o for o in all_oids if o.startswith(EPIC_OID_FAMILY)]
    has_epic_oid = "YES" if epic_oids_found else "NO"

    # Extract OID family prefixes (first 3 segments)
    # E.g., "1.2.840.114350.1.13.297" → "1.2.840"
    # This helps us see the variety of OID roots in use
    oid_families = set()
    for oid in all_oids:
        parts = oid.split(".")
        if len(parts) >= 3:
            oid_families.add(".".join(parts[:3]))

    # =========================================================================
    # SIGNAL 7: XML Formatting Style
    # =========================================================================
    # Indentation pattern can be a minor fingerprint. Epic's serializers
    # typically use consistent 2-space indentation.
    
    indent_style = detect_xml_indentation_style(raw_xml_text)

    # =========================================================================
    # METADATA: Assigning Authority and Patient OID
    # =========================================================================
    # These aren't fingerprints, but they're critical for grouping and
    # understanding the source of the document.
    # Location: //recordTarget/patientRole/id
    
    patient_id_elements = root.findall(
        f".//{{{ns}}}recordTarget/{{{ns}}}patientRole/{{{ns}}}id"
    )
    assigning_authority = ""
    patient_oid = ""

    # Prefer non-Synthea (non-test) assigning authorities
    for patient_id_element in patient_id_elements:
        aa = patient_id_element.get("assigningAuthorityName", "")
        oid = patient_id_element.get("root", "")
        
        if aa and "synthea" not in aa.lower():
            assigning_authority = aa
            patient_oid = oid
            break
    else:
        # If all are Synthea (test data), just take the first one
        if patient_id_elements:
            first = patient_id_elements[0]
            assigning_authority = first.get("assigningAuthorityName", "")
            patient_oid = first.get("root", "")

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
        "sectionOrder": " -> ".join(section_order),
        "hasEpicOID": has_epic_oid,
        "epicOIDsFound": " | ".join(sorted(epic_oids_found)[:10]),  # First 10 only
        "allOIDFamilies": " | ".join(sorted(oid_families)[:20]),     # First 20 only
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
    # SIGNAL CHECK 3: Section Order
    # =========================================================================
    # Extract LOINC codes from the section order string.
    # Epic's order is so distinctive that matching the first 4 sections
    # (Allergies → Meds → Problems → Results) is strong evidence.
    
    section_order_str = fingerprints.get("sectionOrder", "")
    
    # Find all LOINC codes in the format "Title(LOINC)" using regex
    # Regex explanation: \( = literal "(", (\d+-\d+) = capture digits-digits, \) = literal ")"
    loinc_codes = re.findall(r"\((\d+-\d+)\)", section_order_str)
    
    if len(loinc_codes) >= 4:
        # Get Epic's expected first 4 LOINC codes
        epic_first_4 = EPIC_SECTION_LOINC_ORDER[:4]
        
        # Check if this document's first 4 match Epic's pattern exactly
        if loinc_codes[:4] == epic_first_4:
            score += 0.15
            reasons.append("section order matches Epic pattern (first 4)")
        # Weaker signal: just the first 2 match
        elif loinc_codes[:2] == epic_first_4[:2]:
            score += 0.05
            reasons.append("partial section order match (first 2 sections)")

    # =========================================================================
    # SIGNAL CHECK 4: Standard CCD TemplateID
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
    # SIGNAL CHECK 5: XML Formatting
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
    # STEP 2: Connect to S3
    # =========================================================================
    
    print("STEP 2: Connecting to S3...")
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
    # STEP 3: Process each CCD
    # =========================================================================
    
    print("STEP 3: Processing documents...")
    print()

    results = []

    for file_index, s3_key in enumerate(xml_keys, 1):
        file_name = os.path.basename(s3_key)
        file_dir = os.path.dirname(s3_key)
        
        print(f"  [{file_index:3d}/{len(xml_keys):3d}] {file_name}")

        # --- Download from S3 ---
        try:
            response = s3_client.get_object(Bucket=BUCKET, Key=s3_key)
            xml_bytes = response["Body"].read()
            print(f"               Downloaded {len(xml_bytes):,} bytes")
        except Exception as download_error:
            print(f"               [ERROR] Downloading: {download_error}")
            
            # Still write an error row to the output CSV
            error_row = {field: "(download error)" for field in OUTPUT_FIELDS}
            error_row["Path"] = f"s3://{BUCKET}/{file_dir}/"
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
            error_row["Path"] = f"s3://{BUCKET}/{file_dir}/"
            error_row["FileName"] = file_name
            results.append(error_row)
            continue

        # --- Add file path info ---
        fingerprints["Path"] = f"s3://{BUCKET}/{file_dir}/"
        fingerprints["FileName"] = file_name

        # --- Print key signals (for manual review during execution) ---
        print(f"               softwareName: {fingerprints.get('softwareName', '(blank)')[:50]}")
        print(f"               hasEpicOID:   {fingerprints.get('hasEpicOID', '')}")

        # --- Make a preliminary guess ---
        ehr_guess, guess_reason = make_preliminary_ehr_guess(fingerprints)
        fingerprints["EHR-Guess"] = ehr_guess
        fingerprints["EHR-GuessReason"] = guess_reason
        
        print(f"               >> EHR Guess:  {ehr_guess} ({guess_reason[:60]}...)")
        print()

        results.append(fingerprints)

    # =========================================================================
    # STEP 4: Write output CSV
    # =========================================================================
    
    print()
    print("STEP 4: Writing results to output CSV...")
    print(f"  File: {OUTPUT_CSV}")
    
    try:
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"  [OK] Successfully wrote {len(results)} rows")
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
    print(f"Processed {len(results)} CCD documents")
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
