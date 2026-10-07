"""
normalize.py — Shared normalization helpers (patient key + text matching)
=============================================================================

Same normalization approach already proven out in
ADTScanForCandidates/03-SupportingCode/load_lookup.py (normalize_aa /
normalize_mrn) — reused here rather than re-invented, per
measles-detection-technical-plan.md Section 6, so a patient identified from
a CCD, an ADT, and a TRN all resolve to the same aggregation key.
"""


def normalize_aa(value):
    """Normalize an assigning-authority string for comparison."""
    v = (value or "").strip()
    return v.upper()


def normalize_mrn(value):
    """Normalize an MRN string for comparison."""
    v = (value or "").strip()
    return v.upper()


def patient_key(assigning_authority, mrn):
    """Build the normalized (aa, mrn) tuple used as the per-patient rollup key."""
    return (normalize_aa(assigning_authority), normalize_mrn(mrn))


def contains_any(text, keywords):
    """Case-insensitive substring check: True if ANY keyword appears in text."""
    if not text:
        return False
    low = text.lower()
    return any(kw.lower() in low for kw in keywords)


def find_matches(text, keywords):
    """Return the list of keywords (from `keywords`) that appear in `text`,
    case-insensitive. Empty list if text is empty or nothing matches."""
    if not text:
        return []
    low = text.lower()
    return [kw for kw in keywords if kw.lower() in low]
