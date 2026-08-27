"""
score_ccd.py — Master Per-CCD Scorer
======================================

Downloads one CCD from S3, parses it, runs all checker modules, and
assembles the results into a single flat JSON record (Athena-compatible).

This is the core worker — called once per CCD by the pipeline orchestrator.

Usage:
    from score_ccd import score_one_ccd
    result = score_one_ccd(s3_client, bucket, key, qe, assigning_authority)

Or standalone:
    python score_ccd.py <bucket> <key>
"""

import json
import time
import io
import xml.etree.ElementTree as ET

# Checker modules
from checkers import check_diagnoses
from checkers import check_medications
from checkers import check_billing_codes
from checkers import check_encounters
from checkers import check_procedures
from checkers import check_facility_name
import extract_identity


def score_one_ccd(s3_client, bucket, key, qe="", assigning_authority=""):
    """
    Download, parse, and score a single CCD.

    Args:
        s3_client: boto3 S3 client
        bucket: S3 bucket name
        key: S3 object key
        qe: Qualified Entity name (from candidate CSV)
        assigning_authority: AA identifier (from candidate CSV)

    Returns:
        dict — flat JSON record with all fields, ready for NDJSON output.
        On error, returns a record with error info and zeroed scores.
    """
    start_time = time.time()
    path = f"s3://{bucket}/{key}"

    # -----------------------------------------------------------------------
    # Download from S3
    # -----------------------------------------------------------------------
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        body_bytes = response["Body"].read()
        file_size = len(body_bytes)
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return _error_record(path, bucket, key, qe, assigning_authority,
                             f"download_error: {str(e)}", elapsed_ms)

    # -----------------------------------------------------------------------
    # Parse XML
    # -----------------------------------------------------------------------
    try:
        xml_text = body_bytes.decode("utf-8", errors="replace")
        root = ET.fromstring(xml_text)
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return _error_record(path, bucket, key, qe, assigning_authority,
                             f"parse_error: {str(e)}", elapsed_ms, file_size)

    # Detect namespace
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    # -----------------------------------------------------------------------
    # Extract identity fields
    # -----------------------------------------------------------------------
    identity = extract_identity.extract(root, ns)

    # -----------------------------------------------------------------------
    # Run each checker
    # -----------------------------------------------------------------------
    diag_result = check_diagnoses.check(root, ns)
    meds_result = check_medications.check(root, ns)
    billing_result = check_billing_codes.check(root, ns)
    enc_result = check_encounters.check(root, ns)
    proc_result = check_procedures.check(root, ns)
    facility_result = check_facility_name.check(identity["custodian_org_name"])

    # -----------------------------------------------------------------------
    # Compute aggregate scores
    # -----------------------------------------------------------------------
    sud_indicator_count = (
        diag_result["sud_diagnoses_count"]
        + meds_result["mat_medications_count"]
        + billing_result["sud_billing_code_count"]
        + enc_result["sud_encounters_count"]
        + proc_result["sud_procedures_count"]
    )

    has_sud_content = sud_indicator_count > 0

    # Build top_sud_codes — most notable findings, pipe-delimited
    top_codes_parts = []
    if diag_result["sud_diagnosis_codes"]:
        top_codes_parts.append(diag_result["sud_diagnosis_codes"])
    if meds_result["mat_medication_names"]:
        top_codes_parts.append(meds_result["mat_medication_names"])
    if billing_result["sud_billing_codes_found"]:
        top_codes_parts.append(billing_result["sud_billing_codes_found"])
    top_sud_codes = "|".join(top_codes_parts)
    # Truncate if too long for readability
    if len(top_sud_codes) > 200:
        top_sud_codes = top_sud_codes[:197] + "..."

    # -----------------------------------------------------------------------
    # Assemble flat JSON record
    # -----------------------------------------------------------------------
    elapsed_ms = int((time.time() - start_time) * 1000)

    record = {
        # Source identification
        "assigning_authority": assigning_authority,
        "qe": qe,
        "bucket": bucket,
        "key": key,
        "path": path,

        # Identity fields
        "ccd_created_date": identity["ccd_created_date"],
        "ehr_software_name": identity["ehr_software_name"],
        "custodian_org_name": identity["custodian_org_name"],
        "custodian_org_address": identity["custodian_org_address"],
        "service_location_name": identity["service_location_name"],

        # Processing metadata
        "processing_time_ms": elapsed_ms,
        "file_size_bytes": file_size,
        "error": "",

        # Aggregate scores
        "sud_indicator_count": sud_indicator_count,
        "has_sud_content": has_sud_content,

        # Individual checker results
        "sud_diagnoses_count": diag_result["sud_diagnoses_count"],
        "sud_diagnoses_weak_count": diag_result["sud_diagnoses_weak_count"],
        "mat_medications_count": meds_result["mat_medications_count"],
        "mat_strong_signal_count": meds_result["mat_strong_signal_count"],
        "mat_moderate_signal_count": meds_result["mat_moderate_signal_count"],
        "mat_weak_signal_count": meds_result["mat_weak_signal_count"],
        "methadone_dispensed": meds_result["methadone_dispensed"],
        "sud_billing_code_hit": billing_result["sud_billing_code_hit"],
        "sud_billing_code_count": billing_result["sud_billing_code_count"],
        "sud_encounters_count": enc_result["sud_encounters_count"],
        "sud_procedures_count": proc_result["sud_procedures_count"],

        # Facility name analysis
        "facility_name_flags": facility_result["facility_name_flags"],
        "facility_name_is_generic": facility_result["facility_name_is_generic"],

        # Top findings summary
        "top_sud_codes": top_sud_codes,
    }

    return record


def _error_record(path, bucket, key, qe, aa, error_msg, elapsed_ms, file_size=0):
    """Return a zeroed-out record with error information."""
    return {
        "assigning_authority": aa,
        "qe": qe,
        "bucket": bucket,
        "key": key,
        "path": path,
        "ccd_created_date": "",
        "ehr_software_name": "",
        "custodian_org_name": "",
        "custodian_org_address": "",
        "service_location_name": "",
        "processing_time_ms": elapsed_ms,
        "file_size_bytes": file_size,
        "error": error_msg,
        "sud_indicator_count": 0,
        "has_sud_content": False,
        "sud_diagnoses_count": 0,
        "sud_diagnoses_weak_count": 0,
        "mat_medications_count": 0,
        "mat_strong_signal_count": 0,
        "mat_moderate_signal_count": 0,
        "mat_weak_signal_count": 0,
        "methadone_dispensed": False,
        "sud_billing_code_hit": False,
        "sud_billing_code_count": 0,
        "sud_encounters_count": 0,
        "sud_procedures_count": 0,
        "facility_name_flags": "",
        "facility_name_is_generic": True,
        "top_sud_codes": "",
    }


# ============================================================================
# Standalone test — score a single file from S3
# ============================================================================
if __name__ == "__main__":
    import sys
    import boto3
    from run_pipeline_config import get_config

    if len(sys.argv) < 3:
        print("Usage: python score_ccd.py <bucket> <key> [qe] [aa]")
        print("  Uses the active profile's AWS credentials.")
        sys.exit(1)

    cfg = get_config()
    session = boto3.Session(profile_name=cfg["aws_profile"])
    s3 = session.client("s3")

    bucket = sys.argv[1]
    key = sys.argv[2]
    qe = sys.argv[3] if len(sys.argv) > 3 else ""
    aa = sys.argv[4] if len(sys.argv) > 4 else ""

    result = score_one_ccd(s3, bucket, key, qe, aa)

    print(json.dumps(result, indent=2, default=str))
    print()
    print(f"SUD Indicator Count: {result['sud_indicator_count']}")
    print(f"Has SUD Content: {result['has_sud_content']}")
    if result["error"]:
        print(f"ERROR: {result['error']}")
