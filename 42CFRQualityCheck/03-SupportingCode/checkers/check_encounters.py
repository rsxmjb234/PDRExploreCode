"""
check_encounters.py — SUD Encounter Type Checker
==================================================

Scans the Encounters section for encounter types consistent with SUD
treatment: detox, intensive outpatient, residential treatment, OTP visits,
substance use/abuse treatment, addiction counseling, MAT.

Matches on code @displayName or originalText via keyword search.

Returns:
    dict with:
        sud_encounters_count (int) — number of SUD-type encounters found
        sud_encounter_descriptions (str) — pipe-delimited descriptions found
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_pipeline_config import ENCOUNTER_SUD_KEYWORDS, SNOMED_SUD_ENCOUNTERS

_SNOMED_ENC_SET = set(SNOMED_SUD_ENCOUNTERS)


def check(root, ns):
    """
    Scan CCD Encounters section for SUD encounter types.

    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict with sud_encounters_count, sud_encounter_descriptions
    """
    found_descriptions = []

    # Find encounters section
    enc_section = _find_encounters_section(root, ns)
    if enc_section is None:
        # Fall back to scanning all encounter elements
        enc_section = root

    for encounter in enc_section.iter(f"{{{ns}}}encounter"):
        description = _get_encounter_description(encounter, ns)
        # SNOMED code match (backstop for coded encounters)
        matched_by_code = False
        for code_el in encounter.iter(f"{{{ns}}}code"):
            if code_el.get("code", "") in _SNOMED_ENC_SET:
                matched_by_code = True
                if not description:
                    description = code_el.get("displayName", "") or "SUD treatment encounter"
                break

        if matched_by_code:
            if description not in found_descriptions:
                found_descriptions.append(description)
            continue

        if not description:
            continue

        desc_lower = description.lower()
        for keyword in ENCOUNTER_SUD_KEYWORDS:
            if keyword in desc_lower:
                if description not in found_descriptions:
                    found_descriptions.append(description)
                break

    return {
        "sud_encounters_count": len(found_descriptions),
        "sud_encounter_descriptions": "|".join(found_descriptions) if found_descriptions else "",
        "sud_encounter_findings": [f"{d} (Encounter)" for d in found_descriptions],
    }


def _find_encounters_section(root, ns):
    """Find the Encounters section by templateId."""
    enc_templates = [
        "2.16.840.1.113883.10.20.22.2.22",    # Encounters
        "2.16.840.1.113883.10.20.22.2.22.1",  # Encounters (entries required)
    ]
    for section in root.iter(f"{{{ns}}}section"):
        for tmpl in section.iter(f"{{{ns}}}templateId"):
            if tmpl.get("root", "") in enc_templates:
                return section
    return None


def _get_encounter_description(encounter, ns):
    """
    Extract a human-readable description from an encounter element.
    Checks code @displayName, originalText, and text references.
    """
    # Try code displayName
    for code_el in encounter.iter(f"{{{ns}}}code"):
        display = code_el.get("displayName", "")
        if display:
            return display.strip()
        # Try originalText
        for ot in code_el.iter(f"{{{ns}}}originalText"):
            if ot.text and ot.text.strip():
                return ot.text.strip()
        break  # only check the first code element

    # Try text element directly
    for text_el in encounter.iter(f"{{{ns}}}text"):
        if text_el.text and text_el.text.strip():
            return text_el.text.strip()

    return ""


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import xml.etree.ElementTree as ET

    if len(sys.argv) < 2:
        print("Usage: python -m checkers.check_encounters <ccd_file.xml>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    result = check(root, ns)
    print(f"SUD Encounters: {result['sud_encounters_count']}")
    print(f"Descriptions: {result['sud_encounter_descriptions']}")
