"""
extract_patient_identity.py — CCD Patient Identity Extractor
=============================================================================

Extracts the patient-identifying fields a reviewer needs to look up a
candidate at the source (GUIDANCE.md Section 4b, "Patient Identity" letter
section): MRN, assigning authority, name, and date of birth.

Standard CDA R2 paths (same recordTarget/patientRole structure every CCD in
this repo uses — see 42CFRQualityCheck/extract_identity.py and
FindEHR/findandsaveEHRfromCCD-EntireCCD.py for the sibling source-identity
extractors this one complements):
    recordTarget/patientRole/id            -> MRN (root OID) + @assigningAuthorityName
    recordTarget/patientRole/patient/name  -> given/family
    recordTarget/patientRole/patient/birthTime -> @value (YYYYMMDD...)

Mirrors FindEHR's existing pattern of preferring the first non-Synthea
patient id when multiple <id> elements are present.
"""


def extract(root, ns):
    """
    Extract patient identity fields from a CCD.

    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict with mrn, assigning_authority, patient_last_name,
        patient_first_name, patient_dob (YYYY-MM-DD or "").
    """
    patient_role = root.find(f".//{{{ns}}}recordTarget/{{{ns}}}patientRole")

    mrn = ""
    assigning_authority = ""
    if patient_role is not None:
        id_elements = patient_role.findall(f"{{{ns}}}id")
        chosen = None
        for el in id_elements:
            aa = el.get("assigningAuthorityName", "")
            if aa and "synthea" not in aa.lower():
                chosen = el
                break
        if chosen is None and id_elements:
            chosen = id_elements[0]
        if chosen is not None:
            mrn = chosen.get("extension", "") or chosen.get("root", "")
            assigning_authority = chosen.get("assigningAuthorityName", "")

    last_name = ""
    first_name = ""
    dob = ""
    if patient_role is not None:
        name_el = patient_role.find(f"{{{ns}}}patient/{{{ns}}}name")
        if name_el is not None:
            given_el = name_el.find(f"{{{ns}}}given")
            family_el = name_el.find(f"{{{ns}}}family")
            if given_el is not None and given_el.text:
                first_name = given_el.text.strip()
            if family_el is not None and family_el.text:
                last_name = family_el.text.strip()

        birth_el = patient_role.find(f"{{{ns}}}patient/{{{ns}}}birthTime")
        if birth_el is not None:
            val = birth_el.get("value", "")
            if len(val) >= 8:
                dob = f"{val[0:4]}-{val[4:6]}-{val[6:8]}"

    encounter_date, encounter_location = _get_encounter_info(root, ns)

    return {
        "mrn": mrn,
        "assigning_authority": assigning_authority,
        "patient_last_name": last_name,
        "patient_first_name": first_name,
        "patient_dob": dob,
        "encounter_date": encounter_date,
        "encounter_location": encounter_location,
    }


def _get_encounter_info(root, ns):
    """
    Best-effort encounter date + location, for the dashboard's "most recent
    encounter" column (GUIDANCE.md Section 4a). Same encompassingEncounter
    path 42CFRQualityCheck's extract_identity.py uses for service location.
    """
    date_val = ""
    location = ""

    et = root.find(
        f".//{{{ns}}}componentOf/{{{ns}}}encompassingEncounter/{{{ns}}}effectiveTime"
    )
    if et is not None:
        val = et.get("value", "")
        if len(val) >= 8:
            date_val = f"{val[0:4]}-{val[4:6]}-{val[6:8]}"

    loc_el = root.find(
        f".//{{{ns}}}componentOf/{{{ns}}}encompassingEncounter"
        f"/{{{ns}}}location/{{{ns}}}healthCareFacility/{{{ns}}}location/{{{ns}}}name"
    )
    if loc_el is not None and loc_el.text and loc_el.text.strip():
        location = loc_el.text.strip()
    else:
        loc_el = root.find(
            f".//{{{ns}}}componentOf/{{{ns}}}encompassingEncounter"
            f"/{{{ns}}}location/{{{ns}}}healthCareFacility/{{{ns}}}name"
        )
        if loc_el is not None and loc_el.text and loc_el.text.strip():
            location = loc_el.text.strip()

    return date_val, location


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import sys
    import xml.etree.ElementTree as ET

    if len(sys.argv) < 2:
        print("Usage: python extract_patient_identity.py <ccd_file.xml>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    result = extract(root, ns)
    for key, val in result.items():
        print(f"  {key}: {val}")
