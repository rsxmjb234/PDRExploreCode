"""
load_lookup.py — Load the known AA|MRN list into a fast in-memory set
======================================================================

Reads the ~35,000-row lookup CSV (assigning authority + MRN per row) and
builds a normalized set of (assigning_authority, mrn) keys for O(1) matching.

Normalization is applied here the SAME way it will be applied to values
parsed out of ADT files (see normalize() — shared by parse/match), so a match
is not missed due to case or whitespace differences.
"""

import csv
import os

from config import (
    LOOKUP_AA_COLUMNS,
    LOOKUP_MRN_COLUMNS,
    NORMALIZE_UPPERCASE,
    NORMALIZE_STRIP,
    NORMALIZE_STRIP_LEADING_ZEROS_ON_MRN,
)


def normalize_aa(value):
    """Normalize an assigning-authority string for comparison."""
    v = value or ""
    if NORMALIZE_STRIP:
        v = v.strip()
    if NORMALIZE_UPPERCASE:
        v = v.upper()
    return v


def normalize_mrn(value):
    """Normalize an MRN string for comparison."""
    v = value or ""
    if NORMALIZE_STRIP:
        v = v.strip()
    if NORMALIZE_UPPERCASE:
        v = v.upper()
    if NORMALIZE_STRIP_LEADING_ZEROS_ON_MRN:
        v = v.lstrip("0") or "0"
    return v


def make_key(aa, mrn):
    """Build the normalized (aa, mrn) tuple used as the lookup key."""
    return (normalize_aa(aa), normalize_mrn(mrn))


def _pick_column(fieldnames, candidates):
    """Return the actual header matching one of candidates (case-insensitive)."""
    lower_map = {fn.lower().strip(): fn for fn in fieldnames}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def load_lookup(lookup_csv):
    """
    Load the AA|MRN lookup CSV into a set of normalized (aa, mrn) keys.

    Returns:
        (lookup_set, stats) where
          lookup_set: set of (normalized_aa, normalized_mrn)
          stats: dict with counts (rows_read, pairs_loaded, skipped)
    """
    if not os.path.isfile(lookup_csv):
        raise FileNotFoundError(
            f"Lookup CSV not found: {os.path.abspath(lookup_csv)}\n"
            f"Place the ~35k AA|MRN file there (see config LOOKUP path)."
        )

    lookup_set = set()
    rows_read = 0
    skipped = 0

    with open(lookup_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"Lookup CSV has no header row: {lookup_csv}")

        aa_col = _pick_column(reader.fieldnames, LOOKUP_AA_COLUMNS)
        mrn_col = _pick_column(reader.fieldnames, LOOKUP_MRN_COLUMNS)

        if not aa_col or not mrn_col:
            raise ValueError(
                "Could not find AA and/or MRN columns in the lookup CSV.\n"
                f"  Headers present: {reader.fieldnames}\n"
                f"  Looking for AA in {LOOKUP_AA_COLUMNS}\n"
                f"  Looking for MRN in {LOOKUP_MRN_COLUMNS}\n"
                "  Update LOOKUP_AA_COLUMNS / LOOKUP_MRN_COLUMNS in config.py."
            )

        for row in reader:
            rows_read += 1
            aa = row.get(aa_col, "")
            mrn = row.get(mrn_col, "")
            if not (aa and aa.strip()) or not (mrn and mrn.strip()):
                skipped += 1
                continue
            lookup_set.add(make_key(aa, mrn))

    stats = {
        "rows_read": rows_read,
        "pairs_loaded": len(lookup_set),
        "skipped": skipped,
        "aa_column": aa_col,
        "mrn_column": mrn_col,
    }
    return lookup_set, stats


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import sys
    from config import get_config

    cfg = get_config()
    path = sys.argv[1] if len(sys.argv) > 1 else cfg["lookup_csv"]
    # Resolve relative to this script's folder like the pipeline does
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    s, stats = load_lookup(path)
    print(f"Loaded lookup from: {path}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  sample keys: {list(s)[:5]}")
