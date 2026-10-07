"""
check_trn_measles.py — Measles Signal Checker for TRN (HL7v2) Messages
=============================================================================

SCOPE FOR THIS PASS (explicit user instruction): TRN is FREE TEXT ONLY.
TRN carries unstructured discharge-summary/transition-note narrative
content and its message type varies (see parse_hl7.py docstring) — PDR has
no confirmed, reliable coded-diagnosis field on this feed yet. So, for now,
this checker does NOT look at DG1 or any other coded field, even though
parse_hl7.py may still capture one if present. It scans only the narrative
text extracted from OBX-5 / NTE-3, per GUIDANCE.md Section 5 ("TRN" row):
narrative mentions of measles, rubeola, Koplik spots, maculopapular rash
with fever and coryza/conjunctivitis.

ADT is OUT OF SCOPE for this pass entirely (explicit user instruction) —
there is no check_adt_measles.py right now.

Same signal tiers and finding shape as check_ccd_measles.py.

Returns: dict — see check_ccd_measles.py docstring (same shape), minus the
"coded_diagnosis" tier, which this checker never produces.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MEASLES_TEXT_KEYWORDS
from normalize import find_matches
from three_cs_pattern import check_three_cs


def check(message):
    """
    Scan one parsed TRN message (a dict from parse_hl7.parse()) for measles
    signals in its FREE TEXT narrative only (see module docstring for why
    coded fields are intentionally skipped in this pass).

    Args:
        message: dict — one element of the list returned by parse_hl7.parse()

    Returns:
        dict — signal_count, strongest_tier, findings.
    """
    findings = []

    narrative = " ".join(message.get("narrative_lines", []))
    if narrative:
        three_cs = check_three_cs(narrative)
        if three_cs["matched"]:
            findings.append(_finding("three_cs_pattern",
                                      "fever + cough/coryza/conjunctivitis + rash",
                                      "Discharge/Transition Note Narrative"))
        else:
            for kw in find_matches(narrative, MEASLES_TEXT_KEYWORDS):
                findings.append(_finding("keyword", kw, "Discharge/Transition Note Narrative"))

    strongest = _strongest_tier(findings)

    return {
        "signal_count": len(findings),
        "strongest_tier": strongest,
        "findings": findings,
    }


def _finding(signal_type, signal_detail, section):
    return {"signal_type": signal_type, "signal_detail": signal_detail, "section": section}


def _strongest_tier(findings):
    types = {f["signal_type"] for f in findings}
    if "three_cs_pattern" in types:
        return "three_cs"
    if "keyword" in types:
        return "keyword"
    return ""


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import sys as _sys
    _sys.path.insert(0, "..")
    import parse_hl7

    if len(_sys.argv) < 2:
        print("Usage: python -m checkers.check_trn_measles <trn_file.hl7>")
        _sys.exit(1)

    with open(_sys.argv[1], "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    for msg in parse_hl7.parse(text):
        result = check(msg)
        print(f"Signal count: {result['signal_count']}  strongest={result['strongest_tier']}")
        for finding in result["findings"]:
            print(f"  {finding}")
