"""
parse_adt.py — HL7v2 ADT parser: extract MSH context + all PID-3 identifiers
==============================================================================

Parses raw HL7v2 text and returns:
  - MSH-9 (message type, e.g. "ADT^A03")
  - MSH-7 (message timestamp)
  - A list of (id_value, assigning_authority) from every PID-3 occurrence

HL7v2 field separator is "|". Sub-component separator inside PID-3 is "^".

PID-3 (Patient Identifier List) layout:
  ID^check_digit^scheme^assigning_authority^id_type^...
  component 1 = the ID/MRN value
  component 4 = assigning authority (name, OID, or code)

A single file can contain multiple messages (batch) separated by MSH segments.
This parser handles that by iterating every MSH/PID pair found.
"""

from load_lookup import normalize_aa, normalize_mrn


def parse(text):
    """
    Parse HL7v2 text and extract MSH context + PID-3 identifiers.

    Args:
        text: raw HL7v2 message text (may contain multiple messages)

    Returns:
        list of dicts, one per message found:
        [
            {
                "message_type": "ADT^A03",
                "message_time": "20260731143022",
                "identifiers": [
                    {"id": "12345", "aa": "HEALTHIX", "raw_pid3": "12345^^^HEALTHIX^MR"},
                    ...
                ]
            },
            ...
        ]
    """
    # Normalize line endings
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    messages = []
    current_msh9 = ""
    current_msh7 = ""
    current_ids = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("MSH|"):
            # If we were already collecting a message, save it
            if current_msh9 or current_ids:
                messages.append({
                    "message_type": current_msh9,
                    "message_time": current_msh7,
                    "identifiers": current_ids,
                })
            # Start a new message
            fields = line.split("|")
            # MSH-9 is field index 8 (MSH|^~\&|...|...|...|...|...|MSH-9|...)
            current_msh9 = fields[8].strip() if len(fields) > 8 else ""
            # MSH-7 is field index 6
            current_msh7 = fields[6].strip() if len(fields) > 6 else ""
            current_ids = []

        elif line.startswith("PID|"):
            fields = line.split("|")
            # PID-3 is field index 3 (PID|set_id|ext_id|PID-3|alt_id|...)
            if len(fields) > 3:
                pid3_raw = fields[3]
                # PID-3 can be a repeating field (~ separated)
                for repeat in pid3_raw.split("~"):
                    repeat = repeat.strip()
                    if not repeat:
                        continue
                    components = repeat.split("^")
                    id_value = components[0].strip() if len(components) > 0 else ""
                    assigning_auth = components[3].strip() if len(components) > 3 else ""

                    if id_value:
                        current_ids.append({
                            "id": normalize_mrn(id_value),
                            "aa": normalize_aa(assigning_auth),
                            "raw_pid3": repeat,
                        })

    # Don't forget the last message in the file
    if current_msh9 or current_ids:
        messages.append({
            "message_type": current_msh9,
            "message_time": current_msh7,
            "identifiers": current_ids,
        })

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
        for ident in m["identifiers"]:
            print(f"    PID-3: id={ident['id']}  aa={ident['aa']}  raw={ident['raw_pid3']}")
