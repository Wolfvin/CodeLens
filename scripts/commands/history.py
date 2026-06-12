"""History command — Show historical trend data and generate trend charts."""

import os
from commands import register_command
from history_engine import list_snapshots, get_trend_data, compare_snapshots


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--chart", action="store_true",
                        help="Generate HTML trend chart")
    parser.add_argument("--list", action="store_true",
                        help="List all available snapshots")
    parser.add_argument("--compare", nargs=2, metavar=("SNAPSHOT1", "SNAPSHOT2"),
                        help="Compare two snapshots by filename")


def execute(args, workspace):
    should_chart = getattr(args, 'chart', False)
    should_list = getattr(args, 'list', False)
    compare = getattr(args, 'compare', None)

    if should_list:
        snapshots = list_snapshots(workspace)
        return {
            "status": "ok",
            "workspace": workspace,
            "total_snapshots": len(snapshots),
            "snapshots": [
                {
                    "file": s.get("_snapshot_file", ""),
                    "timestamp": s.get("timestamp", ""),
                    "health_score": s.get("health_score", 0),
                    "total_findings": s.get("total_findings", 0),
                    "avg_complexity": s.get("avg_complexity", 0),
                    "files_scanned": s.get("files_scanned", 0),
                }
                for s in snapshots
            ],
        }

    if compare:
        result = compare_snapshots(workspace, compare[0], compare[1])
        return result

    if should_chart:
        return _generate_trend_chart(workspace)

    # Default: show trend table
    return get_trend_data(workspace)


def _generate_trend_chart(workspace: str) -> dict:
    """Generate an HTML trend chart from historical data."""
    from history_engine import get_trend_data

    trend = get_trend_data(workspace)
    if trend.get("snapshots", 0) == 0:
        return trend

    # Generate HTML
    html = _build_trend_html(workspace, trend)

    # Save to file
    codelens_dir = os.path.join(workspace, '.codelens')
    os.makedirs(codelens_dir, exist_ok=True)
    output_path = os.path.join(codelens_dir, 'trend-chart.html')

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
    except IOError as e:
        return {"status": "error", "error": f"Failed to write trend chart: {e}"}

    return {
        "status": "ok",
        "workspace": workspace,
        "chart_path": os.path.abspath(output_path),
        "snapshots": trend["snapshots"],
    }


def _build_trend_html(workspace: str, trend: dict) -> str:
    """Build a self-contained HTML trend chart."""
    import json

    trends = trend.get("trends", {})
    dates = trends.get("dates", [])
    workspace_name = os.path.basename(workspace)

    # Get latest metrics for summary
    latest = trend.get("latest", {})
    health = latest.get("health_score", 0)

    trends_json = json.dumps(trends, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CodeLens Trends — {workspace_name}</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #0f172a; --bg2: #1e293b; --border: #334155;
  --text: #f1f5f9; --muted: #94a3b8; --dim: #64748b;
  --green: #22c55e; --red: #ef4444; --yellow: #eab308;
  --blue: #3b82f6; --purple: #8b5cf6; --cyan: #06b6d4; --orange: #f97316;
}}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 24px; }}
h1 {{ font-size: 24px; margin-bottom: 8px; background: linear-gradient(135deg, #3b82f6, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
.subtitle {{ color: var(--muted); font-size: 14px; margin-bottom: 24px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; }}
.card {{ background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
.card-title {{ font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }}
.chart {{ width: 100%; height: 240px; }}
@media print {{ body {{ background: #fff; color: #111; }} .card {{ border-color: #ddd; }} }}
</style>
</head>
<body>
<h1>CodeLens Trend Chart</h1>
<div class="subtitle">{workspace_name} &middot; {len(dates)} snapshots &middot; Health: {health}</div>

<div class="grid">
  <div class="card">
    <div class="card-title">Health Score</div>
    <div class="chart" id="chart-health"></div>
  </div>
  <div class="card">
    <div class="card-title">Total Findings</div>
    <div class="chart" id="chart-findings"></div>
  </div>
  <div class="card">
    <div class="card-title">Critical Findings</div>
    <div class="chart" id="chart-critical"></div>
  </div>
  <div class="card">
    <div class="card-title">Average Complexity</div>
    <div class="chart" id="chart-complexity"></div>
  </div>
  <div class="card">
    <div class="card-title">Files Scanned</div>
    <div class="chart" id="chart-files"></div>
  </div>
  <div class="card">
    <div class="card-title">Secrets Found</div>
    <div class="chart" id="chart-secrets"></div>
  </div>
</div>

<script>
const T = {trends_json};

function draw(id, data, color) {{
  const el = document.getElementById(id);
  if (!el || !data || data.length === 0) {{ if(el) el.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b">No data</div>'; return; }}
  const w = 500, h = 200, p = 40, cw = w-p*2, ch = h-p-20;
  const mx = Math.max(...data, 1), mn = Math.min(...data, 0), rng = mx-mn||1;
  let svg = '<svg viewBox="0 0 '+w+' '+h+'">';
  for(let i=0;i<=4;i++){{ const y=p+(i/4)*ch; svg+='<line x1="'+p+'" y1="'+y+'" x2="'+(w-p)+'" y2="'+y+'" stroke="#1e293b" stroke-width="1"/>'; svg+='<text x="'+(p-4)+'" y="'+(y+4)+'" text-anchor="end" fill="#64748b" font-size="9">'+(mx-(i/4)*rng).toFixed(1)+'</text>'; }}
  let d=''; data.forEach((v,i)=>{{ const x=p+(i/Math.max(data.length-1,1))*cw; const y=p+((mx-v)/rng)*ch; d+=(i===0?'M':'L')+x+','+y; }});
  svg+='<path d="'+d+' L'+(p+cw)+','+(p+ch)+' L'+p+','+(p+ch)+' Z" fill="'+color+'" opacity="0.1"/>';
  svg+='<path d="'+d+'" fill="none" stroke="'+color+'" stroke-width="2.5"/>';
  data.forEach((v,i)=>{{ const x=p+(i/Math.max(data.length-1,1))*cw; const y=p+((mx-v)/rng)*ch; svg+='<circle cx="'+x+'" cy="'+y+'" r="3" fill="'+color+'"/>'; }});
  const dates=T.dates||[]; if(dates.length>0){{ const step=Math.max(1,Math.floor(dates.length/5)); for(let i=0;i<dates.length;i+=step){{ const x=p+(i/Math.max(dates.length-1,1))*cw; svg+='<text x="'+x+'" y="'+(h-2)+'" text-anchor="middle" fill="#64748b" font-size="8">'+dates[i].substring(0,10)+'</text>'; }} }}
  svg+='</svg>';
  el.innerHTML=svg;
}}

draw('chart-health', T.health_score, '#22c55e');
draw('chart-findings', T.total_findings, '#f97316');
draw('chart-critical', T.critical_findings, '#ef4444');
draw('chart-complexity', T.avg_complexity, '#8b5cf6');
draw('chart-files', T.files_scanned, '#06b6d4');
draw('chart-secrets', T.secrets_count || [], '#ef4444');
</script>
</body>
</html>"""


register_command("history", "Show historical trend data and charts", add_args, execute)
