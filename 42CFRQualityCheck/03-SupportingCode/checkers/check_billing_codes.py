"""
check_billing_codes.py — OTP/SUD Billing Code Checker (HCPCS/CPT)
==================================================================

Scans all code elements across the CCD for OTP-specific and SUD-related
billing codes. These are unambiguous signals — preferred over keyword
matching when present.

Codes checked:
  H0020    Methadone administration/dispensing
  S0109    Methadone, oral, dispensed
  H0015    Intensive outpatient treatment (SUD)
  H0005    Group counseling, substance use
  H0004    Individual counseling, substance use
  H0001    Alcohol/drug assessment
  G2067-G2078  Medicare OTP bundled payment codes
  99408/99409  SBIRT screening/intervention
  80305-80307  Drug testing (context-dependent, weak alone)

Returns:
    dict with:
        sud_billing_code_hit (bool) — True if any OTP/SUD billing code found
        sud_billing_code_count (int) — total billing code matches
        sud_billing_codes_found (str) — pipe-delimited codes found
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_pipeline_config import BILLING_CODES_EXACT, BILLING_CODES_PREFIXES


def check(root, ns):
    """
    Scan CCD for OTP/SUD billing codes.

    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict with sud_billing_code_hit, sud_billing_code_count, sud_billing_codes_found
    """
    found_codes = []
    findings = []  # human-readable: "Description [code] (Billing/Procedure Code)"

    # Scan every <code> element in the entire document
    for code_el in root.iter(f"{{{ns}}}code"):
        code_val = code_el.get("code", "").strip().upper()
        if not code_val:
            continue

        if _is_sud_billing_code(code_val):
            if code_val not in found_codes:
                found_codes.append(code_val)
                findings.append(_bill_finding(code_val, code_el.get("displayName", "")))

    # Also check <value> elements (some CCDs put procedure codes there)
    for value_el in root.iter(f"{{{ns}}}value"):
        code_val = value_el.get("code", "").strip().upper()
        if not code_val:
            continue

        if _is_sud_billing_code(code_val):
            if code_val not in found_codes:
                found_codes.append(code_val)
                findings.append(_bill_finding(code_val, value_el.get("displayName", "")))

    return {
        "sud_billing_code_hit": len(found_codes) > 0,
        "sud_billing_code_count": len(found_codes),
        "sud_billing_codes_found": "|".join(found_codes) if found_codes else "",
        "sud_billing_findings": findings,
    }


def _bill_finding(code, display_name):
    """Human-readable billing/procedure code finding."""
    desc = (display_name or "").strip() or "(no description)"
    return f"{desc} [{code}] (Billing/Procedure Code)"


def _is_sud_billing_code(code_val):
    """Check if a code matches our OTP/SUD billing code lists."""
    # Exact match
    if code_val in [c.upper() for c in BILLING_CODES_EXACT]:
        return True

    # Prefix match (for ranges like G2067-G2078, 80305-80307)
    for prefix in BILLING_CODES_PREFIXES:
        if code_val == prefix.upper() or code_val.startswith(prefix.upper()):
            return True

    return False


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import xml.etree.ElementTree as ET

    if len(sys.argv) < 2:
        print("Usage: python -m checkers.check_billing_codes <ccd_file.xml>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    result = check(root, ns)
    print(f"Billing code hit: {result['sud_billing_code_hit']}")
    print(f"Billing code count: {result['sud_billing_code_count']}")
    print(f"Codes found: {result['sud_billing_codes_found']}")
