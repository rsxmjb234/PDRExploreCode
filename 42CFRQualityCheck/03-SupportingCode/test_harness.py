"""
test_harness.py — 42 CFR Candidate Identification Test Harness
================================================================

Runs the pipeline and evaluates results against known ground truth.
Works in both DEV and PROD using the same logic — the only difference
is where the candidates CSV comes from:

  DEV:  Rebuilt fresh each run by calling make_dev_candidates_42cfr.py
        (lists s3://nyec.ccda.learning/42CFRStyleCCDs/ and 42CFRTesting-Not42CFR/)
  PROD: Already exists — produced by Athena SQL (findcandidates_42cfr.sql)

Both produce the same 5-column CSV with a 'part2' column as ground truth.
The test checks: did our code correctly identify part2=Yes as CANDIDATE
and part2=No as NOT A CANDIDATE?

Usage:
    python test_harness.py DEV
    python test_harness.py PROD
    python test_harness.py DEV --skip-scoring   (use existing results)
    python test_harness.py PROD --skip-scoring

================================================================================
CONFIGURATION
================================================================================
"""

import csv
import json
import os
import sys

# ============================================================================
# CHOOSE YOUR LANDSCAPE -- "DEV" or "PROD"
# (can also pass as first CLI argument)
# ============================================================================

LANDSCAPE = "DEV"

# ============================================================================
# CANDIDATES CSV PATHS
# ============================================================================
# DEV: rebuilt each run by make_dev_candidates_42cfr.py
# PROD: exported from Athena, placed here manually

DEV_CANDIDATES_CSV = os.path.join("..", "05-Candidates", "DEV-42CFR-CandidateS3Paths.csv")
PROD_CANDIDATES_CSV = os.path.join("..", "05-Candidates", "PROD-CandidateS3PathsForEvaluation.csv")

# ============================================================================
# VARIANCE TOLERANCE
# ============================================================================
# How many misclassifications are acceptable before the test "fails"?
# This accounts for borderline cases and imperfect synthetic data.
#
# False negative = a known Part 2 source our code missed (cost: missed phone call)
# False positive = a non-Part-2 source our code flagged (cost: unnecessary phone call)

VARIANCE = {
    "DEV": {
        "max_false_negatives": 2,   # DEV synthetic data should mostly work
        "max_false_positives": 0,   # Non-42CFR sources should not trigger
    },
    "PROD": {
        "max_false_negatives": 5,   # real data has edge cases
        "max_false_positives": 3,   # some sources may be borderline
    },
}


# ============================================================================
# Main
# ============================================================================

def main():
    global LANDSCAPE

    # Parse CLI
    if len(sys.argv) >= 2 and sys.argv[1].upper() in ("DEV", "PROD"):
        LANDSCAPE = sys.argv[1].upper()

    skip_scoring = "--skip-scoring" in sys.argv

    # Auto-set working directory to this script's folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    candidates_csv = DEV_CANDIDATES_CSV if LANDSCAPE == "DEV" else PROD_CANDIDATES_CSV

    print()
    print("=" * 70)
    print(f"  42 CFR TEST HARNESS — {LANDSCAPE}")
    print("=" * 70)
    print(f"  Candidates CSV: {candidates_csv}")
    print(f"  Skip scoring:   {skip_scoring}")
    print("=" * 70)
    print()

    # -----------------------------------------------------------------------
    # Step 0 (DEV only): Rebuild candidates CSV from S3
    # -----------------------------------------------------------------------
    if LANDSCAPE == "DEV":
        print("Step 0: Rebuilding DEV candidates CSV from S3...")
        print("-" * 70)
        _rebuild_dev_candidates()
        print()

    # -----------------------------------------------------------------------
    # Step 1: Verify candidates CSV exists
    # -----------------------------------------------------------------------
    print("Step 1: Verifying candidates CSV...")
    print("-" * 70)

    if not os.path.isfile(candidates_csv):
        print(f"  [FAIL] Candidates CSV not found: {os.path.abspath(candidates_csv)}")
        if LANDSCAPE == "PROD":
            print(f"         Run findcandidates_42cfr.sql in Athena, export CSV, place here.")
        sys.exit(1)

    # Quick stats
    with open(candidates_csv, "r", encoding="utf-8-sig") as f:
        all_candidate_rows = list(csv.DictReader(f))

    yes_count = sum(1 for r in all_candidate_rows if r.get("part2", "").strip().lower() == "yes")
    no_count = sum(1 for r in all_candidate_rows if r.get("part2", "").strip().lower() == "no")
    print(f"  Total rows:     {len(all_candidate_rows)}")
    print(f"  Part2=Yes:      {yes_count}")
    print(f"  Part2=No:       {no_count}")
    print()

    # -----------------------------------------------------------------------
    # Step 2: Run the pipeline (unless --skip-scoring)
    # -----------------------------------------------------------------------
    if not skip_scoring:
        print("Step 2: Running pipeline...")
        print("-" * 70)

        # Pipeline has built-in restart: it skips any CCD already in scored_jsons/.
        # To force a full re-run, delete 06-Results/{landscape}-Output/scored_jsons/
        # or use cleanup_run.py

        import run_pipeline
        run_pipeline.ACTIVE_PROFILE = LANDSCAPE
        import run_pipeline_config
        run_pipeline_config.ACTIVE_PROFILE = LANDSCAPE
        run_pipeline.main()
        print()
    else:
        print("Step 2: SKIPPED (--skip-scoring)")
        print()

    # -----------------------------------------------------------------------
    # Step 3: Load aggregate results
    # -----------------------------------------------------------------------
    print("Step 3: Loading aggregate results...")
    print("-" * 70)

    if LANDSCAPE == "DEV":
        agg_csv = os.path.join("..", "06-Results", "Output", "DEV", "aggregate_results.csv")
    else:
        agg_csv = os.path.join("..", "06-Results", "Output", "PROD", "aggregate_results.csv")

    if not os.path.isfile(agg_csv):
        print(f"  [FAIL] Aggregate results not found: {os.path.abspath(agg_csv)}")
        print(f"         Run without --skip-scoring first.")
        sys.exit(1)

    with open(agg_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        results = [r for r in reader if r.get("level") == "source"]

    print(f"  Loaded {len(results)} source-level results.")
    print()

    # -----------------------------------------------------------------------
    # Step 4: Build expectations from the candidates CSV (part2 column)
    # -----------------------------------------------------------------------
    print("Step 4: Building expected outcomes from candidates CSV...")
    print("-" * 70)

    expectations = _build_expectations(candidates_csv)

    expected_yes = sum(1 for v in expectations.values() if v)
    expected_no = sum(1 for v in expectations.values() if not v)
    print(f"  Distinct AAs with expectations: {len(expectations)}")
    print(f"    Expected CANDIDATE (part2=Yes): {expected_yes}")
    print(f"    Expected NOT CANDIDATE (part2=No): {expected_no}")
    print()

    # -----------------------------------------------------------------------
    # Step 5: Compare results vs expectations
    # -----------------------------------------------------------------------
    print("Step 5: Evaluating results against expectations...")
    print("-" * 70)

    false_negatives = []  # expected CANDIDATE, got NOT A CANDIDATE
    false_positives = []  # expected NOT CANDIDATE, got CANDIDATE
    true_positives = []
    true_negatives = []
    unmatched = []        # in results but not in expectations

    for row in results:
        aa = row.get("assigning_authority", "")
        classification = row.get("classification", "")
        is_candidate = classification.startswith("CANDIDATE")

        expected = expectations.get(aa)
        if expected is None:
            unmatched.append(row)
            continue

        if expected and is_candidate:
            true_positives.append(row)
        elif not expected and not is_candidate:
            true_negatives.append(row)
        elif expected and not is_candidate:
            false_negatives.append(row)
        elif not expected and is_candidate:
            false_positives.append(row)

    # -----------------------------------------------------------------------
    # Step 6: Letter generation check
    # -----------------------------------------------------------------------
    print()
    print("Step 6: Checking letter generation...")
    print("-" * 70)

    if LANDSCAPE == "DEV":
        letters_dir = os.path.join("..", "06-Results", "Output", "DEV", "qe_letters")
    else:
        letters_dir = os.path.join("..", "06-Results", "Output", "PROD", "qe_letters")

    if os.path.isdir(letters_dir):
        letters = [f for f in os.listdir(letters_dir) if f.endswith(".html")]
    else:
        letters = []

    candidate_sources = [r for r in results if r.get("classification", "").startswith("CANDIDATE")]

    print(f"  Letters generated: {len(letters)}")
    print(f"  Sources flagged as CANDIDATE: {len(candidate_sources)}")

    letters_match = len(letters) == len(candidate_sources)
    print(f"  Letters match flagged count: {'PASS' if letters_match else 'FAIL'}")
    print()

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    print("=" * 70)
    print(f"  TEST RESULTS — {LANDSCAPE}")
    print("=" * 70)
    print()
    print(f"  True Positives  (correctly flagged as CANDIDATE):   {len(true_positives)}")
    print(f"  True Negatives  (correctly NOT flagged):            {len(true_negatives)}")
    print(f"  False Negatives (missed — should be CANDIDATE):     {len(false_negatives)}")
    print(f"  False Positives (over-flagged — should NOT be):     {len(false_positives)}")
    if unmatched:
        print(f"  Unmatched (in results but no expectation):          {len(unmatched)}")
    print()

    allowed = VARIANCE[LANDSCAPE]
    fn_ok = len(false_negatives) <= allowed["max_false_negatives"]
    fp_ok = len(false_positives) <= allowed["max_false_positives"]

    print(f"  Allowed false negatives: {allowed['max_false_negatives']}  "
          f"| Actual: {len(false_negatives)}  | {'PASS' if fn_ok else 'FAIL'}")
    print(f"  Allowed false positives: {allowed['max_false_positives']}  "
          f"| Actual: {len(false_positives)}  | {'PASS' if fp_ok else 'FAIL'}")
    print(f"  Letters match candidates: {'PASS' if letters_match else 'FAIL'}")
    print()

    # Detail on failures
    if false_negatives:
        print("  FALSE NEGATIVES (should have been flagged):")
        for row in false_negatives:
            print(f"    - {row.get('assigning_authority', '')[:50]:50s} "
                  f"score={row.get('source_score', '?')}/100 "
                  f"class={row.get('classification', '?')}")
        print()

    if false_positives:
        print("  FALSE POSITIVES (should NOT have been flagged):")
        for row in false_positives:
            print(f"    - {row.get('assigning_authority', '')[:50]:50s} "
                  f"score={row.get('source_score', '?')}/100 "
                  f"class={row.get('classification', '?')}")
        print()

    # -----------------------------------------------------------------------
    # Overall verdict
    # -----------------------------------------------------------------------
    print("=" * 70)
    overall = fn_ok and fp_ok and letters_match
    if overall:
        print(f"  OVERALL: PASS")
    else:
        print(f"  OVERALL: FAIL")
        if not fn_ok:
            print(f"    - Too many false negatives "
                  f"({len(false_negatives)} > {allowed['max_false_negatives']})")
        if not fp_ok:
            print(f"    - Too many false positives "
                  f"({len(false_positives)} > {allowed['max_false_positives']})")
        if not letters_match:
            print(f"    - Letter count mismatch "
                  f"({len(letters)} letters vs {len(candidate_sources)} candidates)")
    print("=" * 70)
    print()

    # -----------------------------------------------------------------------
    # Generate HTML report for the developer
    # -----------------------------------------------------------------------
    print("Generating HTML test report...")
    print("-" * 70)

    candidates_csv_stats = {
        "total": len(all_candidate_rows),
        "yes": yes_count,
        "no": no_count,
    }

    _generate_test_report(
        LANDSCAPE, true_positives, true_negatives,
        false_negatives, false_positives, unmatched,
        letters, candidate_sources, allowed, overall,
        candidates_csv_stats, results, expectations
    )
    print()

    sys.exit(0 if overall else 1)


# ============================================================================
# Generate HTML test report
# ============================================================================

def _generate_test_report(landscape, true_positives, true_negatives,
                          false_negatives, false_positives, unmatched,
                          letters, candidate_sources, allowed, overall,
                          candidates_csv_stats, all_results_for_report,
                          expectations_for_report):
    """
    Generate a developer-facing HTML report summarizing test harness results.
    Focus: how accurately does the system score known Part 2 sources as Part 2?
    """
    from datetime import date

    if landscape == "DEV":
        output_dir = os.path.join("..", "06-Results", "Output", "DEV")
    else:
        output_dir = os.path.join("..", "06-Results", "Output", "PROD")

    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"test_harness_report_{date.today().isoformat()}.html")

    tp = len(true_positives)
    tn = len(true_negatives)
    fn = len(false_negatives)
    fp = len(false_positives)
    total_evaluated = tp + tn + fn + fp

    # Accuracy metrics
    accuracy = (tp + tn) / total_evaluated if total_evaluated > 0 else 0
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0  # recall for Part 2
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0  # recall for non-Part 2
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0

    # Status styling
    if overall:
        status_color = "#16a34a"
        status_text = "PASS"
        status_bg = "#f0fdf4"
    else:
        status_color = "#dc2626"
        status_text = "FAIL"
        status_bg = "#fef2f2"

    # Build false negative detail rows
    fn_rows = ""
    for row in false_negatives:
        fn_rows += f"""<tr>
            <td>{row.get('assigning_authority', '')}</td>
            <td>{row.get('custodian_org_name', '')}</td>
            <td>{row.get('qe', '')}</td>
            <td>{row.get('source_score', '')}</td>
            <td>{row.get('classification', '')}</td>
            <td>{row.get('top_sud_codes', '')[:80]}</td>
        </tr>"""

    # Build false positive detail rows
    fp_rows = ""
    for row in false_positives:
        fp_rows += f"""<tr>
            <td>{row.get('assigning_authority', '')}</td>
            <td>{row.get('custodian_org_name', '')}</td>
            <td>{row.get('qe', '')}</td>
            <td>{row.get('source_score', '')}</td>
            <td>{row.get('classification', '')}</td>
            <td>{row.get('top_sud_codes', '')[:80]}</td>
        </tr>"""

    fn_section = ""
    if false_negatives:
        fn_section = f"""
        <div class="panel warn">
            <h3>False Negatives — Known Part 2 Sources We Missed</h3>
            <p>These sources are known to be 42 CFR (part2=Yes) but our code scored them
               as NOT A CANDIDATE. This means our checkers are too strict or the CCDs lack
               the expected signals.</p>
            <table>
                <thead><tr><th>AA</th><th>Custodian Org</th><th>QE</th><th>Score</th><th>Classification</th><th>Top Codes</th></tr></thead>
                <tbody>{fn_rows}</tbody>
            </table>
        </div>"""

    fp_section = ""
    if false_positives:
        fp_section = f"""
        <div class="panel warn">
            <h3>False Positives — Non-Part-2 Sources We Incorrectly Flagged</h3>
            <p>These sources are known to be general care (part2=No) but our code scored
               them as CANDIDATE. This means our checkers are too loose for these cases.</p>
            <table>
                <thead><tr><th>AA</th><th>Custodian Org</th><th>QE</th><th>Score</th><th>Classification</th><th>Top Codes</th></tr></thead>
                <tbody>{fp_rows}</tbody>
            </table>
        </div>"""

    # Build the full source detail table (every AA evaluated)
    all_source_rows = ""
    for row in all_results_for_report:
        aa = row.get("assigning_authority", "")
        org = row.get("custodian_org_name", "")
        addr = row.get("custodian_org_address", "")[:50]
        qe_val = row.get("qe", "")
        score = row.get("source_score", "")
        prev = row.get("sud_prevalence", "")
        strong = row.get("strong_signal_prevalence", "")
        classification = row.get("classification", "")
        ccds = row.get("ccds_sampled", "")
        top = row.get("top_sud_codes", "")[:60]

        # Determine expected and actual
        expected = expectations_for_report.get(aa)
        if expected is None:
            expected_label = "?"
        elif expected:
            expected_label = "CANDIDATE"
        else:
            expected_label = "NOT CANDIDATE"

        is_candidate = classification.startswith("CANDIDATE")
        if expected is not None and expected == is_candidate:
            result_class = "pass"
            result_label = "CORRECT"
        elif expected is None:
            result_class = ""
            result_label = "—"
        else:
            result_class = "fail"
            result_label = "WRONG"

        all_source_rows += f"""<tr>
            <td>{org if org else aa}</td>
            <td>{addr}</td>
            <td>{qe_val}</td>
            <td>{ccds}</td>
            <td>{score}</td>
            <td>{prev}</td>
            <td>{strong}</td>
            <td>{classification}</td>
            <td>{expected_label}</td>
            <td class="{result_class}">{result_label}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>42 CFR Test Harness Report — {landscape} — {date.today().isoformat()}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f8f6f2; margin: 0; color: #2f2218; }}
        .banner {{ background: {status_color}; color: #fff; text-align: center; padding: 0.8rem 1rem; font-weight: 700; font-size: 1.1em; }}
        header {{ background: linear-gradient(130deg, #3d2b1f 0%, #6a4524 100%); color: #fff; padding: 1.5rem 1.2rem; text-align: center; }}
        header h1 {{ margin: 0; color: #f7d27d; font-size: 1.4em; }}
        header p {{ margin: 0.4rem 0 0; color: #e6cfaa; font-size: 0.9em; }}
        .wrap {{ max-width: 900px; margin: 1.2rem auto 2rem; padding: 0 1.2rem; }}
        .panel {{ background: #fffdf8; border-radius: 0.8rem; box-shadow: 0 4px 14px rgba(61,43,31,0.08); border-top: 4px solid #c8a84b; padding: 1rem 1.2rem; margin-bottom: 0.9rem; }}
        .panel.warn {{ border-top-color: #dc2626; }}
        .panel h2 {{ margin: 0 0 0.5rem; font-size: 1.05em; color: #3d2b1f; }}
        .panel h3 {{ margin: 0.6rem 0 0.3rem; font-size: 0.95em; color: #5c3a1e; }}
        .panel p {{ color: #4b3a2c; line-height: 1.6; font-size: 0.9em; }}
        .stat-grid {{ display: grid; gap: 0.5rem; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 0.5rem 0; }}
        .stat-box {{ background: #fff7de; border: 1px solid #e9ca82; border-radius: 0.5rem; padding: 0.5rem; text-align: center; }}
        .stat-box .num {{ font-size: 1.6em; font-weight: 800; color: #5c3a1e; }}
        .stat-box .lbl {{ font-size: 0.68em; text-transform: uppercase; letter-spacing: 0.7px; color: #815b1d; font-weight: 700; }}
        .verdict {{ background: {status_bg}; border: 2px solid {status_color}; border-radius: 0.7rem; padding: 1rem; text-align: center; margin: 0.8rem 0; }}
        .verdict .big {{ font-size: 2em; font-weight: 800; color: {status_color}; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.82em; margin-top: 0.4rem; }}
        th, td {{ border: 1px solid #e6d9c4; padding: 0.4em 0.5em; text-align: left; }}
        th {{ background: #f9f1e2; font-weight: 700; color: #3d2b1f; font-size: 0.8em; text-transform: uppercase; }}
        .pass {{ color: #16a34a; font-weight: 700; }}
        .fail {{ color: #dc2626; font-weight: 700; }}
        .footer {{ text-align: center; color: #b09060; margin: 1.5rem 0 1rem; font-size: 0.8em; }}
    </style>
</head>
<body>

<div class="banner">TEST HARNESS — {status_text}</div>

<header>
    <h1>42 CFR Candidate Identification — Test Results</h1>
    <p>{landscape} | {date.today().isoformat()} | {total_evaluated} sources evaluated</p>
</header>

<div class="wrap">

    <div class="verdict">
        <div class="big">{status_text}</div>
        <p style="margin:0.3rem 0 0; font-size:0.9em; color:#4b3a2c;">
            {'All checks within tolerance.' if overall else 'One or more checks exceeded tolerance.'}
        </p>
    </div>

    <section class="panel">
        <h2>Scoring Accuracy</h2>
        <p>How well does the system identify known Part 2 sources as Part 2?</p>
        <div class="stat-grid">
            <div class="stat-box"><div class="num">{accuracy:.0%}</div><div class="lbl">Overall Accuracy</div></div>
            <div class="stat-box"><div class="num">{sensitivity:.0%}</div><div class="lbl">Sensitivity<br>(Part 2 Detection Rate)</div></div>
            <div class="stat-box"><div class="num">{specificity:.0%}</div><div class="lbl">Specificity<br>(Non-Part-2 Correct)</div></div>
            <div class="stat-box"><div class="num">{precision:.0%}</div><div class="lbl">Precision<br>(Flagged = Truly Part 2)</div></div>
        </div>
        <p style="font-size:0.82em; color:#6b5a48; margin-top:0.5rem;">
            <strong>Sensitivity</strong> is the key metric — it answers: "Of all known Part 2 sources,
            what % did our code correctly identify?" A sensitivity of 100% means we didn't miss any.
        </p>
    </section>

    <section class="panel">
        <h2>Confusion Matrix</h2>
        <table>
            <thead>
                <tr><th></th><th>Scored as CANDIDATE</th><th>Scored as NOT A CANDIDATE</th></tr>
            </thead>
            <tbody>
                <tr>
                    <td style="font-weight:700;">Known Part 2 (part2=Yes)</td>
                    <td class="pass">True Positive: {tp}</td>
                    <td class="{'fail' if fn > 0 else 'pass'}">False Negative: {fn}</td>
                </tr>
                <tr>
                    <td style="font-weight:700;">Known Non-Part-2 (part2=No)</td>
                    <td class="{'fail' if fp > 0 else 'pass'}">False Positive: {fp}</td>
                    <td class="pass">True Negative: {tn}</td>
                </tr>
            </tbody>
        </table>
    </section>

    <section class="panel">
        <h2>Tolerance Check</h2>
        <table>
            <thead><tr><th>Metric</th><th>Allowed</th><th>Actual</th><th>Result</th></tr></thead>
            <tbody>
                <tr>
                    <td>False Negatives (missed Part 2)</td>
                    <td>{allowed['max_false_negatives']}</td>
                    <td>{fn}</td>
                    <td class="{'pass' if fn <= allowed['max_false_negatives'] else 'fail'}">
                        {'PASS' if fn <= allowed['max_false_negatives'] else 'FAIL'}</td>
                </tr>
                <tr>
                    <td>False Positives (wrongly flagged)</td>
                    <td>{allowed['max_false_positives']}</td>
                    <td>{fp}</td>
                    <td class="{'pass' if fp <= allowed['max_false_positives'] else 'fail'}">
                        {'PASS' if fp <= allowed['max_false_positives'] else 'FAIL'}</td>
                </tr>
                <tr>
                    <td>Letters match candidates</td>
                    <td>Exact</td>
                    <td>{len(letters)} letters / {len(candidate_sources)} candidates</td>
                    <td class="{'pass' if len(letters) == len(candidate_sources) else 'fail'}">
                        {'PASS' if len(letters) == len(candidate_sources) else 'FAIL'}</td>
                </tr>
            </tbody>
        </table>
    </section>

    <section class="panel">
        <h2>Input Summary</h2>
        <table>
            <tr><td style="font-weight:700; width:200px;">Landscape</td><td>{landscape}</td></tr>
            <tr><td style="font-weight:700;">Candidates CSV rows</td><td>{candidates_csv_stats['total']}</td></tr>
            <tr><td style="font-weight:700;">Part2=Yes rows</td><td>{candidates_csv_stats['yes']}</td></tr>
            <tr><td style="font-weight:700;">Part2=No rows</td><td>{candidates_csv_stats['no']}</td></tr>
            <tr><td style="font-weight:700;">Distinct AAs evaluated</td><td>{total_evaluated}</td></tr>
            <tr><td style="font-weight:700;">Letters generated</td><td>{len(letters)}</td></tr>
        </table>
    </section>

    {fn_section}
    {fp_section}

    <section class="panel">
        <h2>All Sources Evaluated</h2>
        <p>Every assigning authority scored in this run, with real facility identity from the CCD:</p>
        <table>
            <thead>
                <tr>
                    <th>Facility Name</th>
                    <th>Address</th>
                    <th>QE</th>
                    <th>CCDs</th>
                    <th>Score</th>
                    <th>SUD Prev</th>
                    <th>Strong Prev</th>
                    <th>Classification</th>
                    <th>Expected</th>
                    <th>Result</th>
                </tr>
            </thead>
            <tbody>{all_source_rows}</tbody>
        </table>
    </section>

</div>

<div class="footer">
    Generated by test_harness.py | {date.today().isoformat()}
</div>

</body>
</html>"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  [OK] HTML test report: {report_path}")


# ============================================================================
# Rebuild DEV candidates CSV
# ============================================================================

def _rebuild_dev_candidates():
    """
    Call make_dev_candidates_42cfr.py to rebuild the DEV candidates CSV
    fresh from S3. Sample size is controlled in that script, not here.
    """
    import subprocess
    result = subprocess.run(
        [sys.executable, "make_dev_candidates_42cfr.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True,
        text=True,
    )
    # Print its output
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")
    if result.returncode != 0:
        print(f"  [ERROR] make_dev_candidates_42cfr.py failed (exit {result.returncode})")
        if result.stderr:
            print(f"  {result.stderr[:500]}")
        sys.exit(1)


# ============================================================================
# Build expectations (same logic for DEV and PROD)
# ============================================================================

def _build_expectations(candidates_csv):
    """
    Read the candidates CSV and build a dict of AA → expected_is_candidate.
    Uses the 'part2' column as ground truth:
      part2=Yes → should be CANDIDATE (True)
      part2=No  → should NOT be CANDIDATE (False)

    Same logic for both DEV and PROD — the CSV format is identical.
    """
    expectations = {}

    with open(candidates_csv, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            aa = row.get("assigning_authority", "").strip()
            part2 = row.get("part2", "").strip().lower()

            if not aa or not part2:
                continue

            if part2 == "yes":
                expectations[aa] = True
            elif part2 == "no":
                expectations[aa] = False

    return expectations


# ============================================================================
# Entry point
# ============================================================================
if __name__ == "__main__":
    main()
