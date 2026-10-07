"""
score_candidate.py — Per-File Measles Signal Worker
=============================================================================

SCOPE FOR THIS PASS (explicit user instruction): only CCD and TRN. CCD is
checked on BOTH coded data and free text. TRN is checked on FREE TEXT ONLY.
ADT and Lab/ORU are out of scope entirely — there is no ADT dispatch branch
here right now; adding it back is a follow-on, not a bug.

Downloads one candidate file from S3, parses it according to its data type
(CCD = XML, TRN = HL7v2 free text), runs the matching checker, and returns a
flat list of finding records (Output A rows — see
measles-detection-technical-plan.md Section 7). This is the core worker,
called once per candidate file by run_pipeline.py.

Modeled directly on 42CFRQualityCheck/score_ccd.py (same download -> parse
-> checker -> flat-record structure).

Usage:
    from score_candidate import score_one_candidate
    rows = score_one_candidate(s3_client, bucket, key, qe, assigning_authority, data_type)
"""

import time
import xml.etree.ElementTree as ET

import parse_trn
import extract_patient_identity
from checkers import check_ccd_measles, check_trn_measles
from normalize import normalize_aa, normalize_mrn


def score_one_candidate(s3_client, bucket, key, qe, assigning_authority, data_type):
    """
    Download, parse, and scan a single candidate file for measles signals.

    Args:
        s3_client: boto3 S3 client
        bucket: S3 bucket name
        key: S3 object key
        qe: Qualified Entity name (from candidate CSV)
        assigning_authority: AA identifier (from candidate CSV)
        data_type: "CCD" | "TRN" (only these two are supported this pass)

    Returns:
        list of flat dicts — one row per (patient identifier, finding) pair
        found in this file. Empty list if the file parsed cleanly but had no
        findings (still counted as "processed", just produces zero rows —
        same "capture everything we touch, but only candidates get a row"
        philosophy as the output format in the technical plan). On
        download/parse error, returns a single error-marker row so the
        failure is visible without halting the run (see run_pipeline.py's
        errors.log for the restart-safe equivalent).
    """
    start_time = time.time()
    path = f"s3://{bucket}/{key}"

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        body_bytes = response["Body"].read()
    except Exception as e:
        return [_error_row(path, bucket, key, qe, assigning_authority, data_type,
                            f"download_error: {e}")]

    try:
        if data_type == "CCD":
            rows = _score_ccd(body_bytes, path, bucket, key, qe, assigning_authority)
        elif data_type == "TRN":
            rows = _score_trn(body_bytes, path, bucket, key, qe, assigning_authority)
        else:
            # ADT and Lab/ORU are explicitly out of scope for this pass.
            return [_error_row(path, bucket, key, qe, assigning_authority, data_type,
                                f"unsupported_data_type_this_pass: {data_type}")]
    except Exception as e:
        return [_error_row(path, bucket, key, qe, assigning_authority, data_type,
                            f"parse_error: {e}")]

    elapsed_ms = int((time.time() - start_time) * 1000)
    for r in rows:
        r["processing_time_ms"] = elapsed_ms
    return rows


def _score_ccd(body_bytes, path, bucket, key, qe, assigning_authority):
    xml_text = body_bytes.decode("utf-8", errors="replace")
    root = ET.fromstring(xml_text)
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    identity = extract_patient_identity.extract(root, ns)
    result = check_ccd_measles.check(root, ns)

    return _build_rows(result["findings"], path, bucket, key, qe, assigning_authority,
                        "CCD", identity)


def _score_trn(body_bytes, path, bucket, key, qe, assigning_authority):
    """TRN is checked on FREE TEXT ONLY this pass — see check_trn_measles.py."""
    text = body_bytes.decode("utf-8", errors="replace")
    messages = parse_trn.parse(text)

    rows = []
    for msg in messages:
        result = check_trn_measles.check(msg)
        if not result["findings"]:
            continue

        # Build an identity dict per message, matching extract_patient_identity's
        # shape, from the first PID-3 identifier (same "first repeat only"
        # convention used in ADTScanForCandidates' capture_adt_record.py).
        identifiers = msg.get("identifiers", [])
        first_ident = identifiers[0] if identifiers else {"id": "", "aa": ""}
        identity = {
            "mrn": first_ident.get("id", ""),
            "assigning_authority": first_ident.get("aa", "") or assigning_authority,
            "patient_last_name": msg.get("patient_last_name", ""),
            "patient_first_name": msg.get("patient_first_name", ""),
            "patient_dob": msg.get("patient_dob", ""),
            "encounter_date": msg.get("message_time", ""),
            "encounter_location": "",
        }
        rows.extend(_build_rows(result["findings"], path, bucket, key, qe,
                                 assigning_authority, "TRN", identity))
    return rows


def _build_rows(findings, path, bucket, key, qe, assigning_authority, data_type, identity):
    rows = []
    for f in findings:
        rows.append({
            "path": path,
            "bucket": bucket,
            "key": key,
            "data_type": data_type,
            "qe": qe,
            "assigning_authority": normalize_aa(identity.get("assigning_authority") or assigning_authority),
            "mrn": normalize_mrn(identity.get("mrn", "")),
            "patient_last_name": identity.get("patient_last_name", ""),
            "patient_first_name": identity.get("patient_first_name", ""),
            "patient_dob": identity.get("patient_dob", ""),
            "encounter_date": identity.get("encounter_date", ""),
            "encounter_location": identity.get("encounter_location", ""),
            "signal_type": f["signal_type"],
            "signal_detail": f["signal_detail"],
            "section": f["section"],
            "error": "",
        })
    return rows


def _error_row(path, bucket, key, qe, assigning_authority, data_type, error_msg):
    return {
        "path": path, "bucket": bucket, "key": key, "data_type": data_type,
        "qe": qe, "assigning_authority": assigning_authority, "mrn": "",
        "patient_last_name": "", "patient_first_name": "", "patient_dob": "",
        "encounter_date": "", "encounter_location": "",
        "signal_type": "", "signal_detail": "", "section": "",
        "error": error_msg, "processing_time_ms": 0,
    }


# ============================================================================
# Standalone test — score a single file from S3
# ============================================================================
if __name__ == "__main__":
    import sys
    import json
    import boto3
    from config import get_config

    if len(sys.argv) < 4:
        print("Usage: python score_candidate.py <bucket> <key> <CCD|TRN> [qe] [aa]")
        print("  (ADT and Lab/ORU are out of scope for this pass.)")
        sys.exit(1)

    cfg = get_config()
    session = boto3.Session(profile_name=cfg["aws_profile"])
    s3 = session.client("s3")

    bucket, key, data_type = sys.argv[1], sys.argv[2], sys.argv[3].upper()
    qe = sys.argv[4] if len(sys.argv) > 4 else ""
    aa = sys.argv[5] if len(sys.argv) > 5 else ""

    rows = score_one_candidate(s3, bucket, key, qe, aa, data_type)
    print(json.dumps(rows, indent=2, default=str))
    print(f"\nRows produced: {len(rows)}")
