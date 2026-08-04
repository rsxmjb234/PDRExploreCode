"""
segment_mapping.py — Segment-to-Section Mapping Table for CCD Coding Quality

This module defines the 14 target segments, how to find them in a CCD XML document,
and which code systems are considered "national standard" for each segment.

Used by:
  - The test-case generator (to know which sections to mutate)
  - The core scoring pipeline (to classify coded elements)

The 14 segments cover EVERY CCD section we evaluate. If a CCD has a section
not in this list, we ignore it. If a CCD is missing a section from this list,
we mark it as "section_absent".
"""


# =============================================================================
# SEGMENT DEFINITIONS
# =============================================================================
# Each segment has:
#   - segment_key: stable identifier used in JSON output and domain_counts
#   - display_name: human-readable name for reports
#   - loinc_code: the LOINC section code that identifies this section in the CCD
#   - template_ids: CDA templateId OIDs for this section (may have multiple)
#   - location: where in the CCD XML to find this data
#   - accepted_code_systems: OIDs that count as "national standard" for this domain
#   - notes: any special handling required

SEGMENT_DEFINITIONS = [
    {
        "segment_key": "allergies",
        "display_name": "Allergies",
        "loinc_code": "48765-2",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.6.1"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.88":  "RxNorm",       # Substance (allergen)
            "2.16.840.1.113883.6.96":  "SNOMED-CT",    # Reaction type
            "2.16.840.1.113883.4.9":   "UNII",         # Substance identifier
        },
        "notes": "Primary code on substance; reaction coded separately",
    },
    {
        "segment_key": "assessment",
        "display_name": "Assessment",
        "loinc_code": "51848-0",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.8"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.96":  "SNOMED-CT",
            "2.16.840.1.113883.6.90":  "ICD-10-CM",
        },
        "notes": "Not present in Synthea; may be absent in many real CCDs",
    },
    {
        "segment_key": "care_plan",
        "display_name": "Plan of Care",
        "loinc_code": "18776-5",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.10"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.96":  "SNOMED-CT",
            "2.16.840.1.113883.6.12":  "CPT-4",
            "2.16.840.1.113883.6.285": "HCPCS",
        },
        "notes": "Often contains planned procedures/goals",
    },
    {
        "segment_key": "chief_complaint",
        "display_name": "Chief Complaint",
        "loinc_code": "10154-3",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.13"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.96":  "SNOMED-CT",
            "2.16.840.1.113883.6.90":  "ICD-10-CM",
        },
        "notes": "Not present in Synthea; often free-text only in real CCDs",
    },
    {
        "segment_key": "demographics",
        "display_name": "Demographics",
        "loinc_code": None,  # Not a section — lives in recordTarget/patientRole/patient
        "template_ids": [],
        "location": "recordTarget",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.238": "CDCREC",        # Race and Ethnicity
            "2.16.840.1.113883.5.1":   "HL7 AdminGender",
            "2.16.840.1.113883.5.2":   "HL7 MaritalStatus",
            "2.16.840.1.113883.6.11":  "HL7 Language",  # ISO 639
        },
        "notes": "Not a CDA section; coded elements in patient header (race, ethnicity, gender, language)",
    },
    {
        "segment_key": "encounters",
        "display_name": "Encounters",
        "loinc_code": "46240-8",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.22"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.96":  "SNOMED-CT",
            "2.16.840.1.113883.6.12":  "CPT-4",
            "2.16.840.1.113883.6.90":  "ICD-10-CM",
        },
        "notes": "Encounter type and diagnosis codes",
    },
    {
        "segment_key": "functional_status",
        "display_name": "Functional Status",
        "loinc_code": "47420-5",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.14"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.96":  "SNOMED-CT",
            "2.16.840.1.113883.6.1":   "LOINC",
        },
        "notes": "Functional assessments and disability codes",
    },
    {
        "segment_key": "immunizations",
        "display_name": "Immunizations",
        "loinc_code": "11369-6",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.2"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.12.292": "CVX",           # Vaccine administered
            "2.16.840.1.113883.12.227": "MVX",           # Vaccine manufacturer
        },
        "notes": "CVX is the primary standard for vaccine codes",
    },
    {
        "segment_key": "labs_results",
        "display_name": "Labs / Diagnostic Results",
        "loinc_code": "30954-2",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.3.1"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.1":   "LOINC",         # Test code
            "2.16.840.1.113883.6.8":   "UCUM",          # Units
        },
        "notes": "LOINC for test identity; UCUM for units of measure",
    },
    {
        "segment_key": "medications",
        "display_name": "Medications",
        "loinc_code": "10160-0",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.1.1"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.88":  "RxNorm",        # Drug code
            "2.16.840.1.113883.6.69":  "NDC",           # National Drug Code
        },
        "notes": "RxNorm preferred; NDC also accepted",
    },
    {
        "segment_key": "problems",
        "display_name": "Problems",
        "loinc_code": "11450-4",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.5.1"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.96":  "SNOMED-CT",
            "2.16.840.1.113883.6.90":  "ICD-10-CM",
            "2.16.840.1.113883.6.103": "ICD-9-CM",      # Legacy but recognized
        },
        "notes": "SNOMED-CT or ICD-10 for diagnosis; ICD-9 accepted as legacy",
    },
    {
        "segment_key": "procedures",
        "display_name": "Procedures",
        "loinc_code": "47519-4",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.7.1"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.96":  "SNOMED-CT",
            "2.16.840.1.113883.6.12":  "CPT-4",
            "2.16.840.1.113883.6.4":   "ICD-10-PCS",
            "2.16.840.1.113883.6.285": "HCPCS",
        },
        "notes": "Multiple standard systems accepted for procedures",
    },
    {
        "segment_key": "social_history",
        "display_name": "Social History",
        "loinc_code": "29762-2",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.17"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.96":  "SNOMED-CT",
            "2.16.840.1.113883.6.1":   "LOINC",
        },
        "notes": "Smoking status, alcohol use, etc.",
    },
    {
        "segment_key": "vitals",
        "display_name": "Vital Signs",
        "loinc_code": "8716-3",
        "template_ids": ["2.16.840.1.113883.10.20.22.2.4.1"],
        "location": "section",
        "accepted_code_systems": {
            "2.16.840.1.113883.6.1":   "LOINC",         # Vital sign type
            "2.16.840.1.113883.6.8":   "UCUM",          # Units
        },
        "notes": "LOINC for observation identity; UCUM for units",
    },
]


# =============================================================================
# QUICK LOOKUP HELPERS
# =============================================================================

# Dict keyed by segment_key for fast lookup
SEGMENTS_BY_KEY = {seg["segment_key"]: seg for seg in SEGMENT_DEFINITIONS}

# Dict keyed by LOINC code for section identification
SEGMENTS_BY_LOINC = {
    seg["loinc_code"]: seg
    for seg in SEGMENT_DEFINITIONS
    if seg["loinc_code"] is not None
}

# All 14 segment keys in stable order
ALL_SEGMENT_KEYS = [seg["segment_key"] for seg in SEGMENT_DEFINITIONS]

# Master set of all accepted national code system OIDs (across all domains)
ALL_NATIONAL_CODE_SYSTEMS = set()
for seg in SEGMENT_DEFINITIONS:
    ALL_NATIONAL_CODE_SYSTEMS.update(seg["accepted_code_systems"].keys())


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_national_standard(code_system_oid, segment_key=None):
    """
    Check if a codeSystem OID is a recognized national standard.
    
    If segment_key is provided, checks against that specific segment's
    accepted systems. Otherwise checks against the global set.
    
    Args:
        code_system_oid (str): The OID to check
        segment_key (str, optional): Limit check to this segment's standards
    
    Returns:
        bool: True if the OID is a recognized national code system
    """
    if not code_system_oid:
        return False
    
    if segment_key and segment_key in SEGMENTS_BY_KEY:
        return code_system_oid in SEGMENTS_BY_KEY[segment_key]["accepted_code_systems"]
    
    return code_system_oid in ALL_NATIONAL_CODE_SYSTEMS


def get_segment_for_loinc(loinc_code):
    """
    Given a LOINC section code, return the segment definition (or None).
    
    Args:
        loinc_code (str): LOINC code from a CDA section/code element
    
    Returns:
        dict or None: The segment definition if found
    """
    return SEGMENTS_BY_LOINC.get(loinc_code)


# =============================================================================
# PRINT SUMMARY (for debugging)
# =============================================================================

if __name__ == "__main__":
    print(f"Segment Mapping Table: {len(SEGMENT_DEFINITIONS)} segments defined")
    print()
    print(f"{'Segment Key':<20} {'LOINC':<10} {'Location':<15} {'Accepted Code Systems'}")
    print("-" * 90)
    for seg in SEGMENT_DEFINITIONS:
        loinc = seg["loinc_code"] or "(header)"
        systems = ", ".join(seg["accepted_code_systems"].values())
        print(f"{seg['segment_key']:<20} {loinc:<10} {seg['location']:<15} {systems}")
    
    print()
    print(f"Total national code system OIDs recognized: {len(ALL_NATIONAL_CODE_SYSTEMS)}")
