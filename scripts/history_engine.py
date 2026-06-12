"""History Engine for CodeLens — Track code quality metrics over time.

Saves snapshots after each scan and provides trend analysis.
Snapshots are stored in .codelens/history/ as JSON files.
Keeps the last 100 snapshots (prunes oldest).

Tracked metrics:
- Health score over time
- Total findings over time (by severity)
- Critical findings over time
- Average complexity over time
- Files scanned over time
- Category-level breakdowns (smell, security, performance, dead-code)
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from utils import logger

# Maximum number of snapshots to keep per workspace
MAX_SNAPSHOTS = 100


def _history_dir(workspace: str) -> str:
    """Get the history directory path."""
    return os.path.join(workspace, '.codelens', 'history')


def _ensure_history_dir(workspace: str) -> str:
    """Create history directory if it doesn't exist."""
    hist_dir = _history_dir(workspace)
    os.makedirs(hist_dir, exist_ok=True)
    return hist_dir


def _snapshot_filename() -> str:
    """Generate a snapshot filename from the current timestamp."""
    now = datetime.now(timezone.utc)
    # Use ISO format with colons replaced by hyphens for filesystem safety
    return now.strftime('%Y-%m-%dT%H-%M-%S') + '.json'


def _prune_snapshots(workspace: str) -> None:
    """Remove oldest snapshots if we exceed MAX_SNAPSHOTS."""
    hist_dir = _history_dir(workspace)
    if not os.path.isdir(hist_dir):
        return

    snapshots = sorted([
        f for f in os.listdir(hist_dir)
        if f.endswith('.json')
    ])

    if len(snapshots) > MAX_SNAPSHOTS:
        to_remove = snapshots[:len(snapshots) - MAX_SNAPSHOTS]
        for fname in to_remove:
            try:
                os.remove(os.path.join(hist_dir, fname))
            except OSError:
                pass


def collect_metrics(workspace: str, scan_result: Dict[str, Any]) -> Dict[str, Any]:
    """Collect all dashboard-relevant metrics from workspace data.

    Runs multiple engines to gather comprehensive metrics for a snapshot.
    Falls back gracefully if any engine fails.
    """
    metrics: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workspace": os.path.basename(workspace),
    }

    # ─── 1. Health Score from smell engine ──────────────────
    try:
        from smell_engine import detect_smells
        smell_result = detect_smells(workspace, max_files=3000)
        metrics["health_score"] = smell_result.get("health_score", 0)
        metrics["total_findings"] = smell_result.get("total_findings", 0)
        stats = smell_result.get("stats", {})
        metrics["findings_by_severity"] = {
            "critical": stats.get("critical", 0),
            "high": stats.get("warning", 0),
            "medium": stats.get("info", 0),
            "low": 0,
            "info": 0,
        }
        metrics["findings_by_category"] = {}
        by_cat = smell_result.get("by_category", {})
        for cat, items in by_cat.items():
            if isinstance(items, list):
                metrics["findings_by_category"][cat] = len(items)
    except Exception:
        metrics["health_score"] = 0
        metrics["total_findings"] = 0
        metrics["findings_by_severity"] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        metrics["findings_by_category"] = {}

    # ─── 2. Complexity metrics ──────────────────────────────
    try:
        from complexity_engine import compute_complexity
        comp = compute_complexity(workspace, max_files=3000)
        comp_stats = comp.get("stats", {})
        metrics["avg_complexity"] = comp_stats.get("avg_cyclomatic", 0)
        metrics["max_complexity"] = comp_stats.get("max_cyclomatic", 0)
        metrics["high_complexity_count"] = comp_stats.get("high_complexity", 0)
        metrics["total_functions"] = comp_stats.get("total_functions", 0)
        metrics["top_complex_functions"] = []
        funcs = comp.get("functions", [])
        top_funcs = sorted(funcs, key=lambda f: f.get("cyclomatic", 0), reverse=True)[:10]
        for fn in top_funcs:
            metrics["top_complex_functions"].append({
                "name": fn.get("name", "unknown"),
                "file": fn.get("file", ""),
                "cyclomatic": fn.get("cyclomatic", 0),
                "cognitive": fn.get("cognitive", 0),
                "loc": fn.get("loc", 0),
            })
    except Exception:
        metrics["avg_complexity"] = 0
        metrics["max_complexity"] = 0
        metrics["high_complexity_count"] = 0
        metrics["total_functions"] = 0
        metrics["top_complex_functions"] = []

    # ─── 3. Security findings ───────────────────────────────
    try:
        from secrets_engine import detect_secrets
        sec = detect_secrets(workspace, max_files=3000)
        sec_stats = sec.get("stats", {})
        metrics["secrets_count"] = sec_stats.get("total_secrets", 0)
        metrics["secrets_by_severity"] = sec_stats.get("by_severity", {})
    except Exception:
        metrics["secrets_count"] = 0
        metrics["secrets_by_severity"] = {}

    # ─── 4. Dead code ───────────────────────────────────────
    try:
        from deadcode_engine import detect_dead_code
        dc = detect_dead_code(workspace, max_files=3000)
        dc_stats = dc.get("stats", {})
        metrics["dead_code_count"] = dc_stats.get("total_dead_code", 0)
        metrics["dead_code_by_category"] = dc_stats.get("by_category", {})
    except Exception:
        metrics["dead_code_count"] = 0
        metrics["dead_code_by_category"] = {}

    # ─── 5. Circular dependencies ───────────────────────────
    try:
        from circular_engine import detect_circular
        circ = detect_circular(workspace)
        metrics["circular_deps_count"] = circ.get("cycle_count", 0)
        metrics["circular_deps"] = []
        cycles = circ.get("cycles", circ.get("chains", {}))
        if isinstance(cycles, dict):
            for cat, items in cycles.items():
                if isinstance(items, list):
                    for item in items[:5]:
                        metrics["circular_deps"].append(str(item))
        elif isinstance(cycles, list):
            metrics["circular_deps"] = [str(c) for c in cycles[:5]]
    except Exception:
        metrics["circular_deps_count"] = 0
        metrics["circular_deps"] = []

    # ─── 6. Performance hints ───────────────────────────────
    try:
        from perfhint_engine import detect_perf_hints
        perf = detect_perf_hints(workspace, max_files=3000)
        perf_stats = perf.get("stats", {})
        metrics["perf_hints_count"] = perf_stats.get("total_hints", 0)
    except Exception:
        metrics["perf_hints_count"] = 0

    # ─── 7. File & function counts ──────────────────────────
    try:
        from registry import load_backend_registry, load_frontend_registry
        backend = load_backend_registry(workspace)
        nodes = backend.get("nodes", [])
        edges = backend.get("edges", [])
        metrics["files_scanned"] = len(set(n.get("file", "") for n in nodes if n.get("file")))
        metrics["total_nodes"] = len(nodes)
        metrics["total_edges"] = len(edges)

        # Build dependency graph from edges
        metrics["dependency_graph"] = _extract_dependency_graph(nodes, edges)
    except Exception:
        metrics["files_scanned"] = scan_result.get("files_scanned", 0) if scan_result else 0
        metrics["total_nodes"] = 0
        metrics["total_edges"] = 0
        metrics["dependency_graph"] = {"nodes": [], "edges": []}

    # ─── 8. Vulnerability scan ──────────────────────────────
    try:
        from vulnscan_engine import scan_vulnerabilities
        vuln = scan_vulnerabilities(workspace)
        metrics["vulnerability_count"] = vuln.get("stats", {}).get("total_vulnerabilities", 0)
        metrics["vulnerabilities"] = []
        for v in vuln.get("vulnerabilities", [])[:10]:
            metrics["vulnerabilities"].append({
                "name": v.get("name", v.get("package", "unknown")),
                "severity": v.get("severity", "medium"),
                "cve": v.get("cve", v.get("id", "")),
            })
    except Exception:
        metrics["vulnerability_count"] = 0
        metrics["vulnerabilities"] = []

    return metrics


def _extract_dependency_graph(nodes: List, edges: List) -> Dict[str, Any]:
    """Extract a dependency graph suitable for dashboard visualization."""
    graph_nodes = []
    graph_edges = []

    # Extract unique files from nodes
    file_set = set()
    for node in nodes:
        f = node.get("file", "")
        if f:
            file_set.add(f)

    for f in sorted(file_set)[:100]:  # Cap at 100 for dashboard performance
        module = os.path.splitext(os.path.basename(f))[0]
        graph_nodes.append({
            "id": module,
            "file": f,
        })

    # Extract imports from edges — edges use "from"/"to" or "source"/"target"
    seen_edges = set()
    for edge in edges[:500]:
        source = edge.get("source", edge.get("from", ""))
        target = edge.get("target", edge.get("to", ""))
        if source and target:
            # Extract module names from full paths
            src_parts = source.split(":")
            tgt_parts = target.split(":")
            src_file = src_parts[0] if src_parts else source
            tgt_file = tgt_parts[0] if tgt_parts else target
            src_mod = os.path.splitext(os.path.basename(src_file))[0]
            tgt_mod = os.path.splitext(os.path.basename(tgt_file))[0]
            edge_key = f"{src_mod}->{tgt_mod}"
            if edge_key not in seen_edges and src_mod != tgt_mod:
                seen_edges.add(edge_key)
                graph_edges.append({"source": src_mod, "target": tgt_mod})

    return {"nodes": graph_nodes, "edges": graph_edges}


def save_snapshot(workspace: str, scan_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Save a metrics snapshot to the history directory.

    Returns the snapshot data that was saved.
    """
    hist_dir = _ensure_history_dir(workspace)
    metrics = collect_metrics(workspace, scan_result or {})

    # Save to file
    filename = _snapshot_filename()
    filepath = os.path.join(hist_dir, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.warning(f"Failed to save history snapshot: {e}")
        return metrics

    # Prune old snapshots
    _prune_snapshots(workspace)

    metrics["_snapshot_file"] = filename
    return metrics


def list_snapshots(workspace: str) -> List[Dict[str, Any]]:
    """List all available snapshots, oldest first."""
    hist_dir = _history_dir(workspace)
    if not os.path.isdir(hist_dir):
        return []

    snapshots = []
    for fname in sorted(os.listdir(hist_dir)):
        if fname.endswith('.json'):
            try:
                with open(os.path.join(hist_dir, fname), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data["_snapshot_file"] = fname
                snapshots.append(data)
            except (json.JSONDecodeError, IOError):
                pass

    return snapshots


def load_snapshot(workspace: str, snapshot_file: str) -> Optional[Dict[str, Any]]:
    """Load a specific snapshot by filename."""
    hist_dir = _history_dir(workspace)
    filepath = os.path.join(hist_dir, snapshot_file)
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def get_trend_data(workspace: str) -> Dict[str, Any]:
    """Get trend data for all tracked metrics over time."""
    snapshots = list_snapshots(workspace)

    if not snapshots:
        return {
            "status": "ok",
            "workspace": workspace,
            "snapshots": 0,
            "message": "No historical data available. Run a scan to create the first snapshot.",
            "trends": {},
        }

    # Extract time series for each metric
    dates = [s.get("timestamp", s.get("_snapshot_file", "").replace('.json', '')) for s in snapshots]

    trends = {
        "dates": dates,
        "health_score": [s.get("health_score", 0) for s in snapshots],
        "total_findings": [s.get("total_findings", 0) for s in snapshots],
        "critical_findings": [s.get("findings_by_severity", {}).get("critical", 0) for s in snapshots],
        "avg_complexity": [s.get("avg_complexity", 0) for s in snapshots],
        "files_scanned": [s.get("files_scanned", 0) for s in snapshots],
        "secrets_count": [s.get("secrets_count", 0) for s in snapshots],
        "dead_code_count": [s.get("dead_code_count", 0) for s in snapshots],
        "circular_deps_count": [s.get("circular_deps_count", 0) for s in snapshots],
    }

    # Compute deltas (latest vs previous)
    deltas = {}
    if len(snapshots) >= 2:
        latest = snapshots[-1]
        previous = snapshots[-2]

        for key in ["health_score", "total_findings", "avg_complexity", "files_scanned",
                     "secrets_count", "dead_code_count", "circular_deps_count"]:
            l_val = latest.get(key, 0)
            p_val = previous.get(key, 0)
            deltas[key] = l_val - p_val

    return {
        "status": "ok",
        "workspace": workspace,
        "snapshots": len(snapshots),
        "latest": snapshots[-1] if snapshots else None,
        "trends": trends,
        "deltas": deltas,
    }


def compare_snapshots(
    workspace: str,
    snapshot1_file: str,
    snapshot2_file: str
) -> Dict[str, Any]:
    """Compare two snapshots and return the delta.

    snapshot2 is the 'newer' one for delta calculation.
    """
    s1 = load_snapshot(workspace, snapshot1_file)
    s2 = load_snapshot(workspace, snapshot2_file)

    if not s1 or not s2:
        return {
            "status": "error",
            "error": f"Could not load snapshots: {snapshot1_file} or {snapshot2_file}",
        }

    comparison = {
        "status": "ok",
        "snapshot1": {"file": snapshot1_file, "timestamp": s1.get("timestamp", "")},
        "snapshot2": {"file": snapshot2_file, "timestamp": s2.get("timestamp", "")},
        "metrics": {},
    }

    # Compare numeric metrics
    numeric_keys = [
        "health_score", "total_findings", "avg_complexity", "files_scanned",
        "secrets_count", "dead_code_count", "circular_deps_count",
        "high_complexity_count", "total_functions", "perf_hints_count",
    ]

    for key in numeric_keys:
        v1 = s1.get(key, 0)
        v2 = s2.get(key, 0)
        delta = v2 - v1 if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) else 0

        # Determine if improvement or degradation
        # For health_score: increase is good
        # For everything else: increase is bad
        if key == "health_score":
            direction = "improved" if delta > 0 else ("degraded" if delta < 0 else "unchanged")
        else:
            direction = "degraded" if delta > 0 else ("improved" if delta < 0 else "unchanged")

        comparison["metrics"][key] = {
            "before": v1,
            "after": v2,
            "delta": delta,
            "direction": direction,
        }

    # Compare findings by severity
    sev1 = s1.get("findings_by_severity", {})
    sev2 = s2.get("findings_by_severity", {})
    comparison["findings_by_severity"] = {}
    for sev in ["critical", "high", "medium", "low", "info"]:
        v1 = sev1.get(sev, 0)
        v2 = sev2.get(sev, 0)
        delta = v2 - v1
        comparison["findings_by_severity"][sev] = {
            "before": v1,
            "after": v2,
            "delta": delta,
            "direction": "degraded" if delta > 0 else ("improved" if delta < 0 else "unchanged"),
        }

    # Summary
    improved = sum(1 for m in comparison["metrics"].values() if m["direction"] == "improved")
    degraded = sum(1 for m in comparison["metrics"].values() if m["direction"] == "degraded")
    new_findings = sum(1 for s in comparison["findings_by_severity"].values()
                       if s["delta"] > 0 for _ in [1])
    resolved_findings = sum(-s["delta"] for s in comparison["findings_by_severity"].values()
                            if s["delta"] < 0)

    comparison["summary"] = {
        "improved_metrics": improved,
        "degraded_metrics": degraded,
        "new_findings": max(0, comparison["findings_by_severity"].get("critical", {}).get("delta", 0)
                           + comparison["findings_by_severity"].get("high", {}).get("delta", 0)),
        "resolved_findings": resolved_findings,
        "overall": "improved" if improved > degraded else ("degraded" if degraded > improved else "unchanged"),
    }

    return comparison
