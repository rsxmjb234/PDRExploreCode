"""
score_ccd_coding_quality.py — Score a CCD's coding quality per section

Simple approach:
  1. Find each clinical section by its LOINC code
  2. Find the clinical entries within that section
  3. Check each entry's primary code: is it a recognized national standard?
  4. Count: Standard / Local / Missing per section

We ONLY look at clinical entry codes — not structural CDA wrappers.
"""

import xml.etree.ElementTree as ET
import os
import json
import argparse
from collections import Counter
from segment_mapping import SECTIONS, ALL_SEGMENT_KEYS, SECTIONS_BY_LOINC

NS = "urn:hl7-org:v3"


# =============================================================================
# CORE: Score one CCD
# =============================================================================

def score_ccd(xml_path, source_metadata=None):
    """
    Parse a CCD and score each section's coding quality.
    
    For each section: find clinical entries, check if their code uses
    a recognized national standard for that section type.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Find all sections by LOINC code
    section_elements = _find_sections(root)

    domain_counts = {}
    local_systems = Counter()

    for seg_key, sec_def in SECTIONS.items():
        if seg_key == "demographics":
            counts, locals_found = _score_demographics(root, sec_def)
        elif seg_key in section_elements:
            counts, locals_found = _score_section(
                section_elements[seg_key], sec_def
            )
        else:
            counts = {"total": 0, "standard": 0, "local": 0, "missing": 0, "section_absent": True}
            locals_found = {}

        domain_counts[seg_key] = counts
        local_systems.update(locals_found)

    # Summary
    total = sum(dc["total"] for dc in domain_counts.values())
    standard = sum(dc["standard"] for dc in domain_counts.values())
    local = sum(dc["local"] for dc in domain_counts.values())
    missing = sum(dc["missing"] for dc in domain_counts.values())
    absent = sum(1 for dc in domain_counts.values() if dc["section_absent"])

    return {
        "source": source_metadata or {},
        "summary": {
            "total_entries": total,
            "standard_count": standard,
            "local_count": local,
            "missing_count": missing,
            "sections_absent": absent,
        },
        "domain_counts": domain_counts,
        "local_code_systems_found": dict(local_systems),
    }


# =============================================================================
# Find sections by LOINC code
# =============================================================================

def _find_sections(root):
    """Map section elements to segment keys using their LOINC code."""
    found = {}
    for section in root.findall(
        f".//{{{NS}}}component/{{{NS}}}structuredBody/{{{NS}}}component/{{{NS}}}section"
    ):
        code_el = section.find(f"{{{NS}}}code")
        if code_el is not None:
            loinc = code_el.get("code", "")
            if loinc in SECTIONS_BY_LOINC:
                seg_key = SECTIONS_BY_LOINC[loinc]
                found[seg_key] = section
    return found


# =============================================================================
# Score one section: find entries, check their codes
# =============================================================================

def _score_section(section_element, sec_def):
    """
    Find clinical entries in a section and classify each entry's code.
    
    Returns:
        tuple: (counts_dict, local_systems_counter)
    """
    accepted = set(sec_def["accepted"].keys())
    entry_tag = sec_def["entry_xpath"].split("/")[-1]  # e.g., "observation", "substanceAdministration"
    code_path = sec_def["code_path"]  # e.g., "code", "value", ".//manufacturedMaterial/code"

    standard = 0
    local = 0
    missing = 0
    local_systems = Counter()

    # Find all entry elements of the expected type within this section
    entries = section_element.findall(f".//{{{NS}}}{entry_tag}")

    for entry in entries:
        # Find the code element on this entry
        classification = _classify_entry_code(entry, code_path, accepted)

        if classification == "standard":
            standard += 1
        elif classification == "local":
            local += 1
            # Track which local system was used
            code_el = _find_code_element(entry, code_path)
            if code_el is not None:
                sys_oid = code_el.get("codeSystem", "")
                if sys_oid:
                    local_systems[sys_oid] += 1
        else:
            missing += 1

    total = standard + local + missing

    return {
        "total": total,
        "standard": standard,
        "local": local,
        "missing": missing,
        "section_absent": False,
    }, dict(local_systems)


def _find_code_element(entry, code_path):
    """Find the code element on an entry using the configured path."""
    if code_path.startswith(".//"):
        # Nested path like ".//manufacturedMaterial/code"
        parts = code_path[3:].split("/")
        xpath = "/".join(f"{{{NS}}}{p}" for p in parts)
        return entry.find(f".//{xpath}")
    else:
        # Direct child like "code" or "value"
        return entry.find(f"{{{NS}}}{code_path}")


def _classify_entry_code(entry, code_path, accepted_systems):
    """
    Classify one entry's code as standard, local, or missing.
    
    Checks primary code first. If not standard, checks translation elements.
    """
    code_el = _find_code_element(entry, code_path)

    if code_el is None:
        return "missing"

    code_system = code_el.get("codeSystem", "")
    code_val = code_el.get("code", "")
    null_flavor = code_el.get("nullFlavor", "")

    # No code at all or nullFlavor
    if null_flavor or (not code_val and not code_system):
        return "missing"

    # Primary code uses a national standard
    if code_system in accepted_systems:
        return "standard"

    # Check translation elements (some sources put standard code in translation)
    for translation in code_el.findall(f"{{{NS}}}translation"):
        trans_system = translation.get("codeSystem", "")
        if trans_system in accepted_systems:
            return "standard"

    # Has a code but not a recognized national standard
    if code_system:
        return "local"

    return "missing"


# =============================================================================
# Score demographics (header, not a section)
# =============================================================================

def _score_demographics(root, sec_def):
    """Score demographic coded elements in the CDA header."""
    accepted = set(sec_def["accepted"].keys())
    patient = root.find(f".//{{{NS}}}recordTarget/{{{NS}}}patientRole/{{{NS}}}patient")

    if patient is None:
        return {"total": 0, "standard": 0, "local": 0, "missing": 0, "section_absent": True}, {}

    standard = 0
    local = 0
    missing = 0
    local_systems = Counter()

    for tag in ["raceCode", "ethnicGroupCode", "administrativeGenderCode"]:
        el = patient.find(f"{{{NS}}}{tag}")
        if el is None:
            continue

        code_system = el.get("codeSystem", "")
        code_val = el.get("code", "")
        null_flavor = el.get("nullFlavor", "")

        if null_flavor or (not code_val and not code_system):
            missing += 1
        elif code_system in accepted:
            standard += 1
        elif code_system:
            local += 1
            local_systems[code_system] += 1
        else:
            missing += 1

    total = standard + local + missing
    return {
        "total": total,
        "standard": standard,
        "local": local,
        "missing": missing,
        "section_absent": False,
    }, dict(local_systems)


# =============================================================================
# BATCH: Score a directory of XMLs
# =============================================================================

def score_directory(input_dir, output_dir):
    """Score all XML files in a directory, write result JSONs."""
    os.makedirs(output_dir, exist_ok=True)
    xml_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".xml")]
    print(f"Found {len(xml_files)} XML files to score")
    print()

    for idx, filename in enumerate(sorted(xml_files), 1):
        xml_path = os.path.join(input_dir, filename)

        # Get source metadata from expected JSON sidecar if available
        expected_path = os.path.join(input_dir, filename.replace(".xml", "_expected.json"))
        if os.path.exists(expected_path):
            try:
                with open(expected_path, "r", encoding="utf-8") as jf:
                    exp = json.load(jf)
                source_metadata = exp.get("source", {})
            except Exception:
                source_metadata = {"assigning_authority": "(unknown)", "qe": "(unknown)"}
        else:
            source_metadata = {"assigning_authority": "(unknown)", "qe": "(unknown)"}

        result = score_ccd(xml_path, source_metadata=source_metadata)

        # Write result
        result_filename = filename.replace(".xml", "_scored.json")
        result_path = os.path.join(output_dir, result_filename)
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        summary = result["summary"]
        total = summary["total_entries"]
        std = summary["standard_count"]
        pct = int(100 * std / total) if total > 0 else 0
        print(f"  [{idx:3d}/{len(xml_files)}] {filename[:55]}  {pct}% standard ({total} entries)")

    print()
    print(f"Wrote {len(xml_files)} result files to: {output_dir}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Score CCD coding quality")
    parser.add_argument("--input", help="Single CCD XML file")
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument("--input-dir", help="Directory of CCD XMLs")
    parser.add_argument("--output-dir", help="Directory for result JSONs")
    args = parser.parse_args()

    if args.input:
        result = score_ccd(args.input)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        else:
            print(json.dumps(result, indent=2))

    elif args.input_dir:
        output_dir = args.output_dir or os.path.join(args.input_dir, "scored_results")
        score_directory(args.input_dir, output_dir)

    else:
        # Default: score generated test cases
        base = os.path.dirname(os.path.abspath(__file__))
        test_dir = os.path.join(base, "DEV-Output", "generated_test_cases")
        scored_dir = os.path.join(base, "DEV-Output", "scored_results")

        print("=" * 75)
        print("CCD Coding Quality — Scorer (entry-focused)")
        print("=" * 75)
        print()
        print(f"  Input:  {test_dir}")
        print(f"  Output: {scored_dir}")
        print()

        if not os.path.exists(test_dir):
            print("ERROR: generated_test_cases/ not found. Run generate_test_cases.py first.")
            return

        score_directory(test_dir, scored_dir)
        print()
        print("Done! Run validate_test_cases.py to compare against expected outcomes.")


if __name__ == "__main__":
    main()
