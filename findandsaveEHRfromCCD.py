"""
findandsaveEHRfromCCD.py

Goal: Determine the EHR system (e.g. Epic, Cerner, MEDITECH) behind each
Assigning Authority by inspecting structural fingerprints inside CCD documents.

Approach:
  - We sample 1 day of data from each Assigning Authority.
  - We use up to 100 documents per AA to ensure we are not getting a false
    read from a single outlier document. Because EHR fingerprints are produced
    by the software (not the clinical content), consistent signals across
    ~100 docs give high confidence in the classification.

Signals extracted (from businessidea-rules.html):
  1. softwareName — from assignedAuthoringDevice/softwareName
  2. manufacturerModelName — from assignedAuthoringDevice/manufacturerModelName
  3. Custodian org name — from custodian/.../representedCustodianOrganization/name
  4. templateId set — all ClinicalDocument/templateId OIDs
  5. Section order — ordered list of section titles/LOINC codes
  6. OID families — unique root OID prefixes used in id/@root across entries
     (looking for Epic's 1.2.840.114350 family)
  7. Formatting style — indentation pattern (2-space, 4-space, tabs, etc.)

This script does NOT classify — it just extracts raw facts into a CSV.
Classification (EPIC / Not-EPIC / NOT SURE) happens downstream in Excel
or a separate scoring script.

The input CSV must have at least a "key" column with the S3 object key.
This matches the format produced by:
  - makelistofdevdocsfollowingprodcsvformat.py  (DEV)
  - Athena query export                         (PROD)
"""

import boto3
import xml.etree.ElementTree as ET
import csv
import io
import os
import re
from collections import Counter

# =============================================================================
# CONFIGURATION — Change these parameters to switch between DEV and PROD
# =============================================================================

# AWS profile to use for S3 access
AWSLocalCLIProfileName = "student1"

# S3 bucket where the CCDs live
BUCKET = "nyec.ccda.learning"

# Input CSV file — the list of documents to process
# For DEV:  "DEV-upto2000documentsfromdevbucket.csv"
# For PROD: "PROD-upto100documentsfromeveryAAForASingleDay.csv"
INPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "DEV-upto2000documentsfromdevbucket.csv"
)

#INPUT_CSV = os.path.join(
#    os.path.dirname(os.path.abspath(__file__)),
#    "PROD-upto100documentsfromeveryAAForASingleDay.csv"
#)


# Output CSV file — where results get written
OUTPUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ehr_software_names.csv"
)

# Max number of files to process (set to None for all rows in the input CSV)
MAX_FILES = 50000

# =============================================================================
# END CONFIGURATION
# =============================================================================

# Output columns
OUTPUT_FIELDS = [
    "Path",
    "FileName",
    "Assigning-Authority",
    "OID",
    "softwareName",
    "manufacturerModelName",
    "custodianOrgName",
    "templateIds",
    "sectionOrder",
    "hasEpicOID",
    "epicOIDsFound",
    "allOIDFamilies",
    "indentStyle",
    "EHR-Guess",
    "EHR-GuessReason",
]

# Epic's expected section order (first 6 sections)
EPIC_SECTION_ORDER = [
    "48765-2",  # Allergies
    "10160-0",  # Medications
    "11450-4",  # Problems
    "30954-2",  # Results
    "8716-3",   # Vital Signs
    "47519-4",  # Procedures
]


def get_s3_client(profile_name):
    """Create an S3 client using the specified AWS profile."""
    session = boto3.Session(profile_name=profile_name)
    return session.client("s3")


def read_input_csv(input_csv_path, max_files=None):
    """
    Read the input CSV and return a list of S3 keys to process.
    Expects a column named 'key' containing the S3 object key.
    """
    keys = []
    with open(input_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row["key"].strip()
            if key.lower().endswith(".xml"):
                keys.append(key)
                if max_files and len(keys) >= max_files:
                    break
    return keys


def detect_indent_style(raw_xml_text):
    """
    Look at the first ~50 indented lines to determine the indentation style.
    Returns something like: '2-space', '4-space', 'tabs', 'mixed', or 'none'.
    """
    lines = raw_xml_text.split("\n")[:200]
    indent_counts = Counter()
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("<?") or stripped.startswith("<!"):
            continue
        leading = line[:len(line) - len(stripped)]
        if not leading:
            continue
        if "\t" in leading:
            indent_counts["tabs"] += 1
        else:
            spaces = len(leading)
            if spaces % 2 == 0 and spaces <= 20:
                indent_counts["2-space"] += 1
            elif spaces % 4 == 0:
                indent_counts["4-space"] += 1
            else:
                indent_counts["other"] += 1

    if not indent_counts:
        return "none"
    most_common = indent_counts.most_common(1)[0][0]
    if len(indent_counts) > 1:
        # If the dominant style covers >70% of lines, call it that; else mixed
        total = sum(indent_counts.values())
        if indent_counts[most_common] / total >= 0.7:
            return most_common
        return "mixed"
    return most_common


def extract_ccd_metadata(xml_bytes):
    """
    Parse a CCD XML and return a dict of all fingerprint signals.
    """
    raw_text = xml_bytes.decode("utf-8", errors="replace")
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()

    ns = "urn:hl7-org:v3"

    # --- Signal 1: softwareName ---
    software_name_el = root.find(f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}softwareName")
    software_name = software_name_el.text.strip() if (software_name_el is not None and software_name_el.text) else ""

    # --- Signal 2: manufacturerModelName ---
    mfr_el = root.find(f".//{{{ns}}}assignedAuthoringDevice/{{{ns}}}manufacturerModelName")
    manufacturer_model = mfr_el.text.strip() if (mfr_el is not None and mfr_el.text) else ""

    # --- Signal 3: Custodian org name ---
    custodian_el = root.find(
        f".//{{{ns}}}custodian/{{{ns}}}assignedCustodian/{{{ns}}}representedCustodianOrganization/{{{ns}}}name"
    )
    custodian_org = custodian_el.text.strip() if (custodian_el is not None and custodian_el.text) else ""

    # --- Signal 4: templateId set (document-level) ---
    template_ids = []
    for tid in root.findall(f"{{{ns}}}templateId"):
        oid = tid.get("root", "")
        ext = tid.get("extension", "")
        template_ids.append(f"{oid}:{ext}" if ext else oid)

    # --- Signal 5: Section order (titles and LOINC codes) ---
    sections = root.findall(f".//{{{ns}}}component/{{{ns}}}structuredBody/{{{ns}}}component/{{{ns}}}section")
    if not sections:
        # Try alternate path (some CCDs nest differently)
        sections = root.findall(f".//{{{ns}}}component/{{{ns}}}section")
    section_order = []
    for sec in sections:
        title_el = sec.find(f"{{{ns}}}title")
        code_el = sec.find(f"{{{ns}}}code")
        title = title_el.text.strip() if (title_el is not None and title_el.text) else ""
        loinc = code_el.get("code", "") if code_el is not None else ""
        section_order.append(f"{title}({loinc})" if loinc else title)

    # --- Signal 6: OID families ---
    all_oids = set()
    for el in root.iter():
        root_attr = el.get("root", "")
        if root_attr and re.match(r"^\d+\.\d+", root_attr):
            # Only collect dotted OIDs (skip UUIDs)
            all_oids.add(root_attr)

    # Check for Epic OID family
    epic_oids = [o for o in all_oids if o.startswith("1.2.840.114350")]
    has_epic_oid = "YES" if epic_oids else "NO"

    # Summarize OID families (first 3 segments)
    oid_families = set()
    for o in all_oids:
        parts = o.split(".")
        if len(parts) >= 3:
            oid_families.add(".".join(parts[:3]))

    # --- Signal 7: Indentation style ---
    indent_style = detect_indent_style(raw_text)

    # --- Assigning Authority and OID ---
    patient_ids = root.findall(
        f".//{{{ns}}}recordTarget/{{{ns}}}patientRole/{{{ns}}}id"
    )
    assigning_authority = ""
    patient_oid = ""
    for pid in patient_ids:
        aa = pid.get("assigningAuthorityName", "")
        root_oid = pid.get("root", "")
        if aa and "synthea" not in aa.lower():
            assigning_authority = aa
            patient_oid = root_oid
            break
    else:
        if patient_ids:
            first = patient_ids[0]
            assigning_authority = first.get("assigningAuthorityName", "")
            patient_oid = first.get("root", "")

    return {
        "Assigning-Authority": assigning_authority,
        "OID": patient_oid,
        "softwareName": software_name,
        "manufacturerModelName": manufacturer_model,
        "custodianOrgName": custodian_org,
        "templateIds": " | ".join(template_ids),
        "sectionOrder": " -> ".join(section_order),
        "hasEpicOID": has_epic_oid,
        "epicOIDsFound": " | ".join(sorted(epic_oids)[:10]),
        "allOIDFamilies": " | ".join(sorted(oid_families)[:20]),
        "indentStyle": indent_style,
    }


def guess_ehr(metadata):
    """
    Make an educated guess at EPIC / NOT-EPIC / NOT SURE based on the
    extracted signals. Uses a simple weighted scoring approach.

    Returns (guess, reason) tuple.
    """
    score = 0.0
    reasons = []

    # --- Signal 1: softwareName or manufacturerModelName contains "Epic" ---
    sw = (metadata.get("softwareName", "") + " " + metadata.get("manufacturerModelName", "")).lower()
    if "epic" in sw:
        score += 0.35
        reasons.append("softwareName contains 'Epic'")
    elif "cerner" in sw or "millennium" in sw:
        score -= 0.35
        reasons.append("softwareName contains 'Cerner/Millennium'")
    elif "meditech" in sw:
        score -= 0.35
        reasons.append("softwareName contains 'MEDITECH'")
    elif "allscripts" in sw:
        score -= 0.35
        reasons.append("softwareName contains 'Allscripts'")
    elif "eclinicalworks" in sw or "ecw" in sw:
        score -= 0.35
        reasons.append("softwareName contains 'eClinicalWorks'")

    # --- Signal 2: Epic OID family (1.2.840.114350) ---
    if metadata.get("hasEpicOID") == "YES":
        score += 0.30
        reasons.append("has Epic OID (1.2.840.114350)")

    # --- Signal 3: Section order matches Epic pattern ---
    section_order_str = metadata.get("sectionOrder", "")
    # Extract LOINC codes from the section order string
    loinc_codes = re.findall(r"\((\d+-\d+)\)", section_order_str)
    if len(loinc_codes) >= 4:
        # Check if the first few sections match Epic's known order
        # Epic: Allergies(48765-2) -> Meds(10160-0) -> Problems(11450-4) -> Results(30954-2)
        epic_first_4 = ["48765-2", "10160-0", "11450-4", "30954-2"]
        if loinc_codes[:4] == epic_first_4:
            score += 0.15
            reasons.append("section order matches Epic pattern")
        elif loinc_codes[:2] == epic_first_4[:2]:
            score += 0.05
            reasons.append("partial section order match (first 2)")

    # --- Signal 4: templateId includes Epic companion templates ---
    template_str = metadata.get("templateIds", "").lower()
    # Standard CCD templateId is expected; Epic often pairs with specific extensions
    if "2.16.840.1.113883.10.20.22.1.2" in template_str:
        # This is the standard CCD template — not distinctive on its own
        # but if combined with other Epic signals, it counts slightly
        if score > 0.2:
            score += 0.05
            reasons.append("standard CCD templateId with other Epic signals")

    # --- Signal 5: Formatting style ---
    indent = metadata.get("indentStyle", "")
    if indent == "2-space" and score > 0.1:
        # 2-space is consistent with Epic but not definitive alone
        score += 0.05
        reasons.append("2-space indentation (consistent with Epic)")

    # --- Make the call ---
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
            reasons.append("weak/mixed signals")

    return guess, "; ".join(reasons) if reasons else "no signals"


def main():
    print("=" * 60)
    print("findandsaveEHRfromCCD.py")
    print("=" * 60)
    print(f"  AWSLocalCLIProfileName:    {AWSLocalCLIProfileName}")
    print(f"  Bucket:     {BUCKET}")
    print(f"  Input CSV:  {os.path.basename(INPUT_CSV)}")
    print(f"  Output CSV: {os.path.basename(OUTPUT_CSV)}")
    print(f"  Max files:  {MAX_FILES if MAX_FILES else 'ALL'}")
    print("=" * 60)

    # Read the input file list
    print(f"\nReading input CSV: {INPUT_CSV}")
    xml_keys = read_input_csv(INPUT_CSV, max_files=MAX_FILES)
    print(f"  Found {len(xml_keys)} documents to process.\n")

    if not xml_keys:
        print("No XML files found in input CSV. Exiting.")
        return

    # Connect to S3
    print(f"Connecting to S3 with AWSLocalCLIProfileName '{AWSLocalCLIProfileName}'...")
    s3 = get_s3_client(AWSLocalCLIProfileName)

    results = []
    for i, key in enumerate(xml_keys, 1):
        file_name = os.path.basename(key)
        path = os.path.dirname(key)
        print(f"  [{i}/{len(xml_keys)}] {file_name}")

        # Download the file content
        try:
            response = s3.get_object(Bucket=BUCKET, Key=key)
            xml_bytes = response["Body"].read()
        except Exception as e:
            print(f"    ERROR downloading: {e}")
            row = {field: "(error)" for field in OUTPUT_FIELDS}
            row["Path"] = f"s3://{BUCKET}/{path}/"
            row["FileName"] = file_name
            results.append(row)
            continue

        # Extract all fingerprint metadata
        try:
            metadata = extract_ccd_metadata(xml_bytes)
        except Exception as e:
            print(f"    ERROR parsing XML: {e}")
            metadata = {field: "(parse error)" for field in OUTPUT_FIELDS}

        metadata["Path"] = f"s3://{BUCKET}/{path}/"
        metadata["FileName"] = file_name

        print(f"    softwareName:     {metadata.get('softwareName', '')}")
        print(f"    mfrModel:         {metadata.get('manufacturerModelName', '')}")
        print(f"    custodian:        {metadata.get('custodianOrgName', '')}")
        print(f"    assigningAuth:    {metadata.get('Assigning-Authority', '')}")
        print(f"    hasEpicOID:       {metadata.get('hasEpicOID', '')}")
        print(f"    indentStyle:      {metadata.get('indentStyle', '')}")

        # Make an educated guess
        guess, reason = guess_ehr(metadata)
        metadata["EHR-Guess"] = guess
        metadata["EHR-GuessReason"] = reason
        print(f"    >>> EHR Guess:    {guess} ({reason})")

        results.append(metadata)

    # Write CSV
    print(f"\nWriting results to: {OUTPUT_CSV}")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(results)

    print(f"Done! Processed {len(results)} files.")


if __name__ == "__main__":
    main()
