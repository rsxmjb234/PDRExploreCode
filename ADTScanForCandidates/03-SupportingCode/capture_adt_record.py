"""
capture_adt_record.py — Build tracking-database records from a parsed ADT
============================================================================

See 01-RequirementsAndPlans/adt-tracking-database-requirement.md (v2).

We already download and parse every ADT file to check for known AA|MRN
matches. Since that parse already extracts everything below, this module
just reshapes it into the operational tracking-database extract — one row
per ADT MESSAGE (not per PID-3 identifier; the target schema is
encounter-level: transaction_id, encounter_id, admit/discharge dates,
diagnoses).

Columns mirror NYEC_EG_Operational_Database_Schema.csv, in schema order,
with:
  - lookup/crosswalk-dependent columns OMITTED (alert_type, source_qe_mpid,
    target_qe_id, target_qe_mpid, discharge_disposition_text) — see the
    requirement doc's "Columns skipped" section for why each one is skipped.
  - one extra column appended at the END, not part of the operational
    schema: found_in_missing_mrn_list (yes/no) — whether this message's MRN
    matches one of the ~35,000 known AA|MRN pairs.

This is deliberately isolated in its own function so that if the schema
changes again, only this mapping needs to change — the scan/restart/
parallelism logic in scan_bucket.py is untouched.
"""

# Column order for the CSV — single source of truth used both when writing
# the header and when writing each row.
TRACKING_COLUMNS = [
    "transaction_id",
    "message_datetime",
    "facility_oid",
    "facility_name",
    "facility_part2_flag",
    "facility_OMH_flag",
    "facility_OPWDD_flag",
    "source_qe_id",
    "facility_mrn",
    "patient_last_name",
    "patient_first_name",
    "patient_dob",
    "admit_date",
    "discharge_date",
    "encounter_id",
    "account_number",
    "chief_complaint",
    "discharge_disposition_code",
    "diagnosis_code",
    "diagnosis_code_system",
    "diagnosis_code_type",
    # Not part of the operational schema — appended at the end per request.
    "found_in_missing_mrn_list",
]


def _make_transaction_id(message_datetime, facility_oid, encounter_id):
    """
    Schema says only "unique ID composed of concatenated ADT values, no PHI."
    Proposed rule (open assumption — see requirement doc): concatenate
    message_datetime + facility_oid + encounter_id. None of these three are
    PHI on their own. Falls back gracefully if any piece is blank.
    """
    parts = [p for p in (message_datetime, facility_oid, encounter_id) if p]
    return "-".join(parts)


def build_records(messages, lookup_set=None):
    """
    Build v2 tracking records from the messages returned by parse_adt.parse().

    Args:
        messages: list of dicts as returned by parse_adt.parse().
        lookup_set: optional set of normalized (aa, mrn) tuples — the known
            AA|MRN pairs. If provided, used to set found_in_missing_mrn_list.
            If omitted, that column is always "no" (caller didn't ask for
            matching, e.g. a standalone/manual run).

    Returns:
        list of flat dicts (keys = TRACKING_COLUMNS), one per ADT message.
        Where a message has multiple DG1 segments, diagnosis_code /
        diagnosis_code_system / diagnosis_code_type are pipe-delimited,
        aligned by position. Where PID-3 repeats, facility_mrn uses the
        FIRST repeat only (the schema has a single MRN column, not a list).
    """
    if lookup_set is None:
        lookup_set = set()

    records = []
    for msg in messages:
        identifiers = msg.get("identifiers", [])
        first_ident = identifiers[0] if identifiers else {"id": "", "aa": ""}
        facility_mrn = first_ident.get("id", "")

        # Match against the known AA|MRN list using ALL identifiers in the
        # message (not just the first) — a message could carry the matching
        # identifier in a later PID-3 repeat even if the first one isn't it.
        matched = any((ident.get("aa", ""), ident.get("id", "")) in lookup_set
                       for ident in identifiers)

        diagnoses = msg.get("diagnoses", [])
        diagnosis_code = "|".join(d.get("diagnosis_code", "") for d in diagnoses)
        diagnosis_code_system = "|".join(d.get("diagnosis_code_system", "") for d in diagnoses)
        diagnosis_code_type = "|".join(d.get("diagnosis_code_type", "") for d in diagnoses)

        message_datetime = msg.get("message_time", "")
        facility_oid = msg.get("facility_oid", "")
        encounter_id = msg.get("encounter_id", "")

        # PV1-39 is the SAME source field for all three flag columns per the
        # operational schema (facility_part2_flag / facility_OMH_flag /
        # facility_OPWDD_flag all map to PV1-39) — captured as-is, flagged
        # as a possible schema ambiguity in the requirement doc.
        pv1_39 = msg.get("pv1_39_flag", "")

        records.append({
            "transaction_id": _make_transaction_id(message_datetime, facility_oid, encounter_id),
            "message_datetime": message_datetime,
            "facility_oid": facility_oid,
            "facility_name": msg.get("facility_name", ""),
            "facility_part2_flag": pv1_39,
            "facility_OMH_flag": pv1_39,
            "facility_OPWDD_flag": pv1_39,
            "source_qe_id": msg.get("source_qe_id", ""),
            "facility_mrn": facility_mrn,
            "patient_last_name": msg.get("patient_last_name", ""),
            "patient_first_name": msg.get("patient_first_name", ""),
            "patient_dob": msg.get("patient_dob", ""),
            "admit_date": msg.get("admit_date", ""),
            "discharge_date": msg.get("discharge_date", ""),
            "encounter_id": encounter_id,
            "account_number": msg.get("account_number", ""),
            "chief_complaint": msg.get("chief_complaint", ""),
            "discharge_disposition_code": msg.get("discharge_disposition_code", ""),
            "diagnosis_code": diagnosis_code,
            "diagnosis_code_system": diagnosis_code_system,
            "diagnosis_code_type": diagnosis_code_type,
            "found_in_missing_mrn_list": "yes" if matched else "no",
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
            "facility_oid": "2.16.840.1.113883.3.999",
            "facility_name": "SAMPLE HOSPITAL",
            "source_qe_id": "HEALTHIX",
            "identifiers": [
                {"id": "12345", "aa": "HEALTHIX", "raw_pid3": "12345^^^HEALTHIX^MR"},
            ],
            "patient_last_name": "DOE",
            "patient_first_name": "JANE",
            "patient_dob": "19800101",
            "account_number": "ACCT1",
            "encounter_id": "ENC1",
            "discharge_disposition_code": "01",
            "pv1_39_flag": "Y",
            "admit_date": "20260110080000",
            "discharge_date": "20260115120000",
            "chief_complaint": "Chest pain",
            "diagnoses": [
                {"diagnosis_code": "R07.9", "diagnosis_code_system": "ICD-10", "diagnosis_code_type": "F"},
            ],
        }
    ]
    lookup = {("HEALTHIX", "12345")}
    for r in build_records(sample_messages, lookup_set=lookup):
        for col in TRACKING_COLUMNS:
            print(f"  {col}: {r[col]}")
