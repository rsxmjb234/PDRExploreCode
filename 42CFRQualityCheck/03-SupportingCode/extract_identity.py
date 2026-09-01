"""
extract_identity.py — CCD Source Identity Extractor
=====================================================

Extracts contextual identity fields from a CCD that tell us WHO the source
is, WHERE it is, and WHEN the document was created. These fields go into
the JSON output so the QE can identify the source without opening the CCD.

Fields extracted:
    ehr_software_name      — from assignedAuthoringDevice/softwareName
    custodian_org_name     — from representedCustodianOrganization/name
    custodian_org_address  — from representedCustodianOrganization/addr
                             (streetAddressLine + city + state + postalCode)
    service_location_name  — from componentOf/encompassingEncounter/location/
                             healthCareFacility/location/name
    ccd_created_date       — from ClinicalDocument/effectiveTime @value
                             (first 8 chars -> YYYY-MM-DD)

Returns:
    dict with all five fields (empty string if not found)
"""


def extract(root, ns):
    """
    Extract source identity fields from a CCD.

    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict with ehr_software_name, custodian_org_name, custodian_org_address,
        service_location_name, ccd_created_date, assigning_authority_name
    """
    return {
        "ehr_software_name": _get_ehr_software_name(root, ns),
        "custodian_org_name": _get_custodian_org_name(root, ns),
        "custodian_org_address": _get_custodian_org_address(root, ns),
        "service_location_name": _get_service_location_name(root, ns),
        "ccd_created_date": _get_ccd_created_date(root, ns),
        "assigning_authority_name": _get_assigning_authority_name(root, ns),
    }


def _get_ehr_software_name(root, ns):
    """
    Extract EHR software name from assignedAuthoringDevice/softwareName.
    Same logic as FindEHR — imperfect but good enough for context.
    """
    # Path: author/assignedAuthor/assignedAuthoringDevice/softwareName
    for device in root.iter(f"{{{ns}}}assignedAuthoringDevice"):
        for sw in device.iter(f"{{{ns}}}softwareName"):
            if sw.text and sw.text.strip():
                return sw.text.strip()
    return ""


def _get_custodian_org_name(root, ns):
    """
    Extract custodian organization name.
    Path: custodian/assignedCustodian/representedCustodianOrganization/name
    """
    el = root.find(
        f".//{{{ns}}}custodian/{{{ns}}}assignedCustodian"
        f"/{{{ns}}}representedCustodianOrganization/{{{ns}}}name"
    )
    if el is not None and el.text:
        return el.text.strip()
    return ""


def _get_custodian_org_address(root, ns):
    """
    Extract custodian organization address as a flat string.
    Path: custodian/assignedCustodian/representedCustodianOrganization/addr
    Concatenates: streetAddressLine(s) + city + state + postalCode
    """
    addr_el = root.find(
        f".//{{{ns}}}custodian/{{{ns}}}assignedCustodian"
        f"/{{{ns}}}representedCustodianOrganization/{{{ns}}}addr"
    )
    if addr_el is None:
        return ""

    parts = []

    # Street address lines (may be multiple)
    for street in addr_el.iter(f"{{{ns}}}streetAddressLine"):
        if street.text and street.text.strip():
            parts.append(street.text.strip())

    # City
    city_el = addr_el.find(f"{{{ns}}}city")
    if city_el is not None and city_el.text and city_el.text.strip():
        parts.append(city_el.text.strip())

    # State
    state_el = addr_el.find(f"{{{ns}}}state")
    if state_el is not None and state_el.text and state_el.text.strip():
        parts.append(state_el.text.strip())

    # Postal code
    zip_el = addr_el.find(f"{{{ns}}}postalCode")
    if zip_el is not None and zip_el.text and zip_el.text.strip():
        parts.append(zip_el.text.strip())

    return ", ".join(parts) if parts else ""


def _get_service_location_name(root, ns):
    """
    Extract the service location (specific unit/floor/department).
    Path: componentOf/encompassingEncounter/location/healthCareFacility/location/name

    This is distinct from custodian — it's the specific care location within
    the facility (e.g., "Outpatient Addiction Services", "Detox Unit Floor 3").
    """
    # Try the full path first
    el = root.find(
        f".//{{{ns}}}componentOf/{{{ns}}}encompassingEncounter"
        f"/{{{ns}}}location/{{{ns}}}healthCareFacility"
        f"/{{{ns}}}location/{{{ns}}}name"
    )
    if el is not None and el.text and el.text.strip():
        return el.text.strip()

    # Some CCDs put the name directly under healthCareFacility
    el = root.find(
        f".//{{{ns}}}componentOf/{{{ns}}}encompassingEncounter"
        f"/{{{ns}}}location/{{{ns}}}healthCareFacility/{{{ns}}}name"
    )
    if el is not None and el.text and el.text.strip():
        return el.text.strip()

    # Fall back: try serviceProviderOrganization/name within encompassingEncounter
    el = root.find(
        f".//{{{ns}}}componentOf/{{{ns}}}encompassingEncounter"
        f"/{{{ns}}}location/{{{ns}}}healthCareFacility"
        f"/{{{ns}}}serviceProviderOrganization/{{{ns}}}name"
    )
    if el is not None and el.text and el.text.strip():
        return el.text.strip()

    return ""


def _get_ccd_created_date(root, ns):
    """
    Extract the CCD creation date from the document header effectiveTime.
    Path: ClinicalDocument/effectiveTime @value
    Format: first 8 chars of value -> YYYY-MM-DD

    Example: <effectiveTime value="20260721143022-0400"/> -> "2026-07-21"
    """
    # effectiveTime is a direct child of the root (ClinicalDocument)
    for et in root.iter(f"{{{ns}}}effectiveTime"):
        val = et.get("value", "")
        if len(val) >= 8:
            try:
                year = val[0:4]
                month = val[4:6]
                day = val[6:8]
                return f"{year}-{month}-{day}"
            except (IndexError, ValueError):
                pass
        break  # only check the first effectiveTime (document-level)

    return ""


def _get_assigning_authority_name(root, ns):
    """
    Extract the assigningAuthorityName from the CCD's first <id> element.
    Format in the CCD: assigningAuthorityName="qe|assigning_authority"
    Returns the full value (e.g., "rochester|FLACRA") — caller splits on |.
    """
    for el in root.iter(f"{{{ns}}}id" if ns else "id"):
        aan = el.get("assigningAuthorityName", "")
        if aan:
            return aan.strip()
    return ""


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import sys
    import xml.etree.ElementTree as ET

    if len(sys.argv) < 2:
        print("Usage: python extract_identity.py <ccd_file.xml>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    result = extract(root, ns)
    for key, val in result.items():
        print(f"  {key}: {val}")
