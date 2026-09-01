"""
check_diagnoses.py — SUD Diagnosis Checker (ICD-10 AND SNOMED-CT)
==================================================================

Looks for substance use disorder diagnoses in two places:
1. Encounter diagnoses (inside the Encounters section entryRelationship) — STRONG signal
2. Problems section (ongoing problem list) — WEAK signal (corroboration only)

Matches BOTH:
  - ICD-10 codes starting with F1 (F10-F19), EXCLUDING F17 (nicotine)
  - SNOMED-CT SUD concept IDs (curated set), plus a displayName keyword
    fallback so newly-seen SUD concepts still register.

Nicotine/tobacco-only findings are excluded (mirrors the F17 exclusion) since
they are not 42 CFR Part 2-protected.

Returns:
    dict with:
        sud_diagnoses_count (int) — total SUD diagnosis codes found in encounters
        sud_diagnoses_weak_count (int) — SUD codes found in problems section only
        sud_diagnosis_codes (str) — pipe-delimited list of codes found
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_pipeline_config import (
    SNOMED_SUD_DIAGNOSES,
    SNOMED_SUD_DIAGNOSIS_KEYWORDS,
    SNOMED_NICOTINE_EXCLUDE,
)


# ICD-10 SUD pattern: F1x.xxx where x is 0-9, but NOT F17 (nicotine)
_SUD_PATTERN = re.compile(r"^F1[0-689]", re.IGNORECASE)
_NICOTINE_PATTERN = re.compile(r"^F17", re.IGNORECASE)

_SNOMED_SUD_SET = set(SNOMED_SUD_DIAGNOSES)
_SNOMED_NICOTINE_SET = set(SNOMED_NICOTINE_EXCLUDE)


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
    findings = []  # human-readable: "code — Description (Section)"

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
                # The diagnosis code is in <value> with @code and @displayName
                for value_el in obs.iter(f"{{{ns}}}value"):
                    code = value_el.get("code", "")
                    if _is_sud_code(code, value_el.get("displayName", "")):
                        if code not in encounter_codes:
                            encounter_codes.append(code)
                            findings.append(_finding(code, value_el.get("displayName", ""),
                                                     "Encounter Diagnosis"))
                # Also check <code> element within the observation
                for code_el in obs.iter(f"{{{ns}}}code"):
                    code = code_el.get("code", "")
                    if _is_sud_code(code, code_el.get("displayName", "")):
                        if code not in encounter_codes:
                            encounter_codes.append(code)
                            findings.append(_finding(code, code_el.get("displayName", ""),
                                                     "Encounter Diagnosis"))

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
                    if _is_sud_code(code, value_el.get("displayName", "")):
                        # Don't double-count if already found in encounters
                        if code not in encounter_codes and code not in problem_codes:
                            problem_codes.append(code)
                            findings.append(_finding(code, value_el.get("displayName", ""),
                                                     "Problem List"))

    # Combine for the pipe-delimited output
    all_codes = encounter_codes + problem_codes
    unique_codes = list(dict.fromkeys(all_codes))  # preserve order, dedupe

    return {
        "sud_diagnoses_count": len(encounter_codes),
        "sud_diagnoses_weak_count": len(problem_codes),
        "sud_diagnosis_codes": "|".join(unique_codes) if unique_codes else "",
        "sud_diagnosis_findings": findings,
    }


def _finding(code, display_name, section):
    """Build a human-readable finding string: 'Description [code] (Section)'."""
    desc = (display_name or "").strip() or "(no description)"
    return f"{desc} [{code}] ({section})"


def _is_sud_code(code, display_name=""):
    """
    Return True if this is a SUD diagnosis, matching either:
      - ICD-10 F10-F19 (excluding F17 nicotine), OR
      - a curated SNOMED-CT SUD concept ID, OR
      - a displayName keyword (fallback for unlisted SUD concepts)
    Nicotine/tobacco-only findings are excluded.
    """
    if not code:
        return False

    disp = (display_name or "").lower()

    # Exclude nicotine/tobacco (mirrors F17 exclusion)
    if _NICOTINE_PATTERN.match(code):
        return False
    if code in _SNOMED_NICOTINE_SET:
        return False
    if ("nicotine" in disp or "tobacco" in disp) and not any(
        k in disp for k in SNOMED_SUD_DIAGNOSIS_KEYWORDS
    ):
        return False

    # ICD-10 F10-F19
    if _SUD_PATTERN.match(code):
        return True

    # Curated SNOMED-CT SUD concept IDs
    if code in _SNOMED_SUD_SET:
        return True

    # displayName keyword fallback (catches SUD concepts not in the curated set)
    if disp and any(k in disp for k in SNOMED_SUD_DIAGNOSIS_KEYWORDS):
        return True

    return False


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
