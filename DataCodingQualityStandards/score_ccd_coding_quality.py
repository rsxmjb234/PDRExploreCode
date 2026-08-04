"""
score_ccd_coding_quality.py — Core Scoring Pipeline for CCD Coding Quality

PURPOSE:
    Read a CCD XML file, walk all 14 segments, classify each coded element as
    Standard / Local / Missing, and output a JSON result that matches the
    expected-outcome contract from the DEV test-case generator.

    This is the script that must produce IDENTICAL output to the expected JSONs
    before it can be promoted to PROD.

HOW IT WORKS:
    1. Parse the CCD XML with ElementTree
    2. Find each of the 14 segments (by LOINC section code or header location)
    3. For each segment, walk all coded elements (code, value, translation tags)
    4. Classify each element:
       - Standard: codeSystem OID is in the segment's accepted national list
       - Local: codeSystem OID is present but NOT in the national list
       - Missing: no @code or @codeSystem (or nullFlavor present)
    5. If a segment's section doesn't exist in the CCD: mark section_absent=True
    6. Output JSON with summary + domain_counts + local_oid_counts

USAGE:
    # Score a single file:
    python score_ccd_coding_quality.py --input path/to/ccd.xml --output path/to/result.json

    # Score all files in a directory:
    python score_ccd_coding_quality.py --input-dir path/to/dir/ --output-dir path/to/results/

    # Score the generated test cases (default mode):
    python score_ccd_coding_quality.py
"""

import xml.etree.ElementTree as ET
import os
import json
import argparse
from collections import Counter
from segment_mapping import (
    SEGMENT_DEFINITIONS, SEGMENTS_BY_LOINC, ALL_SEGMENT_KEYS, SEGMENTS_BY_KEY,
    ALL_NATIONAL_CODE_SYSTEMS
)


# CDA namespace
NS = "urn:hl7-org:v3"


# =============================================================================
# CORE: Score a single CCD
# =============================================================================

def score_ccd(xml_path, source_metadata=None):
    """
    Parse a CCD XML file and score all 14 segments for coding quality.

    Args:
        xml_path (str): Path to a CCD XML file
        source_metadata (dict, optional): Source context from candidates CSV:
            - assigning_authority: who sent this CCD
            - qe: which QE it came through
            - bucket: S3 bucket
            - key: S3 object key
            - path: full s3://bucket/key

    Returns:
        dict: Scoring result with source metadata and domain_counts
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Find all sections and map to segment keys
    sections_found = _find_sections(root)

    # Score each segment
    domain_counts = {}
    local_oid_counter = Counter()

    for seg_key in ALL_SEGMENT_KEYS:
        if seg_key == "demographics":
            counts, local_oids = _score_demographics(root)
        elif seg_key in sections_found:
            counts, local_oids = _score_section(sections_found[seg_key], seg_key)
        else:
            # Section absent
            counts = {
                "total": 0,
                "standard": 0,
                "local": 0,
                "missing": 0,
                "section_absent": True,
            }
            local_oids = {}

        domain_counts[seg_key] = counts
        local_oid_counter.update(local_oids)

    # Build summary
    total_elements = sum(dc["total"] for dc in domain_counts.values())
    standard_count = sum(dc["standard"] for dc in domain_counts.values())
    local_count = sum(dc["local"] for dc in domain_counts.values())
    missing_count = sum(dc["missing"] for dc in domain_counts.values())
    sections_absent = sum(1 for dc in domain_counts.values() if dc["section_absent"])

    result = {
        "source": source_metadata or {},
        "summary": {
            "total_elements": total_elements,
            "standard_count": standard_count,
            "local_count": local_count,
            "missing_count": missing_count,
            "sections_absent": sections_absent,
        },
        "domain_counts": domain_counts,
        "local_oid_counts": dict(local_oid_counter),
    }

    return result


# =============================================================================
# HELPER: Find sections in a CCD
# =============================================================================

def _find_sections(root):
    """Map CDA sections to segment keys using their LOINC code."""
    found = {}
    sections = root.findall(
        f".//{{{NS}}}component/{{{NS}}}structuredBody/{{{NS}}}component/{{{NS}}}section"
    )

    for section in sections:
        code_el = section.find(f"{{{NS}}}code")
        if code_el is not None:
            loinc = code_el.get("code", "")
            if loinc in SEGMENTS_BY_LOINC:
                seg_key = SEGMENTS_BY_LOINC[loinc]["segment_key"]
                found[seg_key] = section

    return found


# =============================================================================
# HELPER: Score a single section
# =============================================================================

def _score_section(section, segment_key):
    """
    Walk all coded elements in a section and classify each.

    Returns:
        tuple: (counts_dict, local_oids_dict)
    """
    seg_def = SEGMENTS_BY_KEY[segment_key]
    accepted_oids = set(seg_def["accepted_code_systems"].keys()) | ALL_NATIONAL_CODE_SYSTEMS

    standard = 0
    local = 0
    missing = 0
    local_oids = Counter()

    for el in section.iter():
        if el.tag not in [f"{{{NS}}}code", f"{{{NS}}}value", f"{{{NS}}}translation"]:
            continue

        code_system = el.get("codeSystem", "")
        code_val = el.get("code", "")
        null_flavor = el.get("nullFlavor", "")

        # Classify this element
        if null_flavor or (not code_val and not code_system):
            # Missing: nullFlavor or no code/codeSystem at all
            missing += 1
        elif code_system in accepted_oids:
            # Standard: recognized national code system
            standard += 1
        elif code_system:
            # Local: has a codeSystem but it's not national
            local += 1
            local_oids[code_system] += 1
        else:
            # Has a code but no codeSystem — treat as missing
            missing += 1

    total = standard + local + missing

    counts = {
        "total": total,
        "standard": standard,
        "local": local,
        "missing": missing,
        "section_absent": False,
    }

    return counts, dict(local_oids)


# =============================================================================
# HELPER: Score demographics
# =============================================================================

def _score_demographics(root):
    """
    Score coded demographic elements in recordTarget/patientRole/patient.
    Demographics use a broader acceptance: any recognized demographic OID counts.
    """
    seg_def = SEGMENTS_BY_KEY["demographics"]
    accepted_oids = set(seg_def["accepted_code_systems"].keys())

    patient = root.find(f".//{{{NS}}}recordTarget/{{{NS}}}patientRole/{{{NS}}}patient")
    if patient is None:
        return {
            "total": 0, "standard": 0, "local": 0, "missing": 0,
            "section_absent": True,
        }, {}

    standard = 0
    local = 0
    missing = 0
    local_oids = Counter()

    # Check each demographic coded element
    demo_tags = [
        "raceCode", "ethnicGroupCode", "administrativeGenderCode", "maritalStatusCode"
    ]

    for tag in demo_tags:
        el = patient.find(f"{{{NS}}}{tag}")
        if el is None:
            continue

        code_system = el.get("codeSystem", "")
        code_val = el.get("code", "")
        null_flavor = el.get("nullFlavor", "")

        if null_flavor or (not code_val and not code_system):
            missing += 1
        elif code_system in accepted_oids:
            standard += 1
        elif code_system:
            local += 1
            local_oids[code_system] += 1
        else:
            missing += 1

    # Language
    lang_el = patient.find(f".//{{{NS}}}languageCommunication/{{{NS}}}languageCode")
    if lang_el is not None:
        code_val = lang_el.get("code", "")
        null_flavor = lang_el.get("nullFlavor", "")
        if null_flavor or not code_val:
            missing += 1
        else:
            # languageCode uses @code directly (no codeSystem attribute in CDA)
            # If it has a value, count as standard
            standard += 1

    total = standard + local + missing

    counts = {
        "total": total,
        "standard": standard,
        "local": local,
        "missing": missing,
        "section_absent": False,
    }

    return counts, dict(local_oids)


# =============================================================================
# BATCH SCORING
# =============================================================================

def score_directory(input_dir, output_dir):
    """
    Score all XML files in a directory and write result JSONs.

    Args:
        input_dir (str): Directory containing CCD XML files
        output_dir (str): Directory to write result JSON files
    """
    os.makedirs(output_dir, exist_ok=True)

    xml_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".xml")]
    print(f"Found {len(xml_files)} XML files to score")
    print()

    for idx, filename in enumerate(sorted(xml_files), 1):
        xml_path = os.path.join(input_dir, filename)
        
        # Try to get real source metadata from the expected JSON sidecar
        expected_json_path = os.path.join(input_dir, filename.replace(".xml", "_expected.json"))
        if os.path.exists(expected_json_path):
            try:
                with open(expected_json_path, "r", encoding="utf-8") as jf:
                    exp = json.load(jf)
                source_info = exp.get("source", {})
                source_metadata = {
                    "assigning_authority": source_info.get("assigning_authority", "(unknown)"),
                    "qe": source_info.get("qe", "(unknown)"),
                    "bucket": source_info.get("bucket", ""),
                    "key": source_info.get("key", filename),
                    "path": source_info.get("path", xml_path),
                }
            except Exception:
                source_metadata = {
                    "assigning_authority": "(unknown)",
                    "qe": "(unknown)",
                    "bucket": "",
                    "key": filename,
                    "path": xml_path,
                }
        else:
            source_metadata = {
                "assigning_authority": "(unknown)",
                "qe": "(unknown)",
                "bucket": "",
                "key": filename,
                "path": xml_path,
            }
        
        result = score_ccd(xml_path, source_metadata=source_metadata)

        # Write result JSON
        result_filename = filename.replace(".xml", "_scored.json")
        result_path = os.path.join(output_dir, result_filename)
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        summary = result["summary"]
        print(f"  [{idx:2d}/{len(xml_files)}] {filename}")
        print(f"           S={summary['standard_count']} L={summary['local_count']} "
              f"M={summary['missing_count']} Absent={summary['sections_absent']}")

    print()
    print(f"Wrote {len(xml_files)} result files to: {output_dir}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Score CCD coding quality")
    parser.add_argument("--input", help="Single CCD XML file to score")
    parser.add_argument("--output", help="Output JSON path (for single file mode)")
    parser.add_argument("--input-dir", help="Directory of CCD XMLs to score")
    parser.add_argument("--output-dir", help="Directory for result JSONs")
    args = parser.parse_args()

    if args.input:
        # Single file mode
        print(f"Scoring: {args.input}")
        result = score_ccd(args.input)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"Result written to: {args.output}")
        else:
            print(json.dumps(result, indent=2))

    elif args.input_dir:
        # Directory mode
        output_dir = args.output_dir or os.path.join(args.input_dir, "scored_results")
        score_directory(args.input_dir, output_dir)

    else:
        # Default: score the generated test cases
        test_cases_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "DEV-Output",
            "generated_test_cases"
        )
        scored_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "DEV-Output",
            "scored_results"
        )

        print("=" * 75)
        print("CCD Coding Quality — Core Scoring Pipeline")
        print("=" * 75)
        print()
        print(f"  Input:  {test_cases_dir}")
        print(f"  Output: {scored_dir}")
        print()

        if not os.path.exists(test_cases_dir):
            print("ERROR: generated_test_cases/ not found. Run generate_test_cases.py first.")
            return

        score_directory(test_cases_dir, scored_dir)

        print()
        print("Done! Run validate_test_cases.py to compare against expected outcomes.")


if __name__ == "__main__":
    main()
