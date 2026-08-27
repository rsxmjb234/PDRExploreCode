"""
check_diagnoses.py — ICD-10 F10-F19 SUD Diagnosis Checker
==========================================================

Looks for substance use disorder diagnoses in two places:
1. Encounter diagnoses (inside the Encounters section entryRelationship) — STRONG signal
2. Problems section (ongoing problem list) — WEAK signal (corroboration only)

We match ICD-10 codes starting with F1 (F10-F19), EXCLUDING F17 (nicotine).
F17 is not covered under 42 CFR Part 2.

Returns:
    dict with:
        sud_diagnoses_count (int) — total SUD diagnosis codes found in encounters
        sud_diagnoses_weak_count (int) — SUD codes found in problems section only
        sud_diagnosis_codes (str) — pipe-delimited list of codes found
"""

import re


# ICD-10 SUD pattern: F1x.xxx where x is 0-9, but NOT F17 (nicotine)
_SUD_PATTERN = re.compile(r"^F1[0-689]", re.IGNORECASE)
_NICOTINE_PATTERN = re.compile(r"^F17", re.IGNORECASE)


def check(root, ns):
    """
    Scan CCD for SUD diagnoses.

    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict with sud_diagnoses_count, sud_diagnoses_weak_count, sud_diagnosis_codes
    """
    encounter_codes = []
    problem_codes = []

    # -----------------------------------------------------------------------
    # 1. Encounter Diagnoses — STRONG signal
    #    These are diagnoses tied to THIS visit, found inside encounter entries
    #    as entryRelationship observations with ICD-10 value codes.
    # -----------------------------------------------------------------------
    # Look for encounters section entries
    for entry in root.iter(f"{{{ns}}}encounter"):
        # entryRelationship contains the diagnoses for this encounter
        for er in entry.iter(f"{{{ns}}}entryRelationship"):
            for obs in er.iter(f"{{{ns}}}observation"):
                # The diagnosis code is in <value> with @code and @codeSystem
                for value_el in obs.iter(f"{{{ns}}}value"):
                    code = value_el.get("code", "")
                    if _is_sud_code(code):
                        encounter_codes.append(code)
                # Also check <code> element within the observation
                for code_el in obs.iter(f"{{{ns}}}code"):
                    code = code_el.get("code", "")
                    if _is_sud_code(code):
                        if code not in encounter_codes:
                            encounter_codes.append(code)

    # -----------------------------------------------------------------------
    # 2. Problems Section — WEAK signal
    #    These are the patient's ongoing problem list. They may be historical
    #    or carried forward from other providers. We count them separately.
    # -----------------------------------------------------------------------
    # Problems are typically in observations within act/entryRelationship
    # under a section with templateId 2.16.840.1.113883.10.20.22.2.5 or .5.1
    for section in root.iter(f"{{{ns}}}section"):
        if _is_problems_section(section, ns):
            for obs in section.iter(f"{{{ns}}}observation"):
                for value_el in obs.iter(f"{{{ns}}}value"):
                    code = value_el.get("code", "")
                    if _is_sud_code(code):
                        # Don't double-count if already found in encounters
                        if code not in encounter_codes and code not in problem_codes:
                            problem_codes.append(code)

    # Combine for the pipe-delimited output
    all_codes = encounter_codes + problem_codes
    unique_codes = list(dict.fromkeys(all_codes))  # preserve order, dedupe

    return {
        "sud_diagnoses_count": len(encounter_codes),
        "sud_diagnoses_weak_count": len(problem_codes),
        "sud_diagnosis_codes": "|".join(unique_codes) if unique_codes else "",
    }


def _is_sud_code(code):
    """Return True if code matches F10-F19 pattern, excluding F17 (nicotine)."""
    if not code:
        return False
    if _NICOTINE_PATTERN.match(code):
        return False
    return bool(_SUD_PATTERN.match(code))


def _is_problems_section(section, ns):
    """Check if a section is the Problems section by templateId."""
    problems_templates = [
        "2.16.840.1.113883.10.20.22.2.5",
        "2.16.840.1.113883.10.20.22.2.5.1",
    ]
    for tmpl in section.iter(f"{{{ns}}}templateId"):
        root_val = tmpl.get("root", "")
        if root_val in problems_templates:
            return True
    return False


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import sys
    import xml.etree.ElementTree as ET

    if len(sys.argv) < 2:
        print("Usage: python -m checkers.check_diagnoses <ccd_file.xml>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    # Auto-detect namespace from root tag
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    result = check(root, ns)
    print(f"SUD Diagnoses (encounter): {result['sud_diagnoses_count']}")
    print(f"SUD Diagnoses (problems, weak): {result['sud_diagnoses_weak_count']}")
    print(f"Codes found: {result['sud_diagnosis_codes']}")
