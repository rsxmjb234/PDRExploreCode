"""
segment_mapping.py — What code system is expected for each CCD section?

Simple concept: each clinical section has a short list of "good" code systems.
If the entry's code references one of these, it's nationally coded (Standard).
If not, it's local/proprietary.

We only check CLINICAL ENTRY codes — not structural CDA wrappers.
"""

# =============================================================================
# SECTION DEFINITIONS
# =============================================================================
# Each section defines:
#   - How to find it (LOINC section code)
#   - What entry elements to check for codes
#   - What code systems count as "national standard"

SECTIONS = {
    "medications": {
        "loinc": "10160-0",
        "display": "Medications",
        "entry_xpath": ".//substanceAdministration",
        "code_path": ".//manufacturedMaterial/code",
        "accepted": {
            "2.16.840.1.113883.6.88": "RxNorm",
            "2.16.840.1.113883.6.69": "NDC",
        },
    },
    "labs_results": {
        "loinc": "30954-2",
        "display": "Labs / Diagnostic Results",
        "entry_xpath": ".//observation",
        "code_path": "code",
        "accepted": {
            "2.16.840.1.113883.6.1": "LOINC",
        },
    },
    "problems": {
        "loinc": "11450-4",
        "display": "Problems",
        "entry_xpath": ".//observation",
        "code_path": "value",  # Problems use <value> for the diagnosis code
        "accepted": {
            "2.16.840.1.113883.6.96": "SNOMED-CT",
            "2.16.840.1.113883.6.90": "ICD-10-CM",
            "2.16.840.1.113883.6.103": "ICD-9-CM",
        },
    },
    "procedures": {
        "loinc": "47519-4",
        "display": "Procedures",
        "entry_xpath": ".//procedure",
        "code_path": "code",
        "accepted": {
            "2.16.840.1.113883.6.96": "SNOMED-CT",
            "2.16.840.1.113883.6.12": "CPT-4",
            "2.16.840.1.113883.6.4": "ICD-10-PCS",
            "2.16.840.1.113883.6.285": "HCPCS",
        },
    },
    "immunizations": {
        "loinc": "11369-6",
        "display": "Immunizations",
        "entry_xpath": ".//substanceAdministration",
        "code_path": ".//manufacturedMaterial/code",
        "accepted": {
            "2.16.840.1.113883.12.292": "CVX",
        },
    },
    "vitals": {
        "loinc": "8716-3",
        "display": "Vital Signs",
        "entry_xpath": ".//observation",
        "code_path": "code",
        "accepted": {
            "2.16.840.1.113883.6.1": "LOINC",
        },
    },
    "allergies": {
        "loinc": "48765-2",
        "display": "Allergies",
        "entry_xpath": ".//observation",
        "code_path": "value",  # Allergen is in <value>
        "accepted": {
            "2.16.840.1.113883.6.88": "RxNorm",
            "2.16.840.1.113883.6.96": "SNOMED-CT",
            "2.16.840.1.113883.4.9": "UNII",
        },
    },
    "encounters": {
        "loinc": "46240-8",
        "display": "Encounters",
        "entry_xpath": ".//encounter",
        "code_path": "code",
        "accepted": {
            "2.16.840.1.113883.6.96": "SNOMED-CT",
            "2.16.840.1.113883.6.12": "CPT-4",
        },
    },
    "social_history": {
        "loinc": "29762-2",
        "display": "Social History",
        "entry_xpath": ".//observation",
        "code_path": "code",
        "accepted": {
            "2.16.840.1.113883.6.96": "SNOMED-CT",
            "2.16.840.1.113883.6.1": "LOINC",
        },
    },
    "care_plan": {
        "loinc": "18776-5",
        "display": "Plan of Care",
        "entry_xpath": ".//act",
        "code_path": "code",
        "accepted": {
            "2.16.840.1.113883.6.96": "SNOMED-CT",
            "2.16.840.1.113883.6.12": "CPT-4",
        },
    },
    "functional_status": {
        "loinc": "47420-5",
        "display": "Functional Status",
        "entry_xpath": ".//observation",
        "code_path": "code",
        "accepted": {
            "2.16.840.1.113883.6.96": "SNOMED-CT",
            "2.16.840.1.113883.6.1": "LOINC",
        },
    },
    "demographics": {
        "loinc": None,  # Not a section — it's in the CDA header
        "display": "Demographics",
        "entry_xpath": None,
        "code_path": None,
        "accepted": {
            "2.16.840.1.113883.6.238": "CDC CDCREC",
            "2.16.840.1.113883.5.1": "HL7 AdminGender",
        },
    },
}

# Stable list of all section keys
ALL_SEGMENT_KEYS = list(SECTIONS.keys())

# Lookup by LOINC code
SECTIONS_BY_LOINC = {
    sec["loinc"]: key
    for key, sec in SECTIONS.items()
    if sec["loinc"] is not None
}


if __name__ == "__main__":
    print(f"Segment Mapping: {len(SECTIONS)} sections defined")
    print()
    for key, sec in SECTIONS.items():
        systems = ", ".join(sec["accepted"].values())
        print(f"  {key:<20} Expected: {systems}")
