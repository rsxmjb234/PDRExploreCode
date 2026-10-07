"""
three_cs_pattern.py — Shared "Fever + Three C's + Rash" Co-Occurrence Check
=============================================================================

Classic measles presentation (GUIDANCE.md Section 5): fever, followed by the
"three C's" (cough, coryza, conjunctivitis), followed by a maculopapular
rash, sometimes with Koplik spots. A COMBINATION across these within the
same note/section is a stronger hint than any single keyword match alone.

This is deliberately crude substring co-occurrence matching, not NLP —
consistent with GUIDANCE.md's explicit framing that this whole exploration
is "pattern-matching, not a validated clinical score." Shared by
check_ccd_measles.py, check_adt_measles.py, and check_trn_measles.py so the
rule is defined once, not three times with potential drift between them.
"""

from normalize import contains_any
from config import (
    THREE_CS_FEVER_KEYWORDS,
    THREE_CS_COUGH_CORYZA_CONJUNCTIVITIS_KEYWORDS,
    THREE_CS_RASH_KEYWORDS,
)


def check_three_cs(text):
    """
    Check a block of text (problem/encounter display text, chief complaint,
    or narrative note) for the fever + three-C's + rash co-occurrence
    pattern.

    Args:
        text: str — the text to scan. May be None/empty.

    Returns:
        dict:
            matched (bool) — True if fever AND (cough/coryza/conjunctivitis)
                AND rash all appear somewhere in this text.
            fever_hit (bool), three_cs_hit (bool), rash_hit (bool) — which
                parts matched, so a caller can still log a partial hit.
    """
    fever_hit = contains_any(text, THREE_CS_FEVER_KEYWORDS)
    three_cs_hit = contains_any(text, THREE_CS_COUGH_CORYZA_CONJUNCTIVITIS_KEYWORDS)
    rash_hit = contains_any(text, THREE_CS_RASH_KEYWORDS)

    return {
        "matched": fever_hit and three_cs_hit and rash_hit,
        "fever_hit": fever_hit,
        "three_cs_hit": three_cs_hit,
        "rash_hit": rash_hit,
    }


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    samples = [
        "Patient presents with fever, cough, and a maculopapular rash on trunk.",
        "Fever and sore throat, no rash noted.",
        "Rash on arms, no fever documented.",
        "",
    ]
    for s in samples:
        result = check_three_cs(s)
        print(f"{result['matched']!s:5}  {s!r}")
