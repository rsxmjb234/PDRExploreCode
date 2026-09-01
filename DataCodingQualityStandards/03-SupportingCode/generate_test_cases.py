"""
generate_test_cases.py — DEV Test Case Generator for CCD Coding Quality

PURPOSE:
    Read Synthea CCDs from S3, assign each a realistic source identity (QE/AA),
    and mutate the coding quality to match that source's known behavior.

    Real EHR systems are CONSISTENT: a source that codes labs to LOINC does so
    for every CCD it produces. This generator respects that by assigning each
    source a quality tier (A/B/C/D) and applying mutations consistently.

QUALITY TIERS:
    A = Well-coded: 90-100% national standards across all segments
    B = Decent: 75-89% standard, with 1-2 weak segments (labs or procedures)
    C = Mixed: 60-74% standard, several segments poorly coded, some absent
    D = Poorly coded: <60% standard, heavy local codes, multiple sections absent

    Per-document variance within a source is small (5-10%) because the
    underlying EHR configuration drives coding, not the patient data.

SOURCE PROFILES:
    Defined in exampleof5aaforeveryqe.txt (tab-separated: qe, aa, quality_tier, notes)
    Each source CCD gets assigned a QE/AA from this list and mutated accordingly.

OUTPUT:
    For each source CCD, generates 1 variant with quality consistent to its
    assigned source profile. Multiple CCDs per source allow us to verify
    that scoring is consistent across documents from the same source.
"""

import boto3
import xml.etree.ElementTree as ET
import csv
import io
import os
import json
import random
import time
from segment_mapping import SECTIONS, ALL_SEGMENT_KEYS, SECTIONS_BY_LOINC


# =============================================================================
# CONFIGURATION
# =============================================================================

AWS_PROFILE = "student1"
SOURCE_BUCKET = "nyec.ccda.learning"
SOURCE_PREFIX = "RawCCDs/"
MAX_SOURCE_FILES = 40
DOCS_PER_SOURCE = 10  # 10 CCDs per assigning authority = 36 AAs x 10 = 360 test cases

# Local output directory for generated test cases
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "06-Results", "Output", "DEV",
    "generated_test_cases"
)

# Source profiles file
PROFILES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "exampleof5aaforeveryqe.txt"
)

# Fake code system identifier for "Local" mutations
FAKE_LOCAL_OID = "1.2.3.4.5.6.7.LOCAL"

# CDA namespace
NS = "urn:hl7-org:v3"

# Register namespaces
ET.register_namespace("", NS)
ET.register_namespace("sdtc", "urn:hl7-org:sdtc")
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

# Random seed for reproducibility
random.seed(42)


# =============================================================================
# QUALITY TIER DEFINITIONS
# =============================================================================
# Each tier defines per-segment behavior:
#   "standard" = leave as national code (Synthea default)
#   "local" = swap code system to fake local
#   "missing" = remove coding (nullFlavor)
#   "absent" = remove entire section
#
# The pct values define what fraction of elements within a segment get mutated.
# E.g., {"state": "local", "pct": 0.3} means 30% of elements become local.

TIER_PROFILES = {
    "A": {
        # Well-coded: 90-100% standard everywhere
        "default_state": "standard",
        "segment_overrides": {},  # No overrides — everything stays standard
        "sections_absent": [],    # No sections removed
        "variance": 0.05,         # 5% random variance per document
    },
    "B": {
        # Decent: mostly good, but labs or procedures have some local codes
        "default_state": "standard",
        "segment_overrides": {
            "labs_results": {"state": "local", "pct": 0.25},
            "procedures": {"state": "local", "pct": 0.20},
            "immunizations": {"state": "local", "pct": 0.15},
        },
        "sections_absent": [],
        "variance": 0.08,
    },
    "C": {
        # Mixed: problems/meds ok, labs/procedures often local, some absent
        "default_state": "standard",
        "segment_overrides": {
            "labs_results": {"state": "local", "pct": 0.70},
            "procedures": {"state": "local", "pct": 0.60},
            "vitals": {"state": "local", "pct": 0.50},
            "allergies": {"state": "local", "pct": 0.40},
            "encounters": {"state": "local", "pct": 0.35},
            "problems": {"state": "local", "pct": 0.25},
        },
        "sections_absent": ["functional_status", "assessment"],
        "variance": 0.08,
    },
    "D": {
        # Poorly coded: mostly local, high missing, multiple sections absent
        "default_state": "standard",
        "segment_overrides": {
            "labs_results": {"state": "local", "pct": 0.80},
            "procedures": {"state": "local", "pct": 0.70},
            "medications": {"state": "local", "pct": 0.50},
            "problems": {"state": "local", "pct": 0.40},
            "vitals": {"state": "missing", "pct": 0.60},
            "allergies": {"state": "missing", "pct": 0.50},
            "encounters": {"state": "local", "pct": 0.60},
            "immunizations": {"state": "missing", "pct": 0.70},
        },
        "sections_absent": ["functional_status", "assessment", "care_plan", "social_history"],
        "variance": 0.08,
    },
}


# =============================================================================
# HELPER: Load source profiles
# =============================================================================

def load_source_profiles():
    """Load QE/AA/tier from exampleof5aaforeveryqe.txt."""
    profiles = []
    with open(PROFILES_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            profiles.append({
                "qe": row["qe"].strip(),
                "aa": row["aa"].strip(),
                "tier": row["quality_tier"].strip(),
                "notes": row.get("notes", "").strip(),
            })
    return profiles


# =============================================================================
# HELPER: Find/manipulate CCD sections
# =============================================================================

def find_sections(root):
    """Map CDA sections to segment keys using LOINC code."""
    found = {}
    sections = root.findall(
        f".//{{{NS}}}component/{{{NS}}}structuredBody/{{{NS}}}component/{{{NS}}}section"
    )
    for section in sections:
        code_el = section.find(f"{{{NS}}}code")
        if code_el is not None:
            loinc = code_el.get("code", "")
            if loinc in SECTIONS_BY_LOINC:
                seg_key = SECTIONS_BY_LOINC[loinc]
                found[seg_key] = section
    return found


def find_section_parent(root, section_element):
    """Find the parent <component> element wrapping a section."""
    for component in root.findall(f".//{{{NS}}}component/{{{NS}}}structuredBody/{{{NS}}}component"):
        sec = component.find(f"{{{NS}}}section")
        if sec is section_element:
            return component
    return None


def inject_assigning_authority(root, assigning_authority):
    """Set assigningAuthorityName in recordTarget/patientRole/id."""
    patient_ids = root.findall(f".//{{{NS}}}recordTarget/{{{NS}}}patientRole/{{{NS}}}id")
    if patient_ids:
        patient_ids[0].set("assigningAuthorityName", assigning_authority)
    else:
        patient_role = root.find(f".//{{{NS}}}recordTarget/{{{NS}}}patientRole")
        if patient_role is not None:
            id_el = ET.SubElement(patient_role, f"{{{NS}}}id")
            id_el.set("assigningAuthorityName", assigning_authority)
            id_el.set("root", "2.16.840.1.113883.4.1")


def get_coded_elements_for_section(section, seg_key):
    """
    Find the clinical entry code elements that the scorer will check.
    Uses the same entry_xpath and code_path as the scorer for alignment.
    """
    sec_def = SECTIONS[seg_key]
    entry_tag = sec_def["entry_xpath"].split("/")[-1]
    code_path = sec_def["code_path"]
    
    elements = []
    entries = section.findall(f".//{{{NS}}}{entry_tag}")
    
    for entry in entries:
        if code_path.startswith(".//"):
            parts = code_path[3:].split("/")
            xpath = "/".join(f"{{{NS}}}{p}" for p in parts)
            code_el = entry.find(f".//{xpath}")
        else:
            code_el = entry.find(f"{{{NS}}}{code_path}")
        
        if code_el is not None and (code_el.get("codeSystem") or code_el.get("code")):
            elements.append(code_el)
    
    return elements


def get_demographics_elements(root):
    """Get coded demographic elements."""
    patient = root.find(f".//{{{NS}}}recordTarget/{{{NS}}}patientRole/{{{NS}}}patient")
    if patient is None:
        return []
    elements = []
    for tag in ["raceCode", "ethnicGroupCode", "administrativeGenderCode", "maritalStatusCode"]:
        el = patient.find(f"{{{NS}}}{tag}")
        if el is not None:
            elements.append(el)
    lang_el = patient.find(f".//{{{NS}}}languageCommunication/{{{NS}}}languageCode")
    if lang_el is not None:
        elements.append(lang_el)
    return elements


# =============================================================================
# MUTATION: Apply tier-based mutations to a single section
# =============================================================================

def mutate_elements(elements, state, pct, variance):
    """
    Mutate a fraction of elements to the given state.
    
    Args:
        elements: list of XML elements to potentially mutate
        state: "local" or "missing"
        pct: base fraction to mutate (0.0-1.0)
        variance: random variance to add/subtract from pct
    
    Returns:
        tuple: (standard_count, local_count, missing_count)
    """
    actual_pct = max(0.0, min(1.0, pct + random.uniform(-variance, variance)))
    n_to_mutate = int(len(elements) * actual_pct)
    
    # Randomly select which elements to mutate
    indices_to_mutate = set(random.sample(range(len(elements)), min(n_to_mutate, len(elements))))
    
    standard = 0
    local = 0
    missing = 0
    
    for i, el in enumerate(elements):
        if i in indices_to_mutate:
            if state == "local":
                el.set("codeSystem", FAKE_LOCAL_OID)
                el.set("codeSystemName", "LOCAL_FACILITY_CODES")
                local += 1
            elif state == "missing":
                for attr in ["code", "codeSystem", "codeSystemName", "displayName"]:
                    if attr in el.attrib:
                        del el.attrib[attr]
                el.set("nullFlavor", "UNK")
                missing += 1
        else:
            standard += 1
    
    return standard, local, missing


# =============================================================================
# CORE: Generate one test CCD with source-consistent quality
# =============================================================================

def generate_test_ccd(root, source_profile, sections_found):
    """
    Apply tier-based mutations to make a CCD match its source's quality profile.
    
    Returns:
        dict: domain_counts for this CCD
    """
    tier = source_profile["tier"]
    tier_def = TIER_PROFILES[tier]
    variance = tier_def["variance"]
    structured_body = root.find(f".//{{{NS}}}component/{{{NS}}}structuredBody")
    
    domain_counts = {}
    
    for seg_key in ALL_SEGMENT_KEYS:
        # Check if this section should be absent for this tier
        if seg_key in tier_def["sections_absent"]:
            if seg_key in sections_found and structured_body is not None:
                parent = find_section_parent(root, sections_found[seg_key])
                if parent is not None:
                    structured_body.remove(parent)
            domain_counts[seg_key] = {
                "total": 0, "standard": 0, "local": 0, "missing": 0,
                "section_absent": True,
            }
            continue
        
        # Handle demographics separately
        if seg_key == "demographics":
            elements = get_demographics_elements(root)
            if not elements:
                domain_counts[seg_key] = {
                    "total": 0, "standard": 0, "local": 0, "missing": 0,
                    "section_absent": True,
                }
                continue
            
            override = tier_def["segment_overrides"].get(seg_key)
            if override:
                s, l, m = mutate_elements(elements, override["state"], override["pct"], variance)
            else:
                s, l, m = len(elements), 0, 0  # Standard by default
            
            domain_counts[seg_key] = {
                "total": s + l + m, "standard": s, "local": l, "missing": m,
                "section_absent": False,
            }
            continue
        
        # Regular section
        if seg_key not in sections_found:
            domain_counts[seg_key] = {
                "total": 0, "standard": 0, "local": 0, "missing": 0,
                "section_absent": True,
            }
            continue
        
        section = sections_found[seg_key]
        elements = get_coded_elements_for_section(section, seg_key)
        
        if not elements:
            domain_counts[seg_key] = {
                "total": 0, "standard": 0, "local": 0, "missing": 0,
                "section_absent": False,
            }
            continue
        
        # Apply tier-based mutation
        override = tier_def["segment_overrides"].get(seg_key)
        if override:
            s, l, m = mutate_elements(elements, override["state"], override["pct"], variance)
        else:
            # Default: leave as standard (with small variance for realism)
            s, l, m = len(elements), 0, 0
        
        domain_counts[seg_key] = {
            "total": s + l + m, "standard": s, "local": l, "missing": m,
            "section_absent": False,
        }
    
    return domain_counts


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 75)
    print("CCD Coding Quality — DEV Test Case Generator")
    print("=" * 75)
    print()
    
    # Load source profiles
    source_profiles = load_source_profiles()
    print(f"  Source profiles loaded: {len(source_profiles)} QE/AA pairs")
    for tier in ["A", "B", "C", "D"]:
        count = sum(1 for p in source_profiles if p["tier"] == tier)
        print(f"    Tier {tier}: {count} sources")
    print()
    print(f"  Source bucket:  s3://{SOURCE_BUCKET}/{SOURCE_PREFIX}")
    print(f"  Max source files (raw material): {MAX_SOURCE_FILES}")
    print(f"  Docs per source: {DOCS_PER_SOURCE}")
    print(f"  Total test cases: {len(source_profiles)} sources x {DOCS_PER_SOURCE} = {len(source_profiles) * DOCS_PER_SOURCE}")
    print(f"  Output dir:     {OUTPUT_DIR}")
    print()
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Connect to S3
    print("Connecting to S3...")
    session = boto3.Session(profile_name=AWS_PROFILE)
    s3 = session.client("s3")
    
    # List source files
    print("Listing source CCDs...")
    paginator = s3.get_paginator("list_objects_v2")
    source_keys = []
    for page in paginator.paginate(Bucket=SOURCE_BUCKET, Prefix=SOURCE_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].lower().endswith(".xml"):
                source_keys.append(obj["Key"])
                if MAX_SOURCE_FILES and len(source_keys) >= MAX_SOURCE_FILES:
                    break
        if MAX_SOURCE_FILES and len(source_keys) >= MAX_SOURCE_FILES:
            break
    
    print(f"  Found {len(source_keys)} source CCDs")
    print()
    
    manifest = []
    file_counter = 0
    
    for profile_idx, profile in enumerate(source_profiles):
        qe = profile["qe"]
        aa = profile["aa"]
        tier = profile["tier"]
        
        print(f"\n--- Source {profile_idx + 1}/{len(source_profiles)}: QE={qe}, AA={aa}, Tier={tier} ---")
        
        for doc_num in range(DOCS_PER_SOURCE):
            # Cycle through Synthea source files as raw material
            source_key = source_keys[file_counter % len(source_keys)]
            file_counter += 1
            
            file_name = os.path.basename(source_key).replace(".xml", "")
            
            # Download source CCD
            response = s3.get_object(Bucket=SOURCE_BUCKET, Key=source_key)
            xml_bytes = response["Body"].read()
            
            # Parse and mutate
            tree = ET.parse(io.BytesIO(xml_bytes))
            root = tree.getroot()
            
            # Inject assigning authority
            inject_assigning_authority(root, aa)
            
            # Find sections
            sections_found = find_sections(root)
            
            # Apply tier-consistent mutations
            domain_counts = generate_test_ccd(root, profile, sections_found)
            
            # Write mutated XML
            xml_filename = f"{aa.replace(' ', '_')}_{qe}_{doc_num:02d}_tier-{tier}.xml"
            xml_filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in xml_filename)
            xml_path = os.path.join(OUTPUT_DIR, xml_filename)
            tree.write(xml_path, xml_declaration=True, encoding="UTF-8")
            
            # Build expected outcome
            total = sum(dc["total"] for dc in domain_counts.values())
            std = sum(dc["standard"] for dc in domain_counts.values())
            loc = sum(dc["local"] for dc in domain_counts.values())
            mis = sum(dc["missing"] for dc in domain_counts.values())
            absent = sum(1 for dc in domain_counts.values() if dc["section_absent"])
            
            local_oid_counts = {}
            if loc > 0:
                local_oid_counts[FAKE_LOCAL_OID] = loc
            
            expected = {
                "test_case_id": f"{aa}_{tier}_{doc_num:02d}",
                "source_input_key": f"s3://{SOURCE_BUCKET}/{source_key}",
                "generated_output_key": xml_path,
                "source": {
                    "assigning_authority": aa,
                    "qe": qe,
                    "bucket": SOURCE_BUCKET,
                    "key": xml_filename,
                    "path": xml_path,
                    "quality_tier": tier,
                },
                "expected_result": {
                    "summary": {
                        "total_elements": total,
                        "standard_count": std,
                        "local_count": loc,
                        "missing_count": mis,
                        "sections_absent": absent,
                    },
                    "domain_counts": domain_counts,
                    "local_oid_counts": local_oid_counts,
                },
            }
            
            # Write expected JSON
            json_filename = xml_filename.replace(".xml", "_expected.json")
            json_path = os.path.join(OUTPUT_DIR, json_filename)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(expected, f, indent=2)
            
            manifest.append(expected)
        
        # Print summary for this source
        src_results = manifest[-DOCS_PER_SOURCE:]
        avg_std = int(sum(
            e["expected_result"]["summary"]["standard_count"] /
            max(e["expected_result"]["summary"]["total_elements"], 1) * 100
            for e in src_results
        ) / DOCS_PER_SOURCE)
        print(f"  Generated {DOCS_PER_SOURCE} CCDs, avg {avg_std}% standard")
    
    # Write manifest
    manifest_path = os.path.join(OUTPUT_DIR, "test_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    
    print()
    print("=" * 75)
    print("DONE!")
    print("=" * 75)
    print()
    print(f"Generated {len(manifest)} test cases ({len(source_profiles)} sources x {DOCS_PER_SOURCE} docs each)")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Manifest: {manifest_path}")
    print()
    
    # Print tier distribution
    tier_summary = {}
    for entry in manifest:
        t = entry["source"]["quality_tier"]
        tier_summary[t] = tier_summary.get(t, 0) + 1
    for t in sorted(tier_summary):
        print(f"  Tier {t}: {tier_summary[t]} test cases")


if __name__ == "__main__":
    main()
