"""
generate_report.py — Generate HTML Coding Quality Reports from Scored Results

Reads scored JSON files, aggregates by QE and Assigning Authority,
and produces styled HTML reports:
  - summary.html: cross-QE overview
  - report_<qe>.html: per-QE detail with source matrix

Sources sorted WORST first (lowest % standard at top).
Color-coded cells: green (>=90%), yellow (60-89%), red (<60%), gray (absent).

Output goes to DEV-Output/ or PROD-Output/ depending on which scored_results
directory is found.
"""

import os
import json
from collections import defaultdict
from segment_mapping import ALL_SEGMENT_KEYS

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Default to DEV. Override with --output-dir argument.
# DEV pipeline passes: --output-dir DEV-Output
# PROD pipeline passes: --output-dir PROD-Output
import argparse

def get_output_dir():
    parser = argparse.ArgumentParser(description="Generate HTML coding quality reports")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (e.g., DEV-Output or PROD-Output)")
    args, _ = parser.parse_known_args()
    
    if args.output_dir:
        return os.path.join(BASE_DIR, args.output_dir)
    
    # Auto-detect: prefer PROD if it has results, else DEV
    prod_scored = os.path.join(BASE_DIR, "PROD-Output", "scored_results")
    if os.path.exists(prod_scored) and any(f.endswith("_scored.json") for f in os.listdir(prod_scored)):
        return os.path.join(BASE_DIR, "PROD-Output")
    return os.path.join(BASE_DIR, "DEV-Output")

OUTPUT_DIR = get_output_dir()
SCORED_DIR = os.path.join(OUTPUT_DIR, "scored_results")


# =============================================================================
# HELPER: Color coding
# =============================================================================

def pct_color(pct):
    """Return background color for a percentage standard value."""
    if pct is None:
        return "#f3f4f6"  # Gray — absent
    elif pct >= 65:
        return "#d1fae5"  # Green — well-coded
    elif pct >= 40:
        return "#fef3c7"  # Yellow — mixed
    else:
        return "#fee2e2"  # Red — poorly coded


def pct_label(pct):
    """Return label for a percentage."""
    if pct is None:
        return "Absent"
    return f"{pct:.0f}%"


def tier_for_pct(pct):
    """
    Assign tier based on overall standard %.
    Calibrated to Synthea DEV data characteristics (~70% ceiling).
    """
    if pct >= 65:
        return "A"
    elif pct >= 55:
        return "B"
    elif pct >= 40:
        return "C"
    else:
        return "D"


# =============================================================================
# HELPER: Load and aggregate scored results
# =============================================================================

def load_scored_results(scored_dir):
    """
    Load all scored JSONs and aggregate by QE > Assigning Authority.
    
    Returns:
        dict: {qe: {aa: {"docs": [...], "segments": {...}}}}
    """
    data = defaultdict(lambda: defaultdict(lambda: {"docs": [], "segments": defaultdict(list)}))
    
    json_files = [f for f in os.listdir(scored_dir) if f.endswith("_scored.json")]
    
    for filename in json_files:
        filepath = os.path.join(scored_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            result = json.load(f)
        
        source = result.get("source", {})
        qe = source.get("qe", "(unknown)")
        aa = source.get("assigning_authority", "(unknown)")
        
        data[qe][aa]["docs"].append(result)
        
        # Aggregate per-segment
        domain_counts = result.get("domain_counts", {})
        for seg_key in ALL_SEGMENT_KEYS:
            if seg_key in domain_counts:
                data[qe][aa]["segments"][seg_key].append(domain_counts[seg_key])
    
    return data


def compute_source_stats(source_data):
    """
    Compute aggregate stats for one source (one AA).
    
    Returns:
        dict with overall_pct, per-segment pct, tier, doc_count, weakest_segment
    """
    total_elements = 0
    total_standard = 0
    total_local = 0
    total_missing = 0
    
    segment_pcts = {}
    
    for seg_key in ALL_SEGMENT_KEYS:
        seg_docs = source_data["segments"].get(seg_key, [])
        seg_total = sum(d["total"] for d in seg_docs)
        seg_standard = sum(d["standard"] for d in seg_docs)
        seg_absent_count = sum(1 for d in seg_docs if d.get("section_absent"))
        
        total_elements += seg_total
        total_standard += seg_standard
        total_local += sum(d["local"] for d in seg_docs)
        total_missing += sum(d["missing"] for d in seg_docs)
        
        if seg_total > 0:
            segment_pcts[seg_key] = 100.0 * seg_standard / seg_total
        elif seg_absent_count == len(seg_docs) and len(seg_docs) > 0:
            segment_pcts[seg_key] = None  # All absent
        else:
            segment_pcts[seg_key] = None  # No data
    
    overall_pct = 100.0 * total_standard / total_elements if total_elements > 0 else 0
    tier = tier_for_pct(overall_pct)
    
    # Find weakest segment (lowest non-None pct)
    valid_segments = {k: v for k, v in segment_pcts.items() if v is not None}
    weakest = min(valid_segments, key=valid_segments.get) if valid_segments else "(none)"
    
    return {
        "overall_pct": overall_pct,
        "tier": tier,
        "doc_count": len(source_data["docs"]),
        "total_elements": total_elements,
        "total_standard": total_standard,
        "total_local": total_local,
        "total_missing": total_missing,
        "segment_pcts": segment_pcts,
        "weakest_segment": weakest,
    }


# =============================================================================
# HTML GENERATION
# =============================================================================

HTML_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
body {{ font-family: 'Inter', Arial, sans-serif; background: #f8f5f0; margin: 0; color: #2f2218; }}
header {{ background: linear-gradient(130deg, #3d2b1f 0%, #6a4524 100%); color: #fff; padding: 1.8rem 1.2rem; text-align: center; }}
header h1 {{ margin: 0; color: #f7d27d; font-size: 1.7em; }}
header p {{ margin: 0.5rem auto 0; color: #e6cfaa; max-width: 800px; }}
.wrap {{ max-width: 1200px; margin: 1rem auto 2rem; padding: 0 1rem; }}
.panel {{ background: #fffdf8; border-radius: 0.8rem; box-shadow: 0 4px 16px rgba(61,43,31,0.1); border-top: 4px solid #c8a84b; padding: 1rem 1.2rem; margin-bottom: 1rem; }}
.panel h2 {{ margin: 0 0 0.5rem; font-size: 1.1em; color: #3d2b1f; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.82em; margin-top: 0.5rem; }}
th, td {{ border: 1px solid #e6d9c4; padding: 0.4em 0.5em; text-align: center; }}
th {{ background: #f9f1e2; font-weight: 700; color: #3d2b1f; font-size: 0.8em; text-transform: uppercase; }}
td.aa {{ text-align: left; font-weight: 600; min-width: 180px; }}
td.tier {{ font-weight: 800; }}
.tier-A {{ color: #065f46; }} .tier-B {{ color: #92400e; }} .tier-C {{ color: #9a3412; }} .tier-D {{ color: #991b1b; }}
.nav {{ margin: 1rem 0; }} .nav a {{ margin-right: 1rem; color: #5c3a1e; font-weight: 600; }}
.footer {{ text-align: center; color: #b09060; margin: 2rem 0 1rem; font-size: 0.85em; }}
</style>
</head>
<body>
"""

HTML_FOOTER = """
<div class="footer">CCD Coding Quality Report — Generated by PDRExploreCode</div>
</body>
</html>
"""


def generate_qe_report(qe, sources_stats, output_dir):
    """Generate one HTML report for a QE."""
    filename = f"report_{qe.replace(' ', '_').lower()}.html"
    filepath = os.path.join(output_dir, filename)
    
    # Sort sources: worst first (ascending by overall_pct)
    sorted_sources = sorted(sources_stats.items(), key=lambda x: x[1]["overall_pct"])
    
    # Short segment labels for column headers
    seg_labels = {
        "allergies": "Allerg", "assessment": "Assess", "care_plan": "CarePl",
        "chief_complaint": "Chief", "demographics": "Demo", "encounters": "Enctr",
        "functional_status": "FuncSt", "immunizations": "Immun", "labs_results": "Labs",
        "medications": "Meds", "problems": "Probs", "procedures": "Procs",
        "social_history": "SocHx", "vitals": "Vitals",
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        title = f"Coding Quality: {qe}"
        f.write(HTML_HEADER.format(title=title))
        f.write(f"<header><h1>{qe} — Coding Quality Report</h1>")
        f.write(f"<p>{len(sorted_sources)} sources evaluated, sorted worst-first</p></header>\n")
        f.write('<div class="wrap">\n')
        
        # Navigation
        f.write('<div class="nav"><a href="summary.html">Back to Summary</a></div>\n')
        
        # QE Summary panel
        total_docs = sum(s["doc_count"] for _, s in sorted_sources)
        avg_pct = sum(s["overall_pct"] for _, s in sorted_sources) / len(sorted_sources) if sorted_sources else 0
        tier_dist = defaultdict(int)
        for _, s in sorted_sources:
            tier_dist[s["tier"]] += 1
        
        f.write('<section class="panel"><h2>QE Summary</h2>\n')
        f.write(f'<p>Sources: {len(sorted_sources)} | CCDs scored: {total_docs} | ')
        f.write(f'Avg standard: {avg_pct:.0f}% | ')
        f.write(f'Tiers: A={tier_dist["A"]} B={tier_dist["B"]} C={tier_dist["C"]} D={tier_dist["D"]}</p>\n')
        f.write('</section>\n')
        
        # Source matrix table
        f.write('<section class="panel"><h2>Source Detail (worst first)</h2>\n')
        f.write("<table><thead><tr>")
        f.write("<th>Assigning Authority</th><th>Tier</th><th>Overall</th><th>Docs</th>")
        for seg_key in ALL_SEGMENT_KEYS:
            f.write(f"<th>{seg_labels.get(seg_key, seg_key[:5])}</th>")
        f.write("<th>Weakest</th>")
        f.write("</tr></thead><tbody>\n")
        
        for aa, stats in sorted_sources:
            f.write("<tr>")
            f.write(f'<td class="aa">{aa}</td>')
            f.write(f'<td class="tier tier-{stats["tier"]}">{stats["tier"]}</td>')
            
            # Overall %
            bg = pct_color(stats["overall_pct"])
            f.write(f'<td style="background:{bg}">{stats["overall_pct"]:.0f}%</td>')
            f.write(f'<td>{stats["doc_count"]}</td>')
            
            # Per-segment cells
            for seg_key in ALL_SEGMENT_KEYS:
                pct = stats["segment_pcts"].get(seg_key)
                bg = pct_color(pct)
                label = pct_label(pct)
                f.write(f'<td style="background:{bg}">{label}</td>')
            
            f.write(f'<td>{stats["weakest_segment"]}</td>')
            f.write("</tr>\n")
        
        f.write("</tbody></table>\n</section>\n")
        f.write("</div>\n")
        f.write(HTML_FOOTER)
    
    return filename


def generate_summary(qe_summaries, output_dir):
    """Generate the cross-QE summary HTML."""
    filepath = os.path.join(output_dir, "summary.html")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(HTML_HEADER.format(title="Coding Quality Summary"))
        f.write("<header><h1>CCD Coding Quality — Summary</h1>")
        f.write("<p>All QEs at a glance, sorted by average standard %</p></header>\n")
        f.write('<div class="wrap">\n')
        
        # Sort QEs by avg standard (worst first)
        sorted_qes = sorted(qe_summaries.items(), key=lambda x: x[1]["avg_pct"])
        
        f.write('<section class="panel"><h2>QE Overview</h2>\n')
        f.write("<table><thead><tr>")
        f.write("<th>QE</th><th>Sources</th><th>CCDs</th><th>Avg Standard %</th>")
        f.write("<th>Tier A</th><th>Tier B</th><th>Tier C</th><th>Tier D</th>")
        f.write("<th>Report</th>")
        f.write("</tr></thead><tbody>\n")
        
        for qe, summary in sorted_qes:
            bg = pct_color(summary["avg_pct"])
            report_file = f"report_{qe.replace(' ', '_').lower()}.html"
            f.write("<tr>")
            f.write(f'<td class="aa">{qe}</td>')
            f.write(f'<td>{summary["source_count"]}</td>')
            f.write(f'<td>{summary["doc_count"]}</td>')
            f.write(f'<td style="background:{bg}">{summary["avg_pct"]:.0f}%</td>')
            f.write(f'<td>{summary["tier_A"]}</td>')
            f.write(f'<td>{summary["tier_B"]}</td>')
            f.write(f'<td>{summary["tier_C"]}</td>')
            f.write(f'<td>{summary["tier_D"]}</td>')
            f.write(f'<td><a href="{report_file}">View</a></td>')
            f.write("</tr>\n")
        
        f.write("</tbody></table>\n</section>\n")
        f.write("</div>\n")
        f.write(HTML_FOOTER)


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 75)
    print("CCD Coding Quality — HTML Report Generator")
    print("=" * 75)
    print()
    print(f"  Scored results: {SCORED_DIR}")
    print(f"  Output dir:     {OUTPUT_DIR}")
    print()
    
    if not os.path.exists(SCORED_DIR):
        print("ERROR: Scored results directory not found.")
        print("  Run score_ccd_coding_quality.py first.")
        return
    
    # Load and aggregate
    print("Loading scored results...")
    data = load_scored_results(SCORED_DIR)
    
    total_qes = len(data)
    total_sources = sum(len(sources) for sources in data.values())
    print(f"  {total_qes} QEs, {total_sources} sources")
    print()
    
    # Compute stats per source
    print("Computing source statistics...")
    qe_summaries = {}
    
    for qe, sources in data.items():
        sources_stats = {}
        for aa, source_data in sources.items():
            sources_stats[aa] = compute_source_stats(source_data)
        
        # Generate per-QE report
        report_file = generate_qe_report(qe, sources_stats, OUTPUT_DIR)
        print(f"  Generated: {report_file} ({len(sources_stats)} sources)")
        
        # Build QE summary
        tier_dist = defaultdict(int)
        for stats in sources_stats.values():
            tier_dist[stats["tier"]] += 1
        
        avg_pct = sum(s["overall_pct"] for s in sources_stats.values()) / len(sources_stats) if sources_stats else 0
        total_docs = sum(s["doc_count"] for s in sources_stats.values())
        
        qe_summaries[qe] = {
            "source_count": len(sources_stats),
            "doc_count": total_docs,
            "avg_pct": avg_pct,
            "tier_A": tier_dist["A"],
            "tier_B": tier_dist["B"],
            "tier_C": tier_dist["C"],
            "tier_D": tier_dist["D"],
        }
    
    # Generate summary
    generate_summary(qe_summaries, OUTPUT_DIR)
    print(f"  Generated: summary.html")
    
    print()
    print("=" * 75)
    print("DONE!")
    print("=" * 75)
    print()
    print(f"Reports written to: {OUTPUT_DIR}")
    print(f"  summary.html + {total_qes} per-QE reports")
    print()
    print("Open summary.html in a browser to view results.")


if __name__ == "__main__":
    main()
