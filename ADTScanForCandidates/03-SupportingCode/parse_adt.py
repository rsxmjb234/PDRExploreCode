"""
parse_adt.py — HL7v2 ADT parser
=================================

Parses raw HL7v2 text and returns, per message, the fields needed for:
  1) matching against the ~35,000 known AA|MRN pairs (PID-3), and
  2) the operational tracking-database extract (Output D — see
     01-RequirementsAndPlans/adt-tracking-database-requirement.md), which
     mirrors NYEC_EG_Operational_Database_Schema.csv.

HL7v2 field separator is "|". Component separator is "^". Repetition
separator (used in PID-3) is "~".

Field indexing note: for MSH, the segment name itself ("MSH") occupies
index 0 and MSH-1 (the field separator character) is consumed by the split,
so fields[1] = MSH-2, fields[2] = MSH-3, ... fields[8] = MSH-9. For every
other segment, fields[N] = <segment>-N directly (fields[0] is the segment
name).

Segments read:
  MSH-4  (facility OID, component 2)      -> facility_oid
  MSH-5  (source QE id)                   -> source_qe_id (primary)
  MSH-6  (source QE id, TechBD fallback)  -> source_qe_id (fallback if MSH-5 blank)
  MSH-7  (message timestamp)              -> message_time
  MSH-9  (message type)                   -> message_type
  EVN-7  (facility name, component 1)     -> facility_name
  PID-3  (patient identifier list)        -> identifiers (id + assigning authority)
  PID-5  (patient name: last^first)       -> patient_last_name / patient_first_name
  PID-7  (date of birth)                  -> patient_dob
  PID-18 (account number)                 -> account_number
  PV1-19 (visit/encounter number)         -> encounter_id
  PV1-36 (discharge disposition code)     -> discharge_disposition_code
  PV1-39 (facility Part 2 / OMH / OPWDD flag — same source field for all three
          per the operational schema)     -> pv1_39_flag
  PV1-44 (admit date/time)                -> admit_date
  PV1-45 (discharge date/time)            -> discharge_date
  PV2-3  (chief complaint, component 2)   -> chief_complaint
  DG1-3  (diagnosis code, comp 1 / code system, comp 3)
  DG1-6  (diagnosis code type, comp 1)    -> diagnoses[] (one entry per DG1 segment)

NOT parsed (schema columns that need an external lookup/crosswalk — see
adt-tracking-database-requirement.md "Columns skipped"): PV1-2 (only used for
the alert_type crosswalk, which we don't have), and anything requiring a
UPI/SMPI service call or the Zen disposition-text mapping.
"""

from load_lookup import normalize_aa, normalize_mrn


def _component(field_value, index):
    """Return the component at `index` (0-based) of a "^"-delimited field,
    or "" if the field/component is missing."""
    if not field_value:
        return ""
    parts = field_value.split("^")
    if index < len(parts):
        return parts[index].strip()
    return ""


def _field(fields, index):
    """Return fields[index] if present, else ''."""
    return fields[index].strip() if len(fields) > index else ""


def _new_message():
    return {
        "message_type": "",
        "message_time": "",
        "facility_oid": "",
        "source_qe_id": "",
        "_msh5": "",
        "_msh6": "",
        "facility_name": "",
        "identifiers": [],
        "patient_last_name": "",
        "patient_first_name": "",
        "patient_dob": "",
        "account_number": "",
        "encounter_id": "",
        "discharge_disposition_code": "",
        "pv1_39_flag": "",
        "admit_date": "",
        "discharge_date": "",
        "chief_complaint": "",
        "diagnoses": [],
    }


def _finalize_message(msg):
    """Resolve fields that depend on more than one raw value once the whole
    message has been read (e.g. MSH-5/MSH-6 fallback)."""
    msg["source_qe_id"] = msg["_msh5"] or msg["_msh6"]
    del msg["_msh5"]
    del msg["_msh6"]
    return msg


def parse(text):
    """
    Parse HL7v2 text (one or more messages/batch) and return a list of
    message dicts. See module docstring for the field list. `identifiers` is
    a list of {"id", "aa", "raw_pid3"} — one entry per PID-3 repeat (used for
    matching against the known AA|MRN list). `diagnoses` is a list of
    {"diagnosis_code", "diagnosis_code_system", "diagnosis_code_type"} — one
    entry per DG1 segment.
    """
    # Normalize line endings
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    messages = []
    current = None

    def flush_current():
        if current is not None and (current["message_type"] or current["identifiers"]):
            messages.append(_finalize_message(current))

    for line in lines:
        line = line.strip()
        if not line:
            continue

        segment = line[:3]
        fields = line.split("|")

        if segment == "MSH":
            flush_current()
            current = _new_message()
            current["message_type"] = _field(fields, 8)
            current["message_time"] = _field(fields, 6)
            current["facility_oid"] = _component(_field(fields, 3), 1)  # MSH-4 comp 2
            current["_msh5"] = _field(fields, 4)
            current["_msh6"] = _field(fields, 5)
            continue

        if current is None:
            # Segment encountered before any MSH — skip (malformed/partial file)
            continue

        if segment == "EVN":
            current["facility_name"] = _component(_field(fields, 7), 0)  # EVN-7 comp 1

        elif segment == "PID":
            pid3_raw = _field(fields, 3)
            for repeat in pid3_raw.split("~"):
                repeat = repeat.strip()
                if not repeat:
                    continue
                components = repeat.split("^")
                id_value = components[0].strip() if len(components) > 0 else ""
                assigning_auth = components[3].strip() if len(components) > 3 else ""
                if id_value:
                    current["identifiers"].append({
                        "id": normalize_mrn(id_value),
                        "aa": normalize_aa(assigning_auth),
                        "raw_pid3": repeat,
                    })

            current["patient_last_name"] = _component(_field(fields, 5), 0)   # PID-5.1
            current["patient_first_name"] = _component(_field(fields, 5), 1)  # PID-5.2
            current["patient_dob"] = _component(_field(fields, 7), 0)         # PID-7
            current["account_number"] = _component(_field(fields, 18), 0)    # PID-18

        elif segment == "PV1":
            current["encounter_id"] = _component(_field(fields, 19), 0)               # PV1-19
            current["discharge_disposition_code"] = _component(_field(fields, 36), 0)  # PV1-36
            current["pv1_39_flag"] = _component(_field(fields, 39), 0)                 # PV1-39
            current["admit_date"] = _component(_field(fields, 44), 0)                  # PV1-44
            current["discharge_date"] = _component(_field(fields, 45), 0)              # PV1-45

        elif segment == "PV2":
            current["chief_complaint"] = _component(_field(fields, 3), 1)  # PV2-3.2

        elif segment == "DG1":
            dg1_3 = _field(fields, 3)
            dg1_6 = _field(fields, 6)
            current["diagnoses"].append({
                "diagnosis_code": _component(dg1_3, 0),          # DG1-3.1
                "diagnosis_code_system": _component(dg1_3, 2),   # DG1-3.3
                "diagnosis_code_type": _component(dg1_6, 0),     # DG1-6.1
            })

    flush_current()
    return messages


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parse_adt.py <hl7_file>")
        print("  Parses a local HL7v2 file and prints what it finds.")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    msgs = parse(text)
    print(f"Messages found: {len(msgs)}")
    for i, m in enumerate(msgs):
        print(f"\n  Message {i+1}: type={m['message_type']}  time={m['message_time']}")
        print(f"    facility_oid={m['facility_oid']}  facility_name={m['facility_name']}  "
              f"source_qe_id={m['source_qe_id']}")
        print(f"    patient: {m['patient_last_name']}, {m['patient_first_name']}  "
              f"dob={m['patient_dob']}  account={m['account_number']}")
        print(f"    encounter_id={m['encounter_id']}  admit={m['admit_date']}  "
              f"discharge={m['discharge_date']}  disp_code={m['discharge_disposition_code']}  "
              f"pv1_39={m['pv1_39_flag']}")
        print(f"    chief_complaint={m['chief_complaint']}")
        for ident in m["identifiers"]:
            print(f"    PID-3: id={ident['id']}  aa={ident['aa']}  raw={ident['raw_pid3']}")
        for dg in m["diagnoses"]:
            print(f"    DG1: {dg}")
