"""
aggregate_sources.py — Source/Location Prevalence Aggregator
=============================================================

Reads all scored JSON files from the output directory, groups by:
  Level 1: assigning_authority (whole source)
  Level 2: assigning_authority + service_location_name (unit within source)

Computes for each group:
  - ccds_sampled (total scored)
  - ccds_with_sud (count where has_sud_content = True)
  - sud_prevalence (ccds_with_sud / ccds_sampled)
  - strong_signal_prevalence (CCDs with methadone_dispensed OR sud_billing_code_hit)
  - avg_sud_indicator_count (mean indicators per CCD)
  - classification: HIGH / MODERATE / LOW / NOT_CANDIDATE

Applies the strong-signal override: any source/location with
strong_signal_prevalence > 0 becomes at minimum CANDIDATE - LOW.

Outputs:
  - aggregate CSV (one row per source + one row per location)
  - general population stats for use in QE letters

Usage:
    python aggregate_sources.py
"""

import json
import csv
import os
import sys
from collections import defaultdict

from run_pipeline_config import (
    get_config,
    THRESHOLD_HIGH,
    THRESHOLD_MODERATE,
    THRESHOLD_LOW,
    STRONG_SIGNAL_OVERRIDE,
    CFR42_BUCKET_MARKERS,
)


def aggregate(json_dir, output_csv_path):
    """
    Read all scored JSONs and produce aggregate CSV.

    Args:
        json_dir: path to directory containing scored JSON files (NDJSON or individual)
        output_csv_path: path for output aggregate CSV

    Returns:
        list of dicts (the aggregate rows), also written to CSV
    """
    # -----------------------------------------------------------------------
    # Load all scored records
    # -----------------------------------------------------------------------
    records = _load_all_records(json_dir)
    if not records:
        print("[WARNING] No scored records found in:")
        print(f"         {os.path.abspath(json_dir)}")
        print()
        print("  This usually means the scoring step hasn't been run yet.")
        print("  Run the full pipeline first:  python run_pipeline.py")
        print("  Or run scoring only:          python run_pipeline.py --score-only")
        return []

    print(f"[OK] Loaded {len(records)} scored CCD records.")

    # -----------------------------------------------------------------------
    # Group by source (Level 1) and by source+location (Level 2)
    # -----------------------------------------------------------------------
    source_groups = defaultdict(list)
    location_groups = defaultdict(list)

    for rec in records:
        aa = rec.get("assigning_authority", "unknown")
        loc = rec.get("service_location_name", "")
        source_groups[aa].append(rec)
        if loc:
            location_groups[(aa, loc)].append(rec)

    # -----------------------------------------------------------------------
    # Compute stats for each source
    # -----------------------------------------------------------------------
    aggregate_rows = []

    for aa, group_records in source_groups.items():
        row = _compute_group_stats(group_records, aa, "", "source")
        aggregate_rows.append(row)

    # Compute stats for each location within a source
    for (aa, loc), group_records in location_groups.items():
        row = _compute_group_stats(group_records, aa, loc, "location")
        aggregate_rows.append(row)

    # -----------------------------------------------------------------------
    # Sort: candidates first (HIGH > MODERATE > LOW), then by prevalence desc
    # -----------------------------------------------------------------------
    classification_order = {
        "CANDIDATE - HIGH": 0,
        "CANDIDATE - MODERATE": 1,
        "CANDIDATE - LOW": 2,
        "NOT A CANDIDATE": 3,
    }
    aggregate_rows.sort(key=lambda r: (
        classification_order.get(r["classification"], 9),
        -r["sud_prevalence"],
    ))

    # -----------------------------------------------------------------------
    # Compute general population stats (for comparison in letters)
    # -----------------------------------------------------------------------
    gen_pop_stats = _compute_general_population_stats(aggregate_rows)

    # -----------------------------------------------------------------------
    # Write aggregate CSV
    # -----------------------------------------------------------------------
    _write_csv(aggregate_rows, output_csv_path)
    print(f"[OK] Aggregate CSV written: {output_csv_path}")
    print(f"     Sources evaluated: {len(source_groups)}")
    print(f"     Locations evaluated: {len(location_groups)}")

    candidates = [r for r in aggregate_rows if "CANDIDATE" in r["classification"]]
    print(f"     Total candidates: {len(candidates)}")

    # Write gen pop stats as a small JSON alongside the CSV
    stats_path = output_csv_path.replace(".csv", "_gen_pop_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(gen_pop_stats, f, indent=2)
    print(f"[OK] General population stats: {stats_path}")

    return aggregate_rows


def _compute_group_stats(records, assigning_authority, location, level):
    """Compute prevalence and classification for a group of CCD records."""
    ccds_sampled = len(records)
    ccds_with_sud = sum(1 for r in records if r.get("has_sud_content", False))
    ccds_with_strong = sum(
        1 for r in records
        if r.get("methadone_dispensed", False) or r.get("sud_billing_code_hit", False)
    )

    sud_prevalence = ccds_with_sud / ccds_sampled if ccds_sampled > 0 else 0.0
    strong_signal_prevalence = ccds_with_strong / ccds_sampled if ccds_sampled > 0 else 0.0

    total_indicators = sum(r.get("sud_indicator_count", 0) for r in records)
    avg_indicators = total_indicators / ccds_sampled if ccds_sampled > 0 else 0.0

    # Classification
    classification = _classify(sud_prevalence, strong_signal_prevalence)

    # Routing check — use the first record's bucket/path as representative
    first_rec = records[0]
    routing_status = _check_routing(first_rec.get("path", ""), first_rec.get("bucket", ""))

    # Most common identity info (take from first record)
    qe = first_rec.get("qe", "")
    custodian_org_name = first_rec.get("custodian_org_name", "")
    custodian_org_address = first_rec.get("custodian_org_address", "")
    ehr_software_name = first_rec.get("ehr_software_name", "")
    facility_name_is_generic = first_rec.get("facility_name_is_generic", True)

    # Top codes across all CCDs in this group
    all_top_codes = [r.get("top_sud_codes", "") for r in records if r.get("top_sud_codes")]
    # Flatten, deduplicate, take top 10
    code_parts = []
    for tc in all_top_codes:
        code_parts.extend(tc.split("|"))
    unique_top = list(dict.fromkeys(p for p in code_parts if p))[:10]

    return {
        "assigning_authority": assigning_authority,
        "service_location_name": location,
        "level": level,
        "qe": qe,
        "custodian_org_name": custodian_org_name,
        "custodian_org_address": custodian_org_address,
        "ehr_software_name": ehr_software_name,
        "facility_name_is_generic": facility_name_is_generic,
        "ccds_sampled": ccds_sampled,
        "ccds_with_sud": ccds_with_sud,
        "sud_prevalence": round(sud_prevalence, 4),
        "ccds_with_strong_signal": ccds_with_strong,
        "strong_signal_prevalence": round(strong_signal_prevalence, 4),
        "avg_sud_indicator_count": round(avg_indicators, 2),
        "classification": classification,
        "routing_status": routing_status,
        "top_sud_codes": "|".join(unique_top),
    }


def _classify(sud_prevalence, strong_signal_prevalence):
    """Apply classification thresholds with strong-signal override."""
    if sud_prevalence > THRESHOLD_HIGH:
        return "CANDIDATE - HIGH"
    elif sud_prevalence > THRESHOLD_MODERATE:
        return "CANDIDATE - MODERATE"
    elif sud_prevalence > THRESHOLD_LOW:
        return "CANDIDATE - LOW"
    elif STRONG_SIGNAL_OVERRIDE and strong_signal_prevalence > 0:
        # Override: any strong signal makes it at least LOW
        return "CANDIDATE - LOW"
    else:
        return "NOT A CANDIDATE"


def _check_routing(path, bucket):
    """Determine if a source is in the general or 42 CFR bucket."""
    check_str = (path + " " + bucket).lower()
    for marker in CFR42_BUCKET_MARKERS:
        if marker in check_str:
            return "ALREADY SEGREGATED (42 CFR bucket)"
    return "GENERAL BUCKET (potentially misrouted)"


def _compute_general_population_stats(aggregate_rows):
    """Compute stats across non-candidate sources for comparison in letters."""
    non_candidates = [
        r for r in aggregate_rows
        if r["classification"] == "NOT A CANDIDATE" and r["level"] == "source"
    ]
    if not non_candidates:
        return {
            "non_candidate_count": 0,
            "avg_sud_prevalence": 0.0,
            "max_sud_prevalence": 0.0,
            "avg_strong_signal_prevalence": 0.0,
            "max_strong_signal_prevalence": 0.0,
            "avg_sud_indicator_count": 0.0,
            "max_sud_indicator_count": 0.0,
        }

    prevalences = [r["sud_prevalence"] for r in non_candidates]
    strong_prevs = [r["strong_signal_prevalence"] for r in non_candidates]
    indicator_avgs = [r["avg_sud_indicator_count"] for r in non_candidates]

    return {
        "non_candidate_count": len(non_candidates),
        "avg_sud_prevalence": round(sum(prevalences) / len(prevalences), 4),
        "max_sud_prevalence": round(max(prevalences), 4),
        "avg_strong_signal_prevalence": round(sum(strong_prevs) / len(strong_prevs), 4),
        "max_strong_signal_prevalence": round(max(strong_prevs), 4),
        "avg_sud_indicator_count": round(sum(indicator_avgs) / len(indicator_avgs), 2),
        "max_sud_indicator_count": round(max(indicator_avgs), 2),
    }


def _load_all_records(json_dir):
    """Load scored records from JSON directory (supports NDJSON files or individual JSONs)."""
    records = []

    if not os.path.isdir(json_dir):
        print(f"[ERROR] JSON directory not found: {json_dir}")
        return records

    for filename in os.listdir(json_dir):
        filepath = os.path.join(json_dir, filename)
        if not os.path.isfile(filepath):
            continue

        if filename.endswith(".json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        continue
                    # Could be a single JSON or NDJSON (one per line)
                    if content.startswith("["):
                        # JSON array
                        records.extend(json.loads(content))
                    else:
                        # NDJSON or single object
                        for line in content.split("\n"):
                            line = line.strip()
                            if line:
                                records.append(json.loads(line))
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARNING] Could not read {filepath}: {e}")

    return records


def _write_csv(rows, output_path):
    """Write aggregate rows to CSV."""
    if not rows:
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ============================================================================
# Standalone execution
# ============================================================================
if __name__ == "__main__":
    cfg = get_config()
    json_dir = cfg["output_json_dir"]
    output_csv = cfg["output_aggregate_csv"]

    print(f"42 CFR Source Aggregation")
    print(f"========================")
    print(f"Profile: {cfg.get('aws_profile', 'unknown')}")
    print(f"JSON dir: {json_dir}")
    print(f"Output: {output_csv}")
    print()

    results = aggregate(json_dir, output_csv)

    if results:
        print()
        print("Top candidates:")
        for r in results[:10]:
            if "CANDIDATE" in r["classification"]:
                print(f"  {r['assigning_authority'][:40]:40s} "
                      f"{r['classification']:22s} "
                      f"prev={r['sud_prevalence']:.1%} "
                      f"strong={r['strong_signal_prevalence']:.1%}")
