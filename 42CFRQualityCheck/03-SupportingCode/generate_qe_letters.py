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

    # Filter to candidates at source level only (location detail goes in the letter).
    # Guard: only generate a letter if the source actually shows SUD content.
    # A source with no SUD signal (ccds_with_sud == 0 and score == 0) must never
    # get a letter, even if some edge case classified it as a candidate.
    source_candidates = []
    for r in all_rows:
        if r.get("level") != "source":
            continue
        if not r.get("classification", "").startswith("CANDIDATE"):
            continue
        # Must have real SUD content to warrant a letter
        try:
            ccds_with_sud = int(float(r.get("ccds_with_sud", 0)))
        except (TypeError, ValueError):
            ccds_with_sud = 0
        try:
            source_score = float(r.get("source_score", 0))
        except (TypeError, ValueError):
            source_score = 0.0
        if ccds_with_sud <= 0 or source_score <= 0:
            print(f"  [SKIP] {r.get('assigning_authority', '')}: classified "
                  f"{r.get('classification', '')} but no SUD content — no letter.")
            continue
        source_candidates.append(r)

    if not source_candidates:
        print("[OK] No candidates with SUD content found. No letters to generate.")
        return

    # Get location-level detail for each source
    location_rows = [r for r in all_rows if r.get("level") == "location"]

    os.makedirs(output_dir, exist_ok=True)
    today = date.today().isoformat()

    # Count totals for context
    total_sources = len([r for r in all_rows if r.get("level") == "source"])

    generated = []

    for source in source_candidates:
        aa = source["assigning_authority"]
        qe = source.get("qe", "unknown")

        # Find location-level detail for this source
        source_locations = [
            r for r in location_rows
            if r.get("assigning_authority") == aa and r.get("classification", "").startswith("CANDIDATE")
        ]

        # Generate HTML
        html = _build_letter_html(source, source_locations, gen_pop, total_sources, today)

        # Write file
        aa_short = aa.replace(".", "")[-12:]  # last 12 chars of OID for filename
        filename = f"42CFR_inquiry_{qe}_{aa_short}_{today}.html"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        # Keep the source row and gen-pop stats so a caller (DEV only) can
        # re-render a chosen candidate as the docs-site sample.
        generated.append({
            "filepath": filepath,
            "source": source,
            "locations": source_locations,
            "gen_pop": gen_pop,
            "total_sources": total_sources,
        })

    print(f"[OK] Generated {len(source_candidates)} QE letters in: {output_dir}")

    return generated


def render_sample_letter(entry, dest_path, force_routing_status=None):
    """Render one candidate's letter to dest_path, optionally overriding the
    routing status.

    Used ONLY in DEV to publish a realistic docs-site sample: a source we know
    is 42 CFR, shown as if it had been misrouted into the standard bucket.

    Args:
        entry: one item from generate_letters()'s return list
               (has 'source', 'locations', 'gen_pop', 'total_sources')
        dest_path: where to write the sample HTML
        force_routing_status: if set, overrides the source's routing_status
    """
    source = dict(entry["source"])  # copy so we don't mutate the aggregate row
    if force_routing_status is not None:
        source["routing_status"] = force_routing_status

    today = date.today().isoformat()
    html = _build_letter_html(
        source, entry["locations"], entry["gen_pop"], entry["total_sources"], today
    )

    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(html)


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
    top_findings = source.get("top_sud_findings", "")

    # Weighted 0-100 score and per-category breakdown
    source_score = float(source.get("source_score", 0))
    score_diagnoses = float(source.get("score_diagnoses", 0))
    score_medications = float(source.get("score_medications", 0))
    score_billing = float(source.get("score_billing_codes", 0))
    score_encounters = float(source.get("score_encounters", 0))
    score_facility = float(source.get("score_facility_name", 0))

    # General population comparison (guard against zero division)
    gp_avg_score = float(gen_pop.get("avg_source_score", 0))
    gp_max_score = float(gen_pop.get("max_source_score", 0))
    gp_avg_prev = float(gen_pop.get("avg_sud_prevalence", 0))
    gp_max_prev = float(gen_pop.get("max_sud_prevalence", 0))
    gp_avg_strong = float(gen_pop.get("avg_strong_signal_prevalence", 0))
    gp_max_strong = float(gen_pop.get("max_strong_signal_prevalence", 0))
    gp_count = gen_pop.get("non_candidate_count", 0)

    # Multiplier for comparison (avoid divide by zero)
    if gp_avg_score > 0:
        multiplier_text = f"{source_score/gp_avg_score:.1f}x the average score of sources we did not flag"
    else:
        multiplier_text = "well above the sources we did not flag"

    # Findings table: English description + where it was found in the CCD
    findings_html = ""
    if top_findings:
        rows = ""
        for f in top_findings.split("|"):
            f = f.strip()
            if not f:
                continue
            # f looks like "Description [code] (Section)  —  seen in N of M sampled CCDs"
            main, _, prevalence = f.partition("  —  ")
            # Split "Description [code] (Section)"
            section = ""
            code = ""
            desc = main
            if "(" in main and main.rstrip().endswith(")"):
                desc, _, sect = main.rpartition("(")
                section = sect.rstrip(")").strip()
                desc = desc.strip()
            if "[" in desc and desc.rstrip().endswith("]"):
                desc, _, c = desc.rpartition("[")
                code = c.rstrip("]").strip()
                desc = desc.strip()
            rows += (f"<tr><td>{desc}</td><td>{code}</td>"
                     f"<td>{section}</td><td>{prevalence.strip()}</td></tr>")
        findings_html = f"""
        <h3>What We Found and Where</h3>
        <p>The specific substance-use indicators that drove this source's score, in plain terms
           and where each was located in the CCDs:</p>
        <table>
            <thead><tr><th>Indicator</th><th>Code</th><th>Where in the CCD</th><th>Frequency</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    # Location detail rows
    location_html = ""
    if locations:
        loc_rows = ""
        for loc in locations:
            loc_rows += f"""<tr>
                <td>{loc.get('service_location_name', '')}</td>
                <td>{loc.get('ccds_sampled', '')}</td>
                <td>{float(loc.get('source_score', 0)):.0f}/100</td>
                <td>{float(loc.get('strong_signal_prevalence', 0)):.1%}</td>
                <td>{loc.get('classification', '')}</td>
            </tr>"""
        location_html = f"""
        <h3>Location-Level Detail</h3>
        <p>The following care locations within this source showed concentrated SUD activity:</p>
        <table>
            <thead><tr><th>Location</th><th>CCDs</th><th>Score</th><th>Strong Signal</th><th>Class</th></tr></thead>
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
        header {{ background: linear-gradient(130deg, #3d2b1f 0%, #6a4524 100%); color: #fff; padding: 0.9rem 1.2rem; }}
        header h1 {{ margin: 0; color: #f7d27d; font-size: 1.25em; }}
        header p {{ margin: 0.2rem 0 0; color: #e6cfaa; font-size: 0.9em; }}
        .wrap {{ max-width: 880px; margin: 1rem auto 2rem; padding: 0 1.2rem; }}
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

<header>
    <h1>42 CFR Part 2 &mdash; Request for Potential Part 2 Source</h1>
    <p>{org_name} &nbsp;&bull;&nbsp; Submitted through: {qe}</p>
</header>

<div class="wrap">

    <section class="panel">
        <h2>Request for Potential Part 2 Source</h2>
        <p>To ensure that the SHIN-NY is not releasing 42 CFR Part 2-protected data in error, the
           PDR team ran an analysis on a sample of recent CCD, looking for sources that show indicators
           of being a Part 2 program but whose data was submitted through the standard (non-Part-2)
           pipeline.</p>
        <p>In doing so, we found that <strong>{org_name}</strong> has indicators that it could be a
           Part 2 program. We are asking that <strong>{qe}</strong> work with this source to
           determine whether it is in fact Part 2.</p>
        <p>To be clear: <strong>we are not saying this source is, or is not, a Part 2 program</strong>
           &mdash; we are asking that you look. If data was submitted to PDR as standard when it is in
           fact Part 2, then we will need to work with the Privacy and Security team on a
           remediation plan.</p>
    </section>

    <section class="panel">
        <h2>What the Code Looked For: High Instances of Data Typical of Part 2 Facilities</h2>
        <p>We ran the analysis against a sample of CCDs drawn from all roughly 4,000 sources
           submitting to PDR. For each CCD, the code examined the clinical content and rated it for
           signals that are typical of a 42 CFR Part 2 substance use disorder treatment facility,
           then rolled those ratings up to the source (Assigning Authority) level.</p>
        <p>A facility whose primary business is treating substance use disorder produces clinical
           documents that look measurably different from those of a general medical practice. When
           we examine a source's CCDs in aggregate, a substance-use treatment program tends to leave
           a distinctive and repeating footprint across its patient population. The code looked for
           a high concentration of the following signals:</p>
        <ul>
            <li><strong>A concentration of SUD diagnoses.</strong> ICD-10 codes in the F10&ndash;F19
                range &mdash; alcohol, opioid, sedative, stimulant, cocaine, and polysubstance use
                disorders &mdash; appear not just occasionally (as they would in any general panel)
                but as the dominant reason for care across many encounters. We deliberately exclude
                F17 (nicotine dependence), which is common everywhere and is not Part 2-protected.</li>
            <li><strong>Medication-assisted treatment (MAT) as a routine therapy.</strong> The
                presence of methadone is a particularly strong signal &mdash; for opioid use disorder
                it can only be dispensed through a federally certified Opioid Treatment Program, so
                its appearance is nearly diagnostic of a Part 2 setting. Buprenorphine, naltrexone,
                and similar agents are weaker on their own (they appear in office-based practice too)
                but become meaningful when they cluster with other signals.</li>
            <li><strong>OTP and SUD-specific billing and procedure codes.</strong> HCPCS/CPT codes
                such as H0020 (methadone administration), S0109, H0015 (intensive outpatient), and
                the G2067&ndash;G2078 OTP bundle codes are used almost exclusively by treatment
                programs. Frequent urine drug screening, SBIRT, and structured addiction counseling
                add corroborating weight.</li>
            <li><strong>Encounter types built around treatment, not incidental care.</strong> Detox
                admissions, intensive outpatient (IOP), partial hospitalization, residential
                treatment, and recurring OTP maintenance visits describe a care model, not a
                one-off event.</li>
        </ul>
        <p>Critically, we only count clinical activity that was <em>delivered at the encounter
           itself</em>. A patient mentioning during an ER visit that they take methadone from a
           clinic elsewhere is patient-reported history, not evidence that the ER is a treatment
           program &mdash; and we exclude it. What moves a source onto this list is a sustained,
           population-level pattern of the facility actively providing SUD treatment.</p>
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
        <h2>Why This Source Was Flagged</h2>
        <p>We sampled <strong>{ccds_sampled} CCDs</strong> from {org_name} and scored each on a
           0&ndash;100 scale across five weighted signal categories. This source earned a weighted
           average score of <strong class="red">{source_score:.0f} / 100</strong>, placing it in the
           <strong>{classification}</strong> band.</p>

        <div class="stat-grid">
            <div class="stat-box"><div class="num">{source_score:.0f}/100</div><div class="lbl">Weighted Score</div></div>
            <div class="stat-box"><div class="num">{ccds_with_sud} / {ccds_sampled}</div><div class="lbl">CCDs with SUD Content</div></div>
            <div class="stat-box"><div class="num">{sud_prevalence:.0%}</div><div class="lbl">SUD Prevalence</div></div>
            <div class="stat-box"><div class="num">{strong_prev:.0%}</div><div class="lbl">Strong Signal Prev</div></div>
        </div>

        <h3>Which Signals Flagged This Facility</h3>
        <p>The score is built from five weighted categories. Here is how many of the available
           points this source earned in each &mdash; showing exactly which signals drove the flag:</p>
        <table>
            <thead>
                <tr><th>Signal Category</th><th>Points Earned</th><th>Max</th></tr>
            </thead>
            <tbody>
                <tr><td>SUD diagnoses (F10&ndash;F19)</td><td class="red">{score_diagnoses:.0f}</td><td>25</td></tr>
                <tr><td>OTP / SUD billing &amp; procedure codes</td><td class="red">{score_billing:.0f}</td><td>25</td></tr>
                <tr><td>Treatment-model encounters</td><td class="red">{score_encounters:.0f}</td><td>25</td></tr>
                <tr><td>MAT medications</td><td class="red">{score_medications:.0f}</td><td>20</td></tr>
                <tr><td>Facility name</td><td class="red">{score_facility:.0f}</td><td>5</td></tr>
                <tr style="font-weight:700;"><td>Total</td><td class="red">{source_score:.0f}</td><td>100</td></tr>
            </tbody>
        </table>

        {findings_html}

        {location_html}
    </section>

    <section class="panel">
        <h2>Comparison to Sources Not Flagged</h2>
        <table>
            <thead><tr><th>Metric</th><th>This Source</th><th>Gen Pop Avg ({gp_count} sources)</th><th>Gen Pop Max</th></tr></thead>
            <tbody>
                <tr class="highlight"><td>Weighted Score (0-100)</td><td class="red">{source_score:.0f}</td><td>{gp_avg_score:.0f}</td><td>{gp_max_score:.0f}</td></tr>
                <tr class="highlight"><td>SUD Prevalence</td><td class="red">{sud_prevalence:.1%}</td><td>{gp_avg_prev:.1%}</td><td>{gp_max_prev:.1%}</td></tr>
                <tr class="highlight"><td>Strong Signal Prevalence</td><td class="red">{strong_prev:.1%}</td><td>{gp_avg_strong:.1%}</td><td>{gp_max_strong:.1%}</td></tr>
            </tbody>
        </table>
        <div class="note">This source's weighted score is <strong>{multiplier_text}</strong>.</div>
    </section>

    <section class="panel">
        <h2>Next Steps</h2>
        <ol>
            <li><strong>Contact {org_name}</strong> and determine whether the facility operates as,
                or contains an identified unit that functions as, a substance use disorder treatment
                program.</li>
            <li><strong>Report findings back to the PDR team regardless of outcome.</strong> If the
                source is not Part 2, we simply close it out.</li>
            <li><strong>If this source is in fact Part 2 but its data was submitted to PDR
                attributed as "standard," you need to engage your security and privacy team and
                request that they engage with Chris Klimek <cklimek@nyehealth.org>.</strong> In that case we need to develop a
                specific action plan together, since Part 2-protected data has been flowing through
                the standard pipeline.  </li>
        </ol>
    </section>

    <section class="panel">
        <h2>How We Validated the Code That Scores the Samples</h2>
        <p>A scoring tool is only useful if we know it actually works. Before trusting the code
           against the general population, we validated it against a known set of Part 2
           facilities &mdash; specifically, the sources that QEs have already identified as 42 CFR
           and are submitting to PDR's designated Part 2 endpoint.</p>
        <h3>Calibration against known Part 2 sources</h3>
        <p>We ran the same code &mdash; the same signal detection and scoring logic that produced
           this letter &mdash; against a sample of CCDs from those known-Part-2 sources and confirmed
           that the signals lit up as expected. This gave us confidence that the code genuinely
           distinguishes treatment programs from general care, rather than flagging noise. We refined
           the indicators and thresholds until the code reliably recognized the facilities we already
           knew to be Part 2, then ran that same validated code against the broader population.</p>
        <h3>A grain of salt on the "known" set</h3>
        <p>We also recognize that this reference set is imperfect. Some organizations are highly
           conservative and route entirely ordinary, non-SUD data to the Part 2 endpoint out of an
           abundance of caution. So a source sitting in the Part 2 location does not, by itself,
           prove that its data carries a strong SUD signature. We took the known set as a useful
           guide, not as ground truth, and weighted our validation accordingly &mdash; looking for
           the clinical signature in the data rather than assuming the routing was always correct.</p>
        <h3>Sanity check against general care</h3>
        <p>Finally, we confirmed the code does not over-flag ordinary sources. Across
           {gp_count} general-population sources, the average SUD prevalence was {gp_avg_prev:.1%},
           with a maximum of {gp_max_prev:.1%} &mdash; a clear separation from the treatment-facility
           pattern. Only then did we scan the broader population that produced this candidate list.</p>
        <div class="note">The code used to produce this analysis is available in our Git repository,
           and we are happy to share it with your technical team so they can review exactly how the
           signals are detected and scored.</div>
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
