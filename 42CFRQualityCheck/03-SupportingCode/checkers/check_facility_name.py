"""
check_facility_name.py — Custodian Organization Name Keyword Checker
=====================================================================

Checks the custodian organization name against a list of SUD-related
keywords (recovery, addiction, substance, methadone, etc.).

IMPORTANT: This is used for PRIORITIZATION, not as an additive flag.
A generic-named facility with high SUD prevalence is the priority case.
An obviously-named facility is a confirmation case.

The key output is `facility_name_is_generic` — True when the facility
name does NOT match any SUD keywords (meaning it looks like ordinary care).

Returns:
    dict with:
        facility_name_flags (str) — pipe-delimited keywords that matched
        facility_name_is_generic (bool) — True if NO keywords match
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_pipeline_config import FACILITY_SUD_KEYWORDS


def check(custodian_org_name):
    """
    Check custodian org name for SUD-related keywords.

    Args:
        custodian_org_name: string (already extracted from CCD)

    Returns:
        dict with facility_name_flags, facility_name_is_generic
    """
    if not custodian_org_name:
        return {
            "facility_name_flags": "",
            "facility_name_is_generic": True,
        }

    name_lower = custodian_org_name.lower()
    matched_keywords = []

    for keyword in FACILITY_SUD_KEYWORDS:
        if keyword in name_lower:
            matched_keywords.append(keyword)

    return {
        "facility_name_flags": "|".join(matched_keywords) if matched_keywords else "",
        "facility_name_is_generic": len(matched_keywords) == 0,
    }


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m checkers.check_facility_name \"Facility Name Here\"")
        sys.exit(1)

    name = " ".join(sys.argv[1:])
    result = check(name)
    print(f"Facility name: {name}")
    print(f"Keyword flags: {result['facility_name_flags']}")
    print(f"Is generic (no SUD keywords): {result['facility_name_is_generic']}")
