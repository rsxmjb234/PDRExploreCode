"""
parse_trn.py — HL7v2 Parser for TRN Files (Free-Text Focus)
=============================================================================

SCOPE FOR THIS PASS (explicit user instruction): TRN scanning is FREE TEXT
ONLY. ADT is out of scope entirely for this pass. So this parser extracts
only what the free-text TRN checker (check_trn_measles.py) and the
per-patient rollup actually need:

  MSH-7  message timestamp         -> message_time
  MSH-9  message type              -> message_type
  PID-3  patient identifier list   -> identifiers (id + assigning authority)
         (needed to key the per-patient rollup — see
         measles-detection-technical-plan.md Section 6)
  PID-5  patient name              -> patient_last_name / patient_first_name
  PID-7  date of birth             -> patient_dob
  OBX-5 / NTE-3  free-text narrative lines -> narrative_lines

Deliberately NOT extracted (would require ADT/coded-field scope, which is
out for this pass): PV1-39, PV2-3 chief complaint, DG1 diagnosis codes.

TRN is PDR's term of art for the raw HL7v2 feed a source sends (not a real
HL7 message type — see TRNMessageMix/01-RequirementsAndPlans/trn-message-mix-plan.md).
A TRN file can carry ADT, ORU, MDM, or anything else; we don't rely on a
specific message type here, only on free text wherever it appears.

Field indexing note (same convention as
ADTScanForCandidates/03-SupportingCode/parse_adt.py): for MSH, the segment
name occupies index 0 and MSH-1 (the field separator) is consumed by the
split, so fields[8] = MSH-9, fields[6] = MSH-7. For every other segment,
fields[N] = <segment>-N directly.
"""


def _component(field_value, index):
    if not field_value:
        return ""
    parts = field_value.split("^")
    if index < len(parts):
        return parts[index].strip()
    return ""


def _field(fields, index):
    return fields[index].strip() if len(fields) > index else ""


def _new_message():
    return {
        "message_type": "",
        "message_time": "",
        "identifiers": [],
        "patient_last_name": "",
        "patient_first_name": "",
        "patient_dob": "",
        "narrative_lines": [],
    }


def parse(text):
    """
    Parse HL7v2 text (one or more messages/batch) and return a list of
    message dicts. See module docstring for the field list.
    `identifiers` is a list of {"id", "aa", "raw_pid3"} (unnormalized —
    caller normalizes via normalize.py).
    `narrative_lines` is a list of free-text strings pulled from OBX-5/NTE-3
    — this is the ONLY content the free-text checker scans in this pass.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    messages = []
    current = None

    def flush_current():
        if current is not None and (current["message_type"] or current["identifiers"]):
            messages.append(current)

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
            continue

        if current is None:
            continue  # segment before any MSH — skip (malformed/partial file)

        if segment == "PID":
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
                        "id": id_value, "aa": assigning_auth, "raw_pid3": repeat,
                    })
            current["patient_last_name"] = _component(_field(fields, 5), 0)
            current["patient_first_name"] = _component(_field(fields, 5), 1)
            current["patient_dob"] = _component(_field(fields, 7), 0)

        elif segment == "OBX":
            value = _field(fields, 5)
            if value:
                current["narrative_lines"].append(value)

        elif segment == "NTE":
            comment = _field(fields, 3)
            if comment:
                current["narrative_lines"].append(comment)

    flush_current()
    return messages


# ============================================================================
# Standalone test
# ============================================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parse_trn.py <trn_file.hl7>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    msgs = parse(text)
    print(f"Messages found: {len(msgs)}")
    for i, m in enumerate(msgs):
        print(f"\n  Message {i+1}: type={m['message_type']}  time={m['message_time']}")
        print(f"    patient: {m['patient_last_name']}, {m['patient_first_name']}  dob={m['patient_dob']}")
        for ident in m["identifiers"]:
            print(f"    PID-3: id={ident['id']}  aa={ident['aa']}")
        for n in m["narrative_lines"]:
            print(f"    narrative: {n}")
