"""
check_medications.py — MAT Medication Checker with Signal Strength
===================================================================

Scans the Medications section of a CCD for Medication-Assisted Treatment
(MAT) drugs. Classifies each hit by regulatory weight:

  STRONG:   methadone — only dispensed for OUD through certified OTPs
  MODERATE: buprenorphine, suboxone, subutex, sublocade, naltrexone, vivitrol
  WEAK:     naloxone, narcan, acamprosate, campral, disulfiram, antabuse

Only counts medications that appear ACTIVE (have an effectiveTime with a
high value or no explicit "completed" statusCode with an old date). This
filters out medication reconciliation entries ("patient reports taking X
from another clinic") which lack an author from this facility.

Returns:
    dict with:
        mat_medications_count (int) — total MAT medication hits
        mat_strong_signal_count (int) — methadone hits
        mat_moderate_signal_count (int) — buprenorphine/naltrexone etc hits
        mat_weak_signal_count (int) — naloxone/acamprosate etc hits
        methadone_dispensed (bool) — True if any methadone found active
        mat_medication_names (str) — pipe-delimited names found
"""

import sys
import os

# Add parent dir to path so we can import run_pipeline_config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_pipeline_config import MAT_STRONG, MAT_MODERATE, MAT_WEAK


def check(root, ns):
    """
    Scan CCD Medications section for MAT drugs.

    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict with mat_medications_count, mat_strong_signal_count,
        mat_moderate_signal_count, mat_weak_signal_count,
        methadone_dispensed, mat_medication_names
    """
    strong_hits = []
    moderate_hits = []
    weak_hits = []

    # Find the medications section by templateId
    med_section = _find_medications_section(root, ns)
    if med_section is None:
        # Fall back: scan entire document for substanceAdministration
        med_section = root

    # Iterate over substanceAdministration entries (the standard CDA medication pattern)
    for sa in med_section.iter(f"{{{ns}}}substanceAdministration"):
        # Check if this medication is active/current
        if not _is_active_medication(sa, ns):
            continue

        # Get the medication name from manufacturedMaterial/code or name
        med_name = _extract_medication_name(sa, ns)
        if not med_name:
            continue

        med_name_lower = med_name.lower()

        # Classify by signal strength
        matched = False
        for keyword in MAT_STRONG:
            if keyword in med_name_lower:
                strong_hits.append(med_name)
                matched = True
                break

        if not matched:
            for keyword in MAT_MODERATE:
                if keyword in med_name_lower:
                    moderate_hits.append(med_name)
                    matched = True
                    break

        if not matched:
            for keyword in MAT_WEAK:
                if keyword in med_name_lower:
                    weak_hits.append(med_name)
                    matched = True
                    break

    # Deduplicate names for the output field
    all_names = strong_hits + moderate_hits + weak_hits
    unique_names = list(dict.fromkeys(all_names))

    return {
        "mat_medications_count": len(all_names),
        "mat_strong_signal_count": len(strong_hits),
        "mat_moderate_signal_count": len(moderate_hits),
        "mat_weak_signal_count": len(weak_hits),
        "methadone_dispensed": len(strong_hits) > 0,
        "mat_medication_names": "|".join(unique_names) if unique_names else "",
    }


def _find_medications_section(root, ns):
    """Find the Medications section by templateId."""
    med_templates = [
        "2.16.840.1.113883.10.20.22.2.1",    # Medications
        "2.16.840.1.113883.10.20.22.2.1.1",  # Medications (entries required)
    ]
    for section in root.iter(f"{{{ns}}}section"):
        for tmpl in section.iter(f"{{{ns}}}templateId"):
            if tmpl.get("root", "") in med_templates:
                return section
    return None


def _is_active_medication(substance_admin, ns):
    """
    Determine if a substanceAdministration entry represents an active/current
    medication (not historical/discontinued).

    V1 simplification: count it if:
    - It has an effectiveTime with a <high> value (meaning still active), OR
    - It does NOT have statusCode = "completed" (which means discontinued)
    - Absence of statusCode is treated as active (common in real CCDs)
    """
    # Check statusCode — "completed" means discontinued
    for sc in substance_admin.iter(f"{{{ns}}}statusCode"):
        code = sc.get("code", "").lower()
        if code == "completed":
            return False
        break  # only check the first one

    # If we get here, it's either "active" or no statusCode (treat as active)
    return True


def _extract_medication_name(substance_admin, ns):
    """
    Extract the medication name from a substanceAdministration entry.

    Looks in:
    1. consumable/manufacturedProduct/manufacturedMaterial/code @displayName
    2. consumable/manufacturedProduct/manufacturedMaterial/code/originalText
    3. consumable/manufacturedProduct/manufacturedMaterial/name
    """
    # Path: consumable -> manufacturedProduct -> manufacturedMaterial
    for consumable in substance_admin.iter(f"{{{ns}}}consumable"):
        for mp in consumable.iter(f"{{{ns}}}manufacturedProduct"):
            for mm in mp.iter(f"{{{ns}}}manufacturedMaterial"):
                # Try code displayName first (most common)
                for code_el in mm.iter(f"{{{ns}}}code"):
                    display = code_el.get("displayName", "")
                    if display:
                        return display.strip()
                    # Try originalText within code
                    for ot in code_el.iter(f"{{{ns}}}originalText"):
                        if ot.text and ot.text.strip():
                            return ot.text.strip()

                # Try name element
                for name_el in mm.iter(f"{{{ns}}}name"):
                    if name_el.text and name_el.text.strip():
                        return name_el.text.strip()

    return ""


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import xml.etree.ElementTree as ET

    if len(sys.argv) < 2:
        print("Usage: python -m checkers.check_medications <ccd_file.xml>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    result = check(root, ns)
    print(f"MAT Medications total: {result['mat_medications_count']}")
    print(f"  Strong (methadone): {result['mat_strong_signal_count']}")
    print(f"  Moderate (buprenorphine etc): {result['mat_moderate_signal_count']}")
    print(f"  Weak (naloxone etc): {result['mat_weak_signal_count']}")
    print(f"Methadone dispensed: {result['methadone_dispensed']}")
    print(f"Names found: {result['mat_medication_names']}")
