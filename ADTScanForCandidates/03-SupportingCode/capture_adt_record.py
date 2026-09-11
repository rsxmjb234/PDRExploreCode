"""
capture_adt_record.py — Build tracking-database records from a parsed ADT
============================================================================

See 01-RequirementsAndPlans/adt-tracking-database-requirement.md.

We already download and parse every ADT file to check for known AA|MRN
matches. Since that work is already done, this module captures one tracking
record per patient identifier (PID-3) found, in EVERY successfully parsed
file — not just files that matched a known candidate.

v1 schema (final schema pending): date/time, assigning_authority, mrn.

This is deliberately isolated in its own function so that when the real
tracking-database schema arrives, only build_records() needs to change —
the scan/restart/parallelism logic in scan_bucket.py is untouched.
"""


def build_records(messages):
    """
    Build v1 tracking records from the messages returned by parse_adt.parse().

    Args:
        messages: list of dicts as returned by parse_adt.parse(), each with
                  "message_time" and "identifiers" (list of {"id", "aa", ...}).

    Returns:
        list of flat dicts, one per PID-3 identifier found across all
        messages in the file:
            {"adt_date_time": ..., "assigning_authority": ..., "mrn": ...}
    """
    records = []
    for msg in messages:
        message_time = msg.get("message_time", "")
        for ident in msg.get("identifiers", []):
            records.append({
                "adt_date_time": message_time,
                "assigning_authority": ident.get("aa", ""),
                "mrn": ident.get("id", ""),
            })
    return records


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    sample_messages = [
        {
            "message_type": "ADT^A03",
            "message_time": "20260115120000",
            "identifiers": [
                {"id": "12345", "aa": "HEALTHIX", "raw_pid3": "12345^^^HEALTHIX^MR"},
            ],
        }
    ]
    for r in build_records(sample_messages):
        print(r)
