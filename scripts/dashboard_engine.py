"""Dashboard Engine for CodeLens — Generate self-contained HTML dashboard.

Produces a single HTML file with:
- Overview Panel (health score, findings, file/function counts)
- Complexity Heatmap
- Finding Distribution Charts (pie, bar, treemap)
- Dependency Graph (interactive SVG)
- Security Overview
- Historical Trends (if history data available)
- Comparison View (if two snapshots specified)

All charts use vanilla JS + SVG. No external dependencies.
Dark mode by default. Responsive. Print-friendly.
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from utils import logger


def generate_dashboard(
    workspace: str,
    output_path: Optional[str] = None,
    compare_snapshots: Optional[tuple] = None,
) -> Dict[str, Any]:
    """Generate a self-contained HTML dashboard for the workspace.

    Args:
        workspace: Path to the workspace
        output_path: Where to save the HTML file (default: .codelens/dashboard.html)
        compare_snapshots: Tuple of (snapshot1_file, snapshot2_file) for comparison view

    Returns:
        Dict with status and path to the generated file.
    """
    workspace = os.path.abspath(workspace)

    # Collect metrics from all engines
    from history_engine import collect_metrics, list_snapshots, compare_snapshots as cmp_snapshots, get_trend_data
    metrics = collect_metrics(workspace, {})

    # Get trend data
    trend_data = get_trend_data(workspace)

    # Comparison data
    comparison_data = None
    if compare_snapshots:
        comparison_data = cmp_snapshots(workspace, compare_snapshots[0], compare_snapshots[1])

    # Build dashboard data
    dashboard_data = {
        "metrics": metrics,
        "trends": trend_data.get("trends", {}),
        "trend_snapshots": trend_data.get("snapshots", 0),
        "comparison": comparison_data,
        "workspace_name": os.path.basename(workspace),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Generate HTML
    html = _build_html(dashboard_data)

    # Determine output path
    if not output_path:
        codelens_dir = os.path.join(workspace, '.codelens')
        os.makedirs(codelens_dir, exist_ok=True)
        output_path = os.path.join(codelens_dir, 'dashboard.html')

    # Write the file
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
    except IOError as e:
        return {"status": "error", "error": f"Failed to write dashboard: {e}"}

    return {
        "status": "ok",
        "dashboard_path": os.path.abspath(output_path),
        "workspace": workspace,
        "health_score": metrics.get("health_score", 0),
        "total_findings": metrics.get("total_findings", 0),
    }


def _health_color(score: float) -> str:
    """Return color based on health score."""
    if score >= 70:
        return "#22c55e"  # green
    elif score >= 40:
        return "#eab308"  # yellow
    else:
        return "#ef4444"  # red


def _severity_color(severity: str) -> str:
    """Return color based on severity level."""
    colors = {
        "critical": "#ef4444",
        "high": "#f97316",
        "warning": "#f97316",
        "medium": "#eab308",
        "low": "#3b82f6",
        "info": "#6b7280",
    }
    return colors.get(severity.lower(), "#6b7280")


def _build_html(data: Dict[str, Any]) -> str:
    """Build the complete self-contained HTML dashboard."""
    metrics = data["metrics"]
    trends = data["trends"]
    workspace_name = data["workspace_name"]
    generated_at = data["generated_at"]
    trend_count = data["trend_snapshots"]
    comparison = data.get("comparison")

    health_score = metrics.get("health_score", 0)
    total_findings = metrics.get("total_findings", 0)
    findings_severity = metrics.get("findings_by_severity", {})
    avg_complexity = metrics.get("avg_complexity", 0)
    files_scanned = metrics.get("files_scanned", 0)
    total_functions = metrics.get("total_functions", 0)
    secrets_count = metrics.get("secrets_count", 0)
    dead_code_count = metrics.get("dead_code_count", 0)
    circular_count = metrics.get("circular_deps_count", 0)
    perf_count = metrics.get("perf_hints_count", 0)
    vuln_count = metrics.get("vulnerability_count", 0)
    top_complex = metrics.get("top_complex_functions", [])
    dep_graph = metrics.get("dependency_graph", {"nodes": [], "edges": []})
    findings_by_cat = metrics.get("findings_by_category", {})
    vulnerabilities = metrics.get("vulnerabilities", [])
    secrets_by_sev = metrics.get("secrets_by_severity", {})

    # Serialize data for JS
    metrics_json = json.dumps(metrics, ensure_ascii=False)
    trends_json = json.dumps(trends, ensure_ascii=False)
    comparison_json = json.dumps(comparison, ensure_ascii=False) if comparison else "null"
    dep_graph_json = json.dumps(dep_graph, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CodeLens Dashboard — {workspace_name}</title>
<style>
/* ─── Reset & Base ──────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --bg-card: #1e293b;
  --bg-card-hover: #334155;
  --border: #334155;
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --accent: #3b82f6;
  --accent-hover: #2563eb;
  --green: #22c55e;
  --yellow: #eab308;
  --red: #ef4444;
  --orange: #f97316;
  --blue: #3b82f6;
  --purple: #8b5cf6;
  --cyan: #06b6d4;
  --radius: 12px;
  --shadow: 0 4px 6px -1px rgba(0,0,0,0.3), 0 2px 4px -2px rgba(0,0,0,0.2);
}}

body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  line-height: 1.6;
  min-height: 100vh;
}}

/* ─── Header ────────────────────────────────────────────── */
.header {{
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border-bottom: 1px solid var(--border);
  padding: 24px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}}

.header h1 {{
  font-size: 28px;
  font-weight: 700;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}

.header-meta {{
  color: var(--text-secondary);
  font-size: 14px;
}}

/* ─── Navigation ────────────────────────────────────────── */
.nav {{
  display: flex;
  gap: 8px;
  padding: 12px 32px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  flex-wrap: wrap;
}}

.nav button {{
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
  white-space: nowrap;
}}

.nav button:hover, .nav button.active {{
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}}

/* ─── Main Content ──────────────────────────────────────── */
.main {{
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px 32px;
}}

.section {{
  display: none;
}}

.section.active {{
  display: block;
}}

/* ─── Cards ─────────────────────────────────────────────── */
.card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  box-shadow: var(--shadow);
  margin-bottom: 20px;
  transition: border-color 0.2s;
}}

.card:hover {{
  border-color: var(--accent);
}}

.card-title {{
  font-size: 16px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 16px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}

/* ─── Grid layouts ──────────────────────────────────────── */
.grid-4 {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}}

.grid-2 {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}}

/* ─── Health Score ──────────────────────────────────────── */
.health-score {{
  text-align: center;
}}

.health-ring {{
  position: relative;
  width: 180px;
  height: 180px;
  margin: 0 auto 16px;
}}

.health-ring svg {{
  transform: rotate(-90deg);
}}

.health-ring .score-text {{
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 48px;
  font-weight: 800;
}}

.health-label {{
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 4px;
}}

/* ─── Metric Cards ──────────────────────────────────────── */
.metric-value {{
  font-size: 36px;
  font-weight: 800;
  line-height: 1.2;
}}

.metric-label {{
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}}

.metric-delta {{
  font-size: 12px;
  margin-top: 2px;
}}

.metric-delta.positive {{ color: var(--green); }}
.metric-delta.negative {{ color: var(--red); }}

/* ─── Severity bars ─────────────────────────────────────── */
.severity-bar {{
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  gap: 12px;
}}

.severity-label {{
  width: 70px;
  font-size: 13px;
  color: var(--text-secondary);
  text-align: right;
}}

.severity-track {{
  flex: 1;
  height: 24px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}}

.severity-fill {{
  height: 100%;
  border-radius: 4px;
  transition: width 0.8s ease;
  min-width: 2px;
}}

.severity-count {{
  width: 40px;
  font-size: 13px;
  font-weight: 600;
}}

/* ─── Complexity heatmap ────────────────────────────────── */
.heatmap-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
}}

.heatmap-cell {{
  border-radius: 8px;
  padding: 12px 8px;
  text-align: center;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  position: relative;
}}

.heatmap-cell:hover {{
  transform: scale(1.05);
  box-shadow: 0 0 12px rgba(59,130,246,0.3);
  z-index: 10;
}}

.heatmap-cell .cell-name {{
  font-size: 11px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

.heatmap-cell .cell-score {{
  font-size: 18px;
  font-weight: 800;
}}

.heatmap-cell .cell-label {{
  font-size: 10px;
  opacity: 0.7;
}}

/* ─── Tooltip ───────────────────────────────────────────── */
.tooltip {{
  display: none;
  position: fixed;
  background: #1e293b;
  border: 1px solid var(--accent);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 13px;
  z-index: 1000;
  max-width: 300px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5);
  pointer-events: none;
}}

.tooltip.visible {{ display: block; }}

/* ─── SVG Chart containers ──────────────────────────────── */
.chart-container {{
  position: relative;
  width: 100%;
  min-height: 300px;
}}

.chart-container svg {{
  width: 100%;
  height: 100%;
}}

/* ─── Dependency Graph ──────────────────────────────────── */
#dep-graph-container {{
  width: 100%;
  height: 500px;
  position: relative;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-primary);
}}

#dep-graph-container svg {{
  width: 100%;
  height: 100%;
}}

.dep-node {{
  cursor: pointer;
}}

.dep-node circle {{
  transition: r 0.2s;
}}

.dep-node:hover circle {{
  r: 16;
}}

/* ─── Comparison ────────────────────────────────────────── */
.compare-row {{
  display: grid;
  grid-template-columns: 1fr 80px 1fr;
  gap: 8px;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}}

.compare-value {{
  font-size: 20px;
  font-weight: 700;
}}

.compare-delta {{
  text-align: center;
  font-size: 14px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 4px;
}}

.compare-delta.improved {{ background: rgba(34,197,94,0.15); color: var(--green); }}
.compare-delta.degraded {{ background: rgba(239,68,68,0.15); color: var(--red); }}
.compare-delta.unchanged {{ background: rgba(100,116,139,0.15); color: var(--text-muted); }}

/* ─── Security card items ───────────────────────────────── */
.sec-item {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}}

.sec-item:last-child {{ border-bottom: none; }}

.sec-badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}}

.sec-badge.critical {{ background: rgba(239,68,68,0.2); color: var(--red); }}
.sec-badge.high {{ background: rgba(249,115,22,0.2); color: var(--orange); }}
.sec-badge.medium {{ background: rgba(234,179,8,0.2); color: var(--yellow); }}
.sec-badge.low {{ background: rgba(59,130,246,0.2); color: var(--blue); }}

/* ─── Top functions table ───────────────────────────────── */
.fn-table {{
  width: 100%;
  border-collapse: collapse;
}}

.fn-table th {{
  text-align: left;
  padding: 10px 12px;
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}}

.fn-table td {{
  padding: 10px 12px;
  font-size: 13px;
  border-bottom: 1px solid rgba(51,65,85,0.5);
}}

.fn-table tr:hover td {{
  background: rgba(59,130,246,0.05);
}}

/* ─── Responsive ────────────────────────────────────────── */
@media (max-width: 768px) {{
  .header {{ padding: 16px; }}
  .main {{ padding: 16px; }}
  .grid-4 {{ grid-template-columns: repeat(2, 1fr); }}
  .grid-2 {{ grid-template-columns: 1fr; }}
  .health-ring {{ width: 140px; height: 140px; }}
  .health-ring .score-text {{ font-size: 36px; }}
  .nav {{ padding: 8px 16px; }}
}}

@media (max-width: 480px) {{
  .grid-4 {{ grid-template-columns: 1fr; }}
}}

/* ─── Print ─────────────────────────────────────────────── */
@media print {{
  body {{ background: white; color: #111; }}
  .header {{ background: none; border-bottom: 2px solid #111; }}
  .header h1 {{ -webkit-text-fill-color: #111; background: none; }}
  .card {{ box-shadow: none; border: 1px solid #ddd; break-inside: avoid; }}
  .nav {{ display: none; }}
  .section {{ display: block !important; page-break-after: always; }}
  :root {{
    --bg-primary: #fff;
    --bg-secondary: #f8f8f8;
    --bg-card: #fff;
    --border: #ddd;
    --text-primary: #111;
    --text-secondary: #555;
    --text-muted: #888;
  }}
}}

/* ─── Treemap ───────────────────────────────────────────── */
.treemap-container {{
  width: 100%;
  height: 300px;
  position: relative;
  border-radius: 8px;
  overflow: hidden;
}}

.treemap-cell {{
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  font-size: 11px;
  font-weight: 600;
  color: white;
  overflow: hidden;
  padding: 4px;
  transition: opacity 0.2s;
  cursor: pointer;
}}

.treemap-cell:hover {{
  opacity: 0.8;
}}

.treemap-cell span {{
  text-shadow: 0 1px 3px rgba(0,0,0,0.5);
  line-height: 1.2;
}}

/* ─── Trend chart ───────────────────────────────────────── */
.trend-chart {{
  width: 100%;
  height: 280px;
}}

/* ─── Animations ────────────────────────────────────────── */
@keyframes fadeIn {{
  from {{ opacity: 0; transform: translateY(10px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}

.card {{ animation: fadeIn 0.4s ease-out; }}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div>
    <h1>CodeLens Dashboard</h1>
    <div class="header-meta">{workspace_name} &middot; Generated {generated_at[:19].replace('T', ' ')}</div>
  </div>
  <div class="header-meta" id="snapshot-info">{trend_count} historical snapshot{'s' if trend_count != 1 else ''}</div>
</div>

<!-- Navigation -->
<div class="nav">
  <button class="active" onclick="showSection('overview')">Overview</button>
  <button onclick="showSection('complexity')">Complexity</button>
  <button onclick="showSection('findings')">Findings</button>
  <button onclick="showSection('dependencies')">Dependencies</button>
  <button onclick="showSection('security')">Security</button>
  <button onclick="showSection('trends')">Trends</button>
  {"<button onclick=\"showSection('compare')\">Compare</button>" if comparison else ""}
</div>

<!-- Main Content -->
<div class="main">

  <!-- ═══ OVERVIEW SECTION ═══ -->
  <div id="section-overview" class="section active">
    <div class="grid-4">
      <!-- Health Score -->
      <div class="card health-score">
        <div class="health-ring">
          <svg viewBox="0 0 180 180">
            <circle cx="90" cy="90" r="78" fill="none" stroke="#334155" stroke-width="10"/>
            <circle cx="90" cy="90" r="78" fill="none"
              stroke="{_health_color(health_score)}"
              stroke-width="10"
              stroke-dasharray="{2 * 3.14159 * 78}"
              stroke-dashoffset="{2 * 3.14159 * 78 * (1 - health_score / 100)}"
              stroke-linecap="round"/>
          </svg>
          <div class="score-text" style="color:{_health_color(health_score)}">{health_score}</div>
        </div>
        <div class="health-label">Health Score</div>
      </div>

      <!-- Total Findings -->
      <div class="card">
        <div class="metric-value" style="color:var(--orange)">{total_findings}</div>
        <div class="metric-label">Total Findings</div>
      </div>

      <!-- Files Scanned -->
      <div class="card">
        <div class="metric-value" style="color:var(--cyan)">{files_scanned}</div>
        <div class="metric-label">Files Scanned</div>
      </div>

      <!-- Avg Complexity -->
      <div class="card">
        <div class="metric-value" style="color:var(--purple)">{avg_complexity:.1f}</div>
        <div class="metric-label">Avg Cyclomatic Complexity</div>
      </div>
    </div>

    <div class="grid-4">
      <div class="card">
        <div class="metric-value" style="color:var(--blue)">{total_functions}</div>
        <div class="metric-label">Total Functions</div>
      </div>
      <div class="card">
        <div class="metric-value" style="color:var(--red)">{secrets_count}</div>
        <div class="metric-label">Hardcoded Secrets</div>
      </div>
      <div class="card">
        <div class="metric-value" style="color:var(--yellow)">{dead_code_count}</div>
        <div class="metric-label">Dead Code Items</div>
      </div>
      <div class="card">
        <div class="metric-value" style="color:var(--orange)">{circular_count}</div>
        <div class="metric-label">Circular Dependencies</div>
      </div>
    </div>

    <!-- Findings by Severity -->
    <div class="card">
      <div class="card-title">Findings by Severity</div>
      {_render_severity_bars(findings_severity, total_findings)}
    </div>
  </div>

  <!-- ═══ COMPLEXITY SECTION ═══ -->
  <div id="section-complexity" class="section">
    <div class="card">
      <div class="card-title">Complexity Heatmap</div>
      <div class="heatmap-grid" id="complexity-heatmap"></div>
    </div>

    <div class="card">
      <div class="card-title">Top 10 Most Complex Functions</div>
      <table class="fn-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Function</th>
            <th>File</th>
            <th>Cyclomatic</th>
            <th>Cognitive</th>
            <th>LOC</th>
          </tr>
        </thead>
        <tbody>
          {_render_top_functions(top_complex)}
        </tbody>
      </table>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-title">Complexity Distribution</div>
        <div class="chart-container" id="complexity-dist-chart"></div>
      </div>
      <div class="card">
        <div class="card-title">Complexity Over Time</div>
        <div class="chart-container" id="complexity-trend-chart"></div>
      </div>
    </div>
  </div>

  <!-- ═══ FINDINGS SECTION ═══ -->
  <div id="section-findings" class="section">
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Findings by Category</div>
        <div class="chart-container" id="category-pie-chart"></div>
      </div>
      <div class="card">
        <div class="card-title">Findings by Severity</div>
        <div class="chart-container" id="severity-bar-chart"></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Files with Most Issues</div>
      <div class="treemap-container" id="issue-treemap"></div>
    </div>
  </div>

  <!-- ═══ DEPENDENCIES SECTION ═══ -->
  <div id="section-dependencies" class="section">
    <div class="card">
      <div class="card-title">Module Dependency Graph (drag to interact)</div>
      <div id="dep-graph-container"></div>
    </div>
    <div class="grid-4">
      <div class="card">
        <div class="metric-value" style="color:var(--cyan)">{len(dep_graph.get('nodes', []))}</div>
        <div class="metric-label">Modules</div>
      </div>
      <div class="card">
        <div class="metric-value" style="color:var(--accent)">{len(dep_graph.get('edges', []))}</div>
        <div class="metric-label">Dependencies</div>
      </div>
      <div class="card">
        <div class="metric-value" style="color:var(--red)">{circular_count}</div>
        <div class="metric-label">Circular Dependencies</div>
      </div>
    </div>
  </div>

  <!-- ═══ SECURITY SECTION ═══ -->
  <div id="section-security" class="section">
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Secrets Detection</div>
        <div class="metric-value" style="color:var(--red)">{secrets_count}</div>
        <div class="metric-label">Potential secrets found</div>
        <div style="margin-top:16px">
          {_render_severity_bars(secrets_by_sev, secrets_count)}
        </div>
      </div>
      <div class="card">
        <div class="card-title">Vulnerability Summary</div>
        <div class="metric-value" style="color:var(--orange)">{vuln_count}</div>
        <div class="metric-label">Known vulnerabilities</div>
        <div style="margin-top:16px">
          {_render_vulns(vulnerabilities)}
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Security Overview</div>
      <div class="grid-4">
        <div class="card">
          <div class="metric-value" style="color:var(--red)">{findings_severity.get('critical', 0)}</div>
          <div class="metric-label">Critical Findings</div>
        </div>
        <div class="card">
          <div class="metric-value" style="color:var(--orange)">{findings_severity.get('high', findings_severity.get('warning', 0))}</div>
          <div class="metric-label">High Findings</div>
        </div>
        <div class="card">
          <div class="metric-value" style="color:var(--yellow)">{perf_count}</div>
          <div class="metric-label">Performance Hints</div>
        </div>
        <div class="card">
          <div class="metric-value" style="color:var(--green)">{_security_status(health_score, secrets_count, vuln_count)}</div>
          <div class="metric-label">Security Status</div>
        </div>
      </div>
    </div>
  </div>

  <!-- ═══ TRENDS SECTION ═══ -->
  <div id="section-trends" class="section">
    <div class="card">
      <div class="card-title">Health Score Over Time</div>
      <div class="chart-container trend-chart" id="trend-health-chart"></div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Total Findings Over Time</div>
        <div class="chart-container trend-chart" id="trend-findings-chart"></div>
      </div>
      <div class="card">
        <div class="card-title">Critical Findings Over Time</div>
        <div class="chart-container trend-chart" id="trend-critical-chart"></div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Average Complexity Over Time</div>
        <div class="chart-container trend-chart" id="trend-complexity-chart"></div>
      </div>
      <div class="card">
        <div class="card-title">Files Scanned Over Time</div>
        <div class="chart-container trend-chart" id="trend-files-chart"></div>
      </div>
    </div>
  </div>

  {"<div id='section-compare' class='section'>" + _render_comparison_section(comparison) + "</div>" if comparison else ""}

</div>

<!-- Tooltip -->
<div class="tooltip" id="tooltip"></div>

<script>
// ─── Data ─────────────────────────────────────────────────
const METRICS = {metrics_json};
const TRENDS = {trends_json};
const COMPARISON = {comparison_json};
const DEP_GRAPH = {dep_graph_json};

// ─── Navigation ───────────────────────────────────────────
function showSection(name) {{
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
  const sec = document.getElementById('section-' + name);
  if (sec) sec.classList.add('active');
  event.target.classList.add('active');
}}

// ─── Tooltip ──────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');
function showTooltip(e, html) {{
  tooltip.innerHTML = html;
  tooltip.classList.add('visible');
  const x = Math.min(e.clientX + 12, window.innerWidth - 320);
  const y = Math.min(e.clientY + 12, window.innerHeight - 100);
  tooltip.style.left = x + 'px';
  tooltip.style.top = y + 'px';
}}
function hideTooltip() {{
  tooltip.classList.remove('visible');
}}

// ─── Severity Bar Helper ──────────────────────────────────
// (Already rendered server-side)

// ─── Complexity Heatmap ───────────────────────────────────
(function() {{
  const container = document.getElementById('complexity-heatmap');
  if (!container || !METRICS.top_complex_functions) return;
  const funcs = METRICS.top_complex_functions || [];
  // Group by file
  const fileMap = {{}};
  funcs.forEach(fn => {{
    const file = fn.file || 'unknown';
    if (!fileMap[file]) fileMap[file] = [];
    fileMap[file].push(fn);
  }});

  // Add all scanned files as low-complexity cells if we have dep graph data
  const allNodes = (DEP_GRAPH.nodes || []);
  allNodes.forEach(n => {{
    const f = n.file || n.id;
    if (!fileMap[f]) fileMap[f] = [];
  }});

  Object.keys(fileMap).forEach(file => {{
    const fns = fileMap[file];
    const maxComp = fns.reduce((m, f) => Math.max(m, f.cyclomatic || 0), 0);
    const bgColor = maxComp > 20 ? '#7f1d1d' : maxComp > 10 ? '#92400e' : maxComp > 5 ? '#365314' : '#14532d';

    const cell = document.createElement('div');
    cell.className = 'heatmap-cell';
    cell.style.background = bgColor;
    const name = file.split('/').pop() || file;
    cell.innerHTML = '<div class="cell-name">' + name + '</div>' +
      '<div class="cell-score">' + (maxComp || 0) + '</div>' +
      '<div class="cell-label">max CC</div>';

    cell.addEventListener('mouseenter', function(e) {{
      let html = '<strong>' + name + '</strong><br>';
      if (fns.length === 0) {{
        html += 'No complex functions';
      }} else {{
        fns.forEach(fn => {{
          html += fn.name + '(): CC=' + fn.cyclomatic + ', Co=' + fn.cognitive + '<br>';
        }});
      }}
      showTooltip(e, html);
    }});
    cell.addEventListener('mouseleave', hideTooltip);
    container.appendChild(cell);
  }});
}})();

// ─── Category Pie Chart (SVG) ─────────────────────────────
(function() {{
  const container = document.getElementById('category-pie-chart');
  if (!container) return;
  const catData = METRICS.findings_by_category || {{}};
  const entries = Object.entries(catData).filter(e => e[1] > 0);
  if (entries.length === 0) {{
    container.innerHTML = '<div style="text-align:center;padding:60px;color:#64748b">No category data available</div>';
    return;
  }}

  const total = entries.reduce((s, e) => s + e[1], 0);
  const colors = ['#3b82f6','#8b5cf6','#ef4444','#eab308','#22c55e','#f97316','#06b6d4','#ec4899'];
  const cx = 150, cy = 140, r = 100;

  let svg = '<svg viewBox="0 0 400 280">';
  let angle = 0;
  entries.forEach((entry, i) => {{
    const [cat, count] = entry;
    const pct = count / total;
    const endAngle = angle + pct * 2 * Math.PI;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const largeArc = pct > 0.5 ? 1 : 0;

    svg += '<path d="M' + cx + ',' + cy + ' L' + x1 + ',' + y1 +
      ' A' + r + ',' + r + ' 0 ' + largeArc + ',1 ' + x2 + ',' + y2 +
      ' Z" fill="' + colors[i % colors.length] + '" opacity="0.85" ' +
      'onmouseenter="this.style.opacity=1" onmouseleave="this.style.opacity=0.85"/>';

    // Label
    const midAngle = (angle + endAngle) / 2;
    const lx = cx + (r + 30) * Math.cos(midAngle);
    const ly = cy + (r + 30) * Math.sin(midAngle);
    svg += '<text x="' + lx + '" y="' + ly + '" text-anchor="middle" fill="#94a3b8" font-size="11">' +
      cat + ' (' + count + ')</text>';

    angle = endAngle;
  }});
  svg += '</svg>';
  container.innerHTML = svg;
}})();

// ─── Severity Bar Chart (SVG) ─────────────────────────────
(function() {{
  const container = document.getElementById('severity-bar-chart');
  if (!container) return;
  const sevData = METRICS.findings_by_severity || {{}};
  const entries = Object.entries(sevData).filter(e => e[1] > 0);
  if (entries.length === 0) {{
    container.innerHTML = '<div style="text-align:center;padding:60px;color:#64748b">No severity data</div>';
    return;
  }}

  const maxVal = Math.max(...entries.map(e => e[1]));
  const barW = 60, gap = 30, chartH = 220, labelH = 40;
  const chartW = entries.length * (barW + gap);
  const colors = {{critical:'#ef4444', high:'#f97316', warning:'#f97316', medium:'#eab308', low:'#3b82f6', info:'#6b7280'}};

  let svg = '<svg viewBox="0 0 ' + (chartW + 40) + ' ' + (chartH + labelH + 20) + '">';
  entries.forEach((entry, i) => {{
    const [sev, count] = entry;
    const h = maxVal > 0 ? (count / maxVal) * chartH : 0;
    const x = 20 + i * (barW + gap);
    const y = chartH - h;
    const color = colors[sev] || '#6b7280';
    svg += '<rect x="' + x + '" y="' + y + '" width="' + barW + '" height="' + h +
      '" fill="' + color + '" rx="4" opacity="0.85"/>';
    svg += '<text x="' + (x + barW/2) + '" y="' + (y - 6) + '" text-anchor="middle" fill="#f1f5f9" font-size="14" font-weight="700">' + count + '</text>';
    svg += '<text x="' + (x + barW/2) + '" y="' + (chartH + 20) + '" text-anchor="middle" fill="#94a3b8" font-size="11">' + sev + '</text>';
  }});
  svg += '</svg>';
  container.innerHTML = svg;
}})();

// ─── Treemap (files with most issues) ─────────────────────
(function() {{
  const container = document.getElementById('issue-treemap');
  if (!container) return;
  const catData = METRICS.findings_by_category || {{}};
  const entries = Object.entries(catData).filter(e => e[1] > 0);
  if (entries.length === 0) {{
    container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b">No issue data</div>';
    return;
  }}

  const total = entries.reduce((s, e) => s + e[1], 0);
  const colors = ['#3b82f6','#8b5cf6','#ef4444','#eab308','#22c55e','#f97316','#06b6d4','#ec4899'];
  const w = container.clientWidth || 800;
  const h = 300;

  // Simple treemap: slice-and-dice
  let x = 0, y = 0, remaining = w;
  entries.forEach((entry, i) => {{
    const [cat, count] = entry;
    const pct = count / total;
    const cellW = Math.floor(pct * w);
    const cell = document.createElement('div');
    cell.className = 'treemap-cell';
    cell.style.left = x + 'px';
    cell.style.top = '0px';
    cell.style.width = cellW + 'px';
    cell.style.height = h + 'px';
    cell.style.background = colors[i % colors.length];
    cell.innerHTML = '<span>' + cat + '<br>' + count + '</span>';
    x += cellW;
  }});
}})();

// ─── Dependency Graph (SVG + Force Layout) ─────────────────
(function() {{
  const container = document.getElementById('dep-graph-container');
  if (!container) return;
  const graph = DEP_GRAPH;
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];

  if (nodes.length === 0) {{
    container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b">No dependency data. Run scan first.</div>';
    return;
  }}

  const w = container.clientWidth || 800;
  const h = 500;

  // Simple force layout simulation
  const nodeMap = {{}};
  nodes.forEach((n, i) => {{
    const angle = (2 * Math.PI * i) / nodes.length;
    const radius = Math.min(w, h) * 0.35;
    nodeMap[n.id] = {{
      id: n.id,
      x: w/2 + radius * Math.cos(angle) + (Math.random() - 0.5) * 40,
      y: h/2 + radius * Math.sin(angle) + (Math.random() - 0.5) * 40,
      vx: 0, vy: 0,
      file: n.file || '',
    }};
  }});

  // Detect circular dependencies
  const circularNodes = new Set();
  const adjList = {{}};
  edges.forEach(e => {{
    if (!adjList[e.source]) adjList[e.source] = [];
    adjList[e.source].push(e.target);
  }});
  function findCycles() {{
    const visited = new Set();
    const stack = new Set();
    function dfs(node) {{
      if (stack.has(node)) {{ circularNodes.add(node); return; }}
      if (visited.has(node)) return;
      visited.add(node);
      stack.add(node);
      (adjList[node] || []).forEach(dfs);
      stack.delete(node);
    }}
    Object.keys(adjList).forEach(dfs);
  }}
  findCycles();

  // Simple force simulation (10 iterations)
  for (let iter = 0; iter < 50; iter++) {{
    // Repulsion
    const nodeArr = Object.values(nodeMap);
    for (let i = 0; i < nodeArr.length; i++) {{
      for (let j = i + 1; j < nodeArr.length; j++) {{
        let dx = nodeArr[j].x - nodeArr[i].x;
        let dy = nodeArr[j].y - nodeArr[i].y;
        let dist = Math.sqrt(dx*dx + dy*dy) || 1;
        let force = 2000 / (dist * dist);
        nodeArr[i].vx -= force * dx / dist;
        nodeArr[i].vy -= force * dy / dist;
        nodeArr[j].vx += force * dx / dist;
        nodeArr[j].vy += force * dy / dist;
      }}
    }}
    // Attraction (edges)
    edges.forEach(e => {{
      const s = nodeMap[e.source];
      const t = nodeMap[e.target];
      if (!s || !t) return;
      let dx = t.x - s.x;
      let dy = t.y - s.y;
      let dist = Math.sqrt(dx*dx + dy*dy) || 1;
      let force = (dist - 80) * 0.01;
      s.vx += force * dx / dist;
      s.vy += force * dy / dist;
      t.vx -= force * dx / dist;
      t.vy -= force * dy / dist;
    }});
    // Center gravity
    nodeArr.forEach(n => {{
      n.vx += (w/2 - n.x) * 0.001;
      n.vy += (h/2 - n.y) * 0.001;
      n.x += n.vx * 0.5;
      n.y += n.vy * 0.5;
      n.vx *= 0.9;
      n.vy *= 0.9;
      // Bounds
      n.x = Math.max(30, Math.min(w - 30, n.x));
      n.y = Math.max(30, Math.min(h - 30, n.y));
    }});
  }}

  // Render SVG
  let svg = '<svg viewBox="0 0 ' + w + ' ' + h + '">';
  // Edges
  edges.forEach(e => {{
    const s = nodeMap[e.source];
    const t = nodeMap[e.target];
    if (!s || !t) return;
    const isCircular = circularNodes.has(e.source) && circularNodes.has(e.target);
    svg += '<line x1="' + s.x + '" y1="' + s.y + '" x2="' + t.x + '" y2="' + t.y +
      '" stroke="' + (isCircular ? '#ef4444' : '#334155') + '" stroke-width="' +
      (isCircular ? '2' : '1') + '" opacity="' + (isCircular ? '0.8' : '0.4') + '"/>';
  }});
  // Nodes
  Object.values(nodeMap).forEach(n => {{
    const isCirc = circularNodes.has(n.id);
    const color = isCirc ? '#ef4444' : '#3b82f6';
    svg += '<g class="dep-node" onmouseenter="showTooltip(event, \\'<strong>' + n.id + '</strong>' +
      (n.file ? '<br>' + n.file : '') +
      (isCirc ? '<br><span style=color:#ef4444>Circular dependency!</span>' : '') +
      '\\')" onmouseleave="hideTooltip()">';
    svg += '<circle cx="' + n.x + '" cy="' + n.y + '" r="10" fill="' + color + '" opacity="0.9"/>';
    svg += '<text x="' + n.x + '" y="' + (n.y + 22) + '" text-anchor="middle" fill="#94a3b8" font-size="9">' + n.id + '</text>';
    svg += '</g>';
  }});

  svg += '</svg>';
  container.innerHTML = svg;
}})();

// ─── Trend Charts (SVG line charts) ──────────────────────
(function() {{
  if (!TRENDS || !TRENDS.dates || TRENDS.dates.length === 0) return;

  function drawLineChart(containerId, data, color, label, yLabel) {{
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!data || data.length === 0) {{
      container.innerHTML = '<div style="text-align:center;padding:40px;color:#64748b">No data</div>';
      return;
    }}

    const w = 600, h = 220, pad = 50, chartW = w - pad * 2, chartH = h - pad - 30;
    const maxVal = Math.max(...data, 1);
    const minVal = Math.min(...data, 0);
    const range = maxVal - minVal || 1;

    let svg = '<svg viewBox="0 0 ' + w + ' ' + h + '">';
    // Grid lines
    for (let i = 0; i <= 4; i++) {{
      const y = pad + (i / 4) * chartH;
      const val = maxVal - (i / 4) * range;
      svg += '<line x1="' + pad + '" y1="' + y + '" x2="' + (w - pad) + '" y2="' + y + '" stroke="#1e293b" stroke-width="1"/>';
      svg += '<text x="' + (pad - 6) + '" y="' + (y + 4) + '" text-anchor="end" fill="#64748b" font-size="10">' + val.toFixed(1) + '</text>';
    }}

    // Data line
    let pathD = '';
    data.forEach((val, i) => {{
      const x = pad + (i / Math.max(data.length - 1, 1)) * chartW;
      const y = pad + ((maxVal - val) / range) * chartH;
      pathD += (i === 0 ? 'M' : 'L') + x + ',' + y;
    }});

    // Fill area
    const lastX = pad + chartW;
    const firstX = pad;
    svg += '<path d="' + pathD + ' L' + lastX + ',' + (pad + chartH) + ' L' + firstX + ',' + (pad + chartH) + ' Z" fill="' + color + '" opacity="0.1"/>';
    svg += '<path d="' + pathD + '" fill="none" stroke="' + color + '" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>';

    // Dots
    data.forEach((val, i) => {{
      const x = pad + (i / Math.max(data.length - 1, 1)) * chartW;
      const y = pad + ((maxVal - val) / range) * chartH;
      svg += '<circle cx="' + x + '" cy="' + y + '" r="4" fill="' + color + '"/>';
    }});

    // Date labels
    const dates = TRENDS.dates || [];
    if (dates.length > 0) {{
      const step = Math.max(1, Math.floor(dates.length / 6));
      for (let i = 0; i < dates.length; i += step) {{
        const x = pad + (i / Math.max(dates.length - 1, 1)) * chartW;
        const d = dates[i].substring(0, 10);
        svg += '<text x="' + x + '" y="' + (h - 5) + '" text-anchor="middle" fill="#64748b" font-size="9">' + d + '</text>';
      }}
    }}

    svg += '</svg>';
    container.innerHTML = svg;
  }}

  drawLineChart('trend-health-chart', TRENDS.health_score, '#22c55e', 'Health Score');
  drawLineChart('trend-findings-chart', TRENDS.total_findings, '#f97316', 'Total Findings');
  drawLineChart('trend-critical-chart', TRENDS.critical_findings, '#ef4444', 'Critical Findings');
  drawLineChart('trend-complexity-chart', TRENDS.avg_complexity, '#8b5cf6', 'Avg Complexity');
  drawLineChart('trend-files-chart', TRENDS.files_scanned, '#06b6d4', 'Files Scanned');
}})();

// ─── Complexity Distribution Chart ────────────────────────
(function() {{
  const container = document.getElementById('complexity-dist-chart');
  if (!container) return;
  const funcs = METRICS.top_complex_functions || [];
  if (funcs.length === 0) {{
    container.innerHTML = '<div style="text-align:center;padding:40px;color:#64748b">No complexity data</div>';
    return;
  }}

  const w = 500, h = 220, pad = 50, chartW = w - pad - 20, chartH = h - pad - 30;
  const maxCC = Math.max(...funcs.map(f => f.cyclomatic || 0), 1);
  const barH = Math.min(20, (chartH / funcs.length) - 4);

  let svg = '<svg viewBox="0 0 ' + w + ' ' + (h + funcs.length * 2) + '">';
  funcs.forEach((fn, i) => {{
    const y = pad + i * (barH + 6);
    const barW = ((fn.cyclomatic || 0) / maxCC) * chartW;
    const color = fn.cyclomatic > 20 ? '#ef4444' : fn.cyclomatic > 10 ? '#eab308' : '#22c55e';
    svg += '<rect x="' + pad + '" y="' + y + '" width="' + barW + '" height="' + barH + '" fill="' + color + '" rx="3" opacity="0.85"/>';
    svg += '<text x="' + (pad - 4) + '" y="' + (y + barH/2 + 4) + '" text-anchor="end" fill="#94a3b8" font-size="10">' + (fn.name || '?').substring(0, 20) + '</text>';
    svg += '<text x="' + (pad + barW + 4) + '" y="' + (y + barH/2 + 4) + '" fill="#f1f5f9" font-size="10">' + fn.cyclomatic + '</text>';
  }});
  svg += '</svg>';
  container.innerHTML = svg;
}})();

// ─── Complexity Trend Chart ───────────────────────────────
(function() {{
  const container = document.getElementById('complexity-trend-chart');
  if (!container || !TRENDS || !TRENDS.avg_complexity || TRENDS.avg_complexity.length === 0) {{
    if (container) container.innerHTML = '<div style="text-align:center;padding:40px;color:#64748b">Run more scans to see trends</div>';
    return;
  }}
  // Reuse the trend data but for complexity
  const data = TRENDS.avg_complexity;
  const color = '#8b5cf6';
  const w = 500, h = 220, pad = 50, chartW = w - pad * 2, chartH = h - pad - 30;
  const maxVal = Math.max(...data, 1);
  const minVal = Math.min(...data, 0);
  const range = maxVal - minVal || 1;

  let svg = '<svg viewBox="0 0 ' + w + ' ' + h + '">';
  let pathD = '';
  data.forEach((val, i) => {{
    const x = pad + (i / Math.max(data.length - 1, 1)) * chartW;
    const y = pad + ((maxVal - val) / range) * chartH;
    pathD += (i === 0 ? 'M' : 'L') + x + ',' + y;
  }});
  svg += '<path d="' + pathD + ' L' + (pad + chartW) + ',' + (pad + chartH) + ' L' + pad + ',' + (pad + chartH) + ' Z" fill="' + color + '" opacity="0.1"/>';
  svg += '<path d="' + pathD + '" fill="none" stroke="' + color + '" stroke-width="2"/>';
  data.forEach((val, i) => {{
    const x = pad + (i / Math.max(data.length - 1, 1)) * chartW;
    const y = pad + ((maxVal - val) / range) * chartH;
    svg += '<circle cx="' + x + '" cy="' + y + '" r="3" fill="' + color + '"/>';
  }});
  svg += '</svg>';
  container.innerHTML = svg;
}})();

</script>
</body>
</html>"""


def _render_severity_bars(severity_data: Dict, total: int) -> str:
    """Render severity bar HTML."""
    colors = {
        "critical": "#ef4444",
        "high": "#f97316",
        "warning": "#f97316",
        "medium": "#eab308",
        "low": "#3b82f6",
        "info": "#6b7280",
    }
    bars = []
    max_val = max(severity_data.values()) if severity_data else 1
    for sev in ["critical", "high", "warning", "medium", "low", "info"]:
        count = severity_data.get(sev, 0)
        if count == 0 and sev not in severity_data:
            continue
        pct = (count / max_val * 100) if max_val > 0 else 0
        color = colors.get(sev, "#6b7280")
        bars.append(f"""<div class="severity-bar">
          <div class="severity-label">{sev.title()}</div>
          <div class="severity-track">
            <div class="severity-fill" style="width:{pct}%;background:{color}"></div>
          </div>
          <div class="severity-count" style="color:{color}">{count}</div>
        </div>""")
    return "\n".join(bars)


def _render_top_functions(funcs: List[Dict]) -> str:
    """Render top complex functions as table rows."""
    if not funcs:
        return '<tr><td colspan="6" style="color:#64748b;text-align:center">No complexity data</td></tr>'
    rows = []
    for i, fn in enumerate(funcs[:10], 1):
        cc = fn.get("cyclomatic", 0)
        color = "#ef4444" if cc > 20 else "#eab308" if cc > 10 else "#22c55e"
        name = fn.get("name", "unknown")
        file_short = fn.get("file", "").split("/")[-1] if fn.get("file") else "—"
        rows.append(f"""<tr>
          <td>{i}</td>
          <td style="font-weight:600">{name}</td>
          <td style="color:#94a3b8;font-size:12px">{file_short}</td>
          <td style="color:{color};font-weight:700">{cc}</td>
          <td>{fn.get('cognitive', 0)}</td>
          <td>{fn.get('loc', 0)}</td>
        </tr>""")
    return "\n".join(rows)


def _render_vulns(vulns: List[Dict]) -> str:
    """Render vulnerability list."""
    if not vulns:
        return '<div style="color:#64748b;padding:12px">No known vulnerabilities detected</div>'
    items = []
    for v in vulns[:10]:
        sev = v.get("severity", "medium")
        name = v.get("name", "unknown")
        cve = v.get("cve", "")
        items.append(f"""<div class="sec-item">
          <span class="sec-badge {sev}">{sev}</span>
          <span style="flex:1">{name}</span>
          {f'<span style="color:#94a3b8;font-size:12px">{cve}</span>' if cve else ''}
        </div>""")
    return "\n".join(items)


def _security_status(health: float, secrets: int, vulns: int) -> str:
    """Return security status text."""
    if secrets > 0 or vulns > 0:
        return "AT RISK"
    elif health >= 70:
        return "GOOD"
    elif health >= 40:
        return "FAIR"
    else:
        return "POOR"


def _render_comparison_section(comparison: Optional[Dict]) -> str:
    """Render comparison section HTML."""
    if not comparison:
        return ""

    s1 = comparison.get("snapshot1", {})
    s2 = comparison.get("snapshot2", {})
    metrics = comparison.get("metrics", {})
    summary = comparison.get("summary", {})

    rows = []
    label_map = {
        "health_score": "Health Score",
        "total_findings": "Total Findings",
        "avg_complexity": "Avg Complexity",
        "files_scanned": "Files Scanned",
        "secrets_count": "Secrets",
        "dead_code_count": "Dead Code",
        "circular_deps_count": "Circular Deps",
        "high_complexity_count": "High Complexity",
        "total_functions": "Total Functions",
        "perf_hints_count": "Perf Hints",
    }

    for key, label in label_map.items():
        m = metrics.get(key, {})
        before = m.get("before", 0)
        after = m.get("after", 0)
        delta = m.get("delta", 0)
        direction = m.get("direction", "unchanged")

        if isinstance(before, float):
            before_str = f"{before:.1f}"
            after_str = f"{after:.1f}"
        else:
            before_str = str(before)
            after_str = str(after)

        delta_str = f"+{delta}" if delta > 0 else str(delta)
        rows.append(f"""<div class="compare-row">
          <div class="compare-value" style="text-align:right">{before_str}</div>
          <div class="compare-delta {direction}">{delta_str}</div>
          <div class="compare-value">{after_str}</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 80px 1fr;gap:8px;margin-bottom:8px">
          <div style="text-align:right;font-size:12px;color:#64748b">{s1.get('timestamp','')[:19].replace('T',' ')}</div>
          <div style="text-align:center;font-size:12px;color:#94a3b8">{label}</div>
          <div style="font-size:12px;color:#64748b">{s2.get('timestamp','')[:19].replace('T',' ')}</div>
        </div>""")

    overall = summary.get("overall", "unchanged")
    overall_color = "#22c55e" if overall == "improved" else "#ef4444" if overall == "degraded" else "#64748b"

    return f"""<div class="card">
        <div class="card-title">Snapshot Comparison</div>
        <div style="text-align:center;margin-bottom:20px">
          <span style="font-size:20px;font-weight:800;color:{overall_color}">Overall: {overall.upper()}</span>
          <div style="color:#94a3b8;font-size:13px;margin-top:4px">
            {summary.get('improved_metrics', 0)} improved &middot;
            {summary.get('degraded_metrics', 0)} degraded &middot;
            {summary.get('resolved_findings', 0)} resolved &middot;
            {summary.get('new_findings', 0)} new findings
          </div>
        </div>
        {''.join(rows)}
      </div>"""
