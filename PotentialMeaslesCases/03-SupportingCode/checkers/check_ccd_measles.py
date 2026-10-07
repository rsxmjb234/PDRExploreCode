"""
check_ccd_measles.py — Measles Signal Checker for CCD (CDA XML) Documents
=============================================================================

Scans a parsed CCD's Problems and Encounter-Diagnosis sections for measles
signals, per GUIDANCE.md Section 5 ("CCD" row) and
measles-detection-technical-plan.md Section 4.

Matches (in order of strength, see config.py scoring constants):
  1. Coded diagnosis — ICD-10 B05.x, or a curated SNOMED measles concept ID.
  2. "Three C's" co-occurrence pattern in the problem/encounter display text
     (fever + cough/coryza/conjunctivitis + rash).
  3. A single bare measles-related keyword in display text, with neither of
     the above.

Mirrors the structure of 42CFRQualityCheck/checkers/check_diagnoses.py
(same encounter-vs-problem-list distinction, same ElementTree iteration
style) but looks for measles signals instead of SUD signals.

Returns:
    dict with:
        signal_count (int)
        strongest_tier (str) — "coded_diagnosis" | "three_cs" | "keyword" | ""
        findings (list of dict) — one per signal, each:
            {"signal_type", "signal_detail", "section"}
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ICD10_MEASLES_PREFIX, SNOMED_MEASLES_CODES, MEASLES_TEXT_KEYWORDS
from normalize import contains_any, find_matches
from three_cs_pattern import check_three_cs

_ICD10_PATTERN = re.compile(r"^" + re.escape(ICD10_MEASLES_PREFIX), re.IGNORECASE)
_SNOMED_SET = set(SNOMED_MEASLES_CODES)

_PROBLEMS_TEMPLATE_IDS = [
    "2.16.840.1.113883.10.20.22.2.5",
    "2.16.840.1.113883.10.20.22.2.5.1",
]


def check(root, ns):
    """
    Scan a CCD for measles signals.

    Args:
        root: ElementTree root of the CCD XML
        ns: CDA namespace string (e.g., "urn:hl7-org:v3")

    Returns:
        dict — see module docstring.
    """
    findings = []

    # ------------------------------------------------------------------
    # 1. Coded diagnoses — encounter diagnoses (entryRelationship under
    #    <encounter>) and the Problems section (ongoing problem list).
    # ------------------------------------------------------------------
    for entry in root.iter(f"{{{ns}}}encounter"):
        for er in entry.iter(f"{{{ns}}}entryRelationship"):
            for obs in er.iter(f"{{{ns}}}observation"):
                for value_el in obs.iter(f"{{{ns}}}value"):
                    code = value_el.get("code", "")
                    disp = value_el.get("displayName", "")
                    if _is_measles_code(code):
                        findings.append(_finding("coded_diagnosis", f"{disp} [{code}]",
                                                  "Encounter Diagnosis"))

    for section in root.iter(f"{{{ns}}}section"):
        if _is_problems_section(section, ns):
            for obs in section.iter(f"{{{ns}}}observation"):
                for value_el in obs.iter(f"{{{ns}}}value"):
                    code = value_el.get("code", "")
                    disp = value_el.get("displayName", "")
                    if _is_measles_code(code):
                        findings.append(_finding("coded_diagnosis", f"{disp} [{code}]",
                                                  "Problem List"))

    # ------------------------------------------------------------------
    # 2 & 3. Text scan — display text on problem/encounter observations,
    #    plus free-text section narrative where present. Covers the
    #    three-C's pattern and the bare-keyword fallback.
    # ------------------------------------------------------------------
    text_blobs = []
    for section in root.iter(f"{{{ns}}}section"):
        title_el = section.find(f"{{{ns}}}title")
        section_label = (title_el.text or "Section").strip() if title_el is not None and title_el.text else "Section"
        for obs in section.iter(f"{{{ns}}}observation"):
            for value_el in obs.iter(f"{{{ns}}}value"):
                disp = value_el.get("displayName", "")
                if disp:
                    text_blobs.append((disp, section_label))
        # Narrative text block (free text within the section, if present)
        text_el = section.find(f"{{{ns}}}text")
        if text_el is not None:
            narrative = "".join(text_el.itertext()).strip()
            if narrative:
                text_blobs.append((narrative, section_label))

    for text, section_label in text_blobs:
        three_cs = check_three_cs(text)
        if three_cs["matched"]:
            findings.append(_finding("three_cs_pattern",
                                      "fever + cough/coryza/conjunctivitis + rash", section_label))
            continue  # don't also double-count as a bare keyword hit

        hits = find_matches(text, MEASLES_TEXT_KEYWORDS)
        for kw in hits:
            findings.append(_finding("keyword", kw, section_label))

    strongest = _strongest_tier(findings)

    return {
        "signal_count": len(findings),
        "strongest_tier": strongest,
        "findings": findings,
    }


def _is_measles_code(code):
    if not code:
        return False
    if _ICD10_PATTERN.match(code):
        return True
    if code in _SNOMED_SET:
        return True
    return False


def _is_problems_section(section, ns):
    for tmpl in section.iter(f"{{{ns}}}templateId"):
        if tmpl.get("root", "") in _PROBLEMS_TEMPLATE_IDS:
            return True
    return False


def _finding(signal_type, signal_detail, section):
    return {"signal_type": signal_type, "signal_detail": signal_detail, "section": section}


def _strongest_tier(findings):
    types = {f["signal_type"] for f in findings}
    if "coded_diagnosis" in types:
        return "coded_diagnosis"
    if "three_cs_pattern" in types:
        return "three_cs"
    if "keyword" in types:
        return "keyword"
    return ""


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import sys
    import xml.etree.ElementTree as ET

    if len(sys.argv) < 2:
        print("Usage: python -m checkers.check_ccd_measles <ccd_file.xml>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    result = check(root, ns)
    print(f"Signal count: {result['signal_count']}")
    print(f"Strongest tier: {result['strongest_tier']}")
    for f in result["findings"]:
        print(f"  {f}")
