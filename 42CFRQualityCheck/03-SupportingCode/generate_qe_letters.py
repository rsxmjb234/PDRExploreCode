"""
generate_qe_letters.py — Per-Source HTML Letter Generator
==========================================================

For each source classified as CANDIDATE (HIGH, MODERATE, or LOW),
generates a self-contained HTML letter addressed to the responsible QE.

The letter explains:
  1. What we are asking (research this source)
  2. Source identity (name, address, EHR, AA, routing)
  3. Our methodology (all 3 phases)
  4. Why this source was flagged (specific indicators)
  5. How it compares to the general population
  6. Requested action
  7. Disclaimer

File naming: 42CFR_inquiry_{qe}_{aa_short}_{date}.html

Usage:
    python generate_qe_letters.py
"""

import csv
import json
import os
import sys
from datetime import date

from run_pipeline_config import get_config


def generate_letters(aggregate_csv_path, gen_pop_stats_path, output_dir):
    """
    Read aggregate CSV and generate one HTML letter per candidate source.

    Args:
        aggregate_csv_path: path to the aggregate results CSV
        gen_pop_stats_path: path to the general population stats JSON
        output_dir: directory to write HTML letters into
    """
    # Load aggregate data
    if not os.path.isfile(aggregate_csv_path):
        print(f"[ERROR] Aggregate CSV not found: {aggregate_csv_path}")
        return

    with open(aggregate_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    # Load general population stats
    gen_pop = {}
    if os.path.isfile(gen_pop_stats_path):
        with open(gen_pop_stats_path, "r", encoding="utf-8") as f:
            gen_pop = json.load(f)

    # Filter to candidates at source level only (location detail goes in the letter)
    source_candidates = [
        r for r in all_rows
        if "CANDIDATE" in r.get("classification", "") and r.get("level") == "source"
    ]

    if not source_candidates:
        print("[OK] No candidates found. No letters to generate.")
        return

    # Get location-level detail for each source
    location_rows = [r for r in all_rows if r.get("level") == "location"]

    os.makedirs(output_dir, exist_ok=True)
    today = date.today().isoformat()

    # Count totals for context
    total_sources = len([r for r in all_rows if r.get("level") == "source"])

    for source in source_candidates:
        aa = source["assigning_authority"]
        qe = source.get("qe", "unknown")

        # Find location-level detail for this source
        source_locations = [
            r for r in location_rows
            if r.get("assigning_authority") == aa and "CANDIDATE" in r.get("classification", "")
        ]

        # Generate HTML
        html = _build_letter_html(source, source_locations, gen_pop, total_sources, today)

        # Write file
        aa_short = aa.replace(".", "")[-12:]  # last 12 chars of OID for filename
        filename = f"42CFR_inquiry_{qe}_{aa_short}_{today}.html"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

    print(f"[OK] Generated {len(source_candidates)} QE letters in: {output_dir}")


def _build_letter_html(source, locations, gen_pop, total_sources, today):
    """Build the full HTML letter for one candidate source."""
    classification = source.get("classification", "")
    banner_color = _get_banner_color(classification)
    aa = source.get("assigning_authority", "")
    qe = source.get("qe", "")
    org_name = source.get("custodian_org_name", aa)
    org_address = source.get("custodian_org_address", "")
    ehr = source.get("ehr_software_name", "")
    ccds_sampled = source.get("ccds_sampled", "0")
    ccds_with_sud = source.get("ccds_with_sud", "0")
    sud_prevalence = float(source.get("sud_prevalence", 0))
    strong_prev = float(source.get("strong_signal_prevalence", 0))
    avg_indicators = source.get("avg_sud_indicator_count", "0")
    routing = source.get("routing_status", "")
    top_codes = source.get("top_sud_codes", "")

    # General population comparison (guard against zero division)
    gp_avg_prev = float(gen_pop.get("avg_sud_prevalence", 0))
    gp_max_prev = float(gen_pop.get("max_sud_prevalence", 0))
    gp_avg_strong = float(gen_pop.get("avg_strong_signal_prevalence", 0))
    gp_max_strong = float(gen_pop.get("max_strong_signal_prevalence", 0))
    gp_count = gen_pop.get("non_candidate_count", 0)

    # Multiplier for comparison (avoid divide by zero)
    if gp_avg_prev > 0:
        multiplier_text = f"{sud_prevalence/gp_avg_prev:.1f}x the general population average"
    else:
        multiplier_text = "not comparable (no general population data in this run)"

    # Location detail rows
    location_html = ""
    if locations:
        loc_rows = ""
        for loc in locations:
            loc_rows += f"""<tr>
                <td>{loc.get('service_location_name', '')}</td>
                <td>{loc.get('ccds_sampled', '')}</td>
                <td>{float(loc.get('sud_prevalence', 0)):.1%}</td>
                <td>{float(loc.get('strong_signal_prevalence', 0)):.1%}</td>
                <td>{loc.get('classification', '')}</td>
            </tr>"""
        location_html = f"""
        <h3>Location-Level Detail</h3>
        <p>The following care locations within this source showed concentrated SUD activity:</p>
        <table>
            <thead><tr><th>Location</th><th>CCDs</th><th>SUD Prev</th><th>Strong Signal</th><th>Class</th></tr></thead>
            <tbody>{loc_rows}</tbody>
        </table>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>42 CFR Research Request: {org_name}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f8f6f2; margin: 0; color: #2f2218; }}
        .banner {{ background: {banner_color}; color: #fff; text-align: center; padding: 0.7rem 1rem; font-weight: 700; font-size: 0.95em; }}
        header {{ background: linear-gradient(130deg, #3d2b1f 0%, #6a4524 100%); color: #fff; padding: 1.8rem 1.2rem 1.2rem; text-align: center; }}
        header h1 {{ margin: 0; color: #f7d27d; font-size: 1.5em; }}
        header p {{ margin: 0.4rem auto 0; color: #e6cfaa; font-size: 0.92em; }}
        .wrap {{ max-width: 880px; margin: 1.2rem auto 2rem; padding: 0 1.2rem; }}
        .panel {{ background: #fffdf8; border-radius: 0.8rem; box-shadow: 0 4px 14px rgba(61,43,31,0.08); border-top: 4px solid #c8a84b; padding: 1.1rem 1.2rem; margin-bottom: 0.9rem; }}
        .panel h2 {{ margin: 0 0 0.4rem; font-size: 1.05em; color: #3d2b1f; }}
        .panel h3 {{ margin: 0.7rem 0 0.3rem; font-size: 0.92em; color: #5c3a1e; }}
        .panel p, .panel li {{ color: #4b3a2c; line-height: 1.65; font-size: 0.9em; }}
        .panel ul, .panel ol {{ margin: 0.3rem 0 0.5rem 1.1rem; padding: 0; }}
        .panel li {{ margin-bottom: 0.25em; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.84em; margin-top: 0.4rem; }}
        th, td {{ border: 1px solid #e6d9c4; padding: 0.4em 0.55em; text-align: left; }}
        th {{ background: #f9f1e2; font-weight: 700; color: #3d2b1f; font-size: 0.82em; text-transform: uppercase; }}
        .highlight {{ background: #fef2f2; }}
        .stat-grid {{ display: grid; gap: 0.5rem; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); margin: 0.4rem 0; }}
        .stat-box {{ background: #fff7de; border: 1px solid #e9ca82; border-radius: 0.5rem; padding: 0.5rem 0.6rem; text-align: center; }}
        .stat-box .num {{ font-size: 1.4em; font-weight: 800; color: #5c3a1e; }}
        .stat-box .lbl {{ font-size: 0.7em; text-transform: uppercase; letter-spacing: 0.7px; color: #815b1d; font-weight: 700; margin-top: 0.15rem; }}
        .red {{ color: #dc2626; font-weight: 700; }}
        .note {{ margin-top: 0.5rem; background: #fef3d0; border-left: 4px solid #c8a84b; border-radius: 0.4rem; padding: 0.5rem 0.7rem; font-size: 0.84em; line-height: 1.55; }}
        .disclaimer {{ margin-top: 0.8rem; background: #f5f0e8; border: 1px solid #e0d5c3; border-radius: 0.6rem; padding: 0.6rem 0.8rem; font-size: 0.82em; line-height: 1.55; color: #5c4a38; }}
        .footer {{ text-align: center; color: #b09060; margin: 1.5rem 0 1rem; font-size: 0.82em; }}
    </style>
</head>
<body>

<div class="banner">{classification} &mdash; Research Requested</div>

<header>
    <h1>42 CFR Part 2 &mdash; Source Research Request</h1>
    <p>{org_name}<br>Submitted through: {qe}</p>
</header>

<div class="wrap">

    <section class="panel">
        <h2>What We Are Asking</h2>
        <p>The PDR is requesting that <strong>{qe}</strong> research the source
           <strong>{org_name}</strong> (Assigning Authority: <code>{aa}</code>) to determine
           whether this source operates as, or contains, a substance use disorder treatment
           program covered under 42 CFR Part 2.</p>
        <p>Based on our analysis of clinical content submitted by this source through the general
           (non-42-CFR) pipeline, we identified patterns consistent with a facility providing SUD
           treatment services. We are asking {qe} to contact this source, determine the nature of
           the services provided, and advise the PDR on whether data routing changes are appropriate.</p>
    </section>

    <section class="panel">
        <h2>Source Information</h2>
        <table>
            <tr><td style="font-weight:700; width:180px;">Qualified Entity</td><td>{qe}</td></tr>
            <tr><td style="font-weight:700;">Source Name</td><td>{org_name}</td></tr>
            <tr><td style="font-weight:700;">Assigning Authority</td><td>{aa}</td></tr>
            <tr><td style="font-weight:700;">Address</td><td>{org_address if org_address else '(not available in CCD)'}</td></tr>
            <tr><td style="font-weight:700;">EHR System</td><td>{ehr if ehr else '(not detected)'}</td></tr>
            <tr><td style="font-weight:700;">Current Routing</td><td class="red">{routing}</td></tr>
            <tr><td style="font-weight:700;">Date of Analysis</td><td>{today}</td></tr>
        </table>
    </section>

    <section class="panel">
        <h2>Our Methodology</h2>
        <p>The PDR developed an automated scoring tool that examines the clinical content of CCD
           files to identify patterns consistent with substance use disorder treatment activity.
           The methodology was developed and validated in three phases:</p>
        <h3>Phase 1 &mdash; Calibration Against Known 42 CFR Sources</h3>
        <p>We ran the tool against sources that QEs have already submitted to PDR's designated
           42 CFR endpoint (known Part 2 programs). We iterated until the tool reliably identified
           known positives as candidates.</p>
        <h3>Phase 2 &mdash; General Population Sanity Check</h3>
        <p>We ran the tool against sources from the general pipeline and confirmed it does not
           over-flag ordinary care sources. Among {gp_count} general-population sources, the average
           SUD prevalence was {gp_avg_prev:.1%} with a maximum of {gp_max_prev:.1%}.</p>
        <h3>Phase 3 &mdash; Candidate Identification</h3>
        <p>With confidence the tool works both ways, we scanned <strong>{total_sources} sources</strong>
           submitting to the general pipeline. Sources whose clinical content pattern is consistent
           with SUD treatment activity became candidates for QE research.</p>
        <h3>What the Tool Looks For</h3>
        <ul>
            <li>ICD-10 F10-F19 diagnoses (SUD, excluding nicotine F17)</li>
            <li>MAT medications (methadone = strong signal; buprenorphine/naltrexone = moderate)</li>
            <li>OTP billing codes (H0020, S0109, H0015, G2067-G2078, etc.)</li>
            <li>SUD encounter types (detox, IOP, OTP visits, residential treatment)</li>
            <li>SUD procedures (urine drug screens, SBIRT, addiction counseling)</li>
        </ul>
        <p>We only count activity tied to care delivered at the visit itself &mdash; not patient-reported
           history from elsewhere.</p>
    </section>

    <section class="panel">
        <h2>Why This Source Was Flagged</h2>
        <p>We sampled <strong>{ccds_sampled} CCDs</strong> from {org_name}. Of these,
           <strong>{ccds_with_sud} contained SUD treatment indicators</strong> &mdash; an SUD
           prevalence of <strong class="red">{sud_prevalence:.1%}</strong>.</p>

        <div class="stat-grid">
            <div class="stat-box"><div class="num">{sud_prevalence:.0%}</div><div class="lbl">SUD Prevalence</div></div>
            <div class="stat-box"><div class="num">{ccds_with_sud} / {ccds_sampled}</div><div class="lbl">CCDs with SUD</div></div>
            <div class="stat-box"><div class="num">{avg_indicators}</div><div class="lbl">Avg Indicators/CCD</div></div>
            <div class="stat-box"><div class="num">{strong_prev:.0%}</div><div class="lbl">Strong Signal Prev</div></div>
        </div>

        <h3>Top Indicator Codes Observed</h3>
        <p>{top_codes.replace('|', ', ') if top_codes else '(none recorded)'}</p>

        {location_html}
    </section>

    <section class="panel">
        <h2>Comparison to Sources Not Flagged</h2>
        <table>
            <thead><tr><th>Metric</th><th>This Source</th><th>Gen Pop Avg ({gp_count} sources)</th><th>Gen Pop Max</th></tr></thead>
            <tbody>
                <tr class="highlight"><td>SUD Prevalence</td><td class="red">{sud_prevalence:.1%}</td><td>{gp_avg_prev:.1%}</td><td>{gp_max_prev:.1%}</td></tr>
                <tr class="highlight"><td>Strong Signal Prevalence</td><td class="red">{strong_prev:.1%}</td><td>{gp_avg_strong:.1%}</td><td>{gp_max_strong:.1%}</td></tr>
            </tbody>
        </table>
        <div class="note">This source's SUD prevalence is <strong>{multiplier_text}</strong>.</div>
    </section>

    <section class="panel">
        <h2>Requested Action</h2>
        <ol>
            <li><strong>Contact {org_name}</strong> and determine whether the facility operates as,
                or contains an identified unit that functions as, a substance use disorder treatment
                program.</li>
            <li><strong>Advise the PDR</strong> on whether this source's data should be rerouted to
                the 42 CFR-designated pipeline, and whether retroactive changes are needed.</li>
            <li><strong>Report findings</strong> back to the PDR team regardless of outcome.</li>
        </ol>
    </section>

    <section class="panel">
        <div class="disclaimer">
            <strong>Disclaimer:</strong> This analysis identifies clinical content patterns only.
            It is not a legal determination of 42 CFR Part 2 status. Part 2 status depends on
            whether a program is "federally assisted" and "holds itself out" as providing SUD
            treatment &mdash; factors not visible in clinical data. This report surfaces an
            investigative signal. The QE's research and response will inform any routing decisions.
            <br><br>
            No patient-identifiable information is included. All findings are presented as aggregated
            code patterns and prevalence statistics.
        </div>
    </section>

</div>

<div class="footer">
    Generated by PDR 42 CFR Candidate Identification Tool<br>
    Report date: {today}<br>
    Contact: PDR Data Quality Team
</div>

</body>
</html>"""

    return html


def _get_banner_color(classification):
    """Return banner color based on classification."""
    if "HIGH" in classification:
        return "#dc2626"
    elif "MODERATE" in classification:
        return "#ea580c"
    elif "LOW" in classification:
        return "#ca8a04"
    return "#6b7280"


# ============================================================================
# Standalone execution
# ============================================================================
if __name__ == "__main__":
    cfg = get_config()
    agg_csv = cfg["output_aggregate_csv"]
    stats_json = agg_csv.replace(".csv", "_gen_pop_stats.json")
    letters_dir = cfg["output_letters_dir"]

    print(f"42 CFR QE Letter Generation")
    print(f"===========================")
    print(f"Aggregate CSV: {agg_csv}")
    print(f"Output dir: {letters_dir}")
    print()

    generate_letters(agg_csv, stats_json, letters_dir)
