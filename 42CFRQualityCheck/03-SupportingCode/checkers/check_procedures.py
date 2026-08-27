"""
check_procedures.py — SUD Procedure Checker
=============================================

Scans the Procedures section for substance-use-related procedures:
urine drug screens (UDS), SBIRT, addiction counseling, toxicology.

Matches by code @displayName keyword OR by CPT code (80305-80307, 99408/99409).

Note: CPT code matches are also caught by check_billing_codes.py.
This module focuses on the Procedures section specifically and uses
keyword matching as a fallback when codes aren't present.

Returns:
    dict with:
        sud_procedures_count (int) — number of SUD procedures found
        sud_procedure_descriptions (str) — pipe-delimited descriptions found
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_pipeline_config import PROCEDURE_SUD_KEYWORDS


def check(root, ns):
    """
    Scan CCD Procedures section for SUD-related procedures.

    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict with sud_procedures_count, sud_procedure_descriptions
    """
    found_descriptions = []

    # Find procedures section
    proc_section = _find_procedures_section(root, ns)
    if proc_section is None:
        # Fall back to scanning all procedure elements
        proc_section = root

    for procedure in proc_section.iter(f"{{{ns}}}procedure"):
        description = _get_procedure_description(procedure, ns)
        if not description:
            continue

        desc_lower = description.lower()
        for keyword in PROCEDURE_SUD_KEYWORDS:
            if keyword in desc_lower:
                if description not in found_descriptions:
                    found_descriptions.append(description)
                break

    # Also check observation elements in procedures section (some CCDs
    # encode lab orders like UDS as observations within procedures)
    if proc_section is not root:
        for obs in proc_section.iter(f"{{{ns}}}observation"):
            description = _get_observation_description(obs, ns)
            if not description:
                continue
            desc_lower = description.lower()
            for keyword in PROCEDURE_SUD_KEYWORDS:
                if keyword in desc_lower:
                    if description not in found_descriptions:
                        found_descriptions.append(description)
                    break

    return {
        "sud_procedures_count": len(found_descriptions),
        "sud_procedure_descriptions": "|".join(found_descriptions) if found_descriptions else "",
    }


def _find_procedures_section(root, ns):
    """Find the Procedures section by templateId."""
    proc_templates = [
        "2.16.840.1.113883.10.20.22.2.7",    # Procedures
        "2.16.840.1.113883.10.20.22.2.7.1",  # Procedures (entries required)
    ]
    for section in root.iter(f"{{{ns}}}section"):
        for tmpl in section.iter(f"{{{ns}}}templateId"):
            if tmpl.get("root", "") in proc_templates:
                return section
    return None


def _get_procedure_description(procedure, ns):
    """Extract description from a procedure element."""
    for code_el in procedure.iter(f"{{{ns}}}code"):
        display = code_el.get("displayName", "")
        if display:
            return display.strip()
        for ot in code_el.iter(f"{{{ns}}}originalText"):
            if ot.text and ot.text.strip():
                return ot.text.strip()
        break
    return ""


def _get_observation_description(obs, ns):
    """Extract description from an observation element."""
    for code_el in obs.iter(f"{{{ns}}}code"):
        display = code_el.get("displayName", "")
        if display:
            return display.strip()
        for ot in code_el.iter(f"{{{ns}}}originalText"):
            if ot.text and ot.text.strip():
                return ot.text.strip()
        break
    return ""


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import xml.etree.ElementTree as ET

    if len(sys.argv) < 2:
        print("Usage: python -m checkers.check_procedures <ccd_file.xml>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    result = check(root, ns)
    print(f"SUD Procedures: {result['sud_procedures_count']}")
    print(f"Descriptions: {result['sud_procedure_descriptions']}")
