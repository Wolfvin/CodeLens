"""arch-metrics command — architecture metrics from the graph database.

Computes fan-in, fan-out, instability, and god-module detection from the
SQLite graph tables. Closes issue #61.

Usage::

    codelens arch-metrics [workspace]
    codelens arch-metrics --format json
    codelens arch-metrics --sort-by fan-in
    codelens arch-metrics --threshold-fanin 15 --threshold-fanout 20
"""

from __future__ import annotations

import os
import sys
import sqlite3
import argparse
from typing import Any, Dict, List, Optional, Tuple

from commands import register_command


def add_args(parser: argparse.ArgumentParser) -> None:
    """Register arch-metrics CLI arguments.

    Note: ``--format`` is added globally by ``codelens.py`` with choices
    ``json|markdown|ai|sarif|compact``. We reuse it: ``json`` produces
    machine-readable JSON; any other value produces a human-readable table.
    """
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--threshold-fanin",
        type=int,
        default=10,
        help="Fan-in threshold for god-module detection (default: 10)",
    )
    parser.add_argument(
        "--threshold-fanout",
        type=int,
        default=15,
        help="Fan-out threshold for god-module detection (default: 15)",
    )
    parser.add_argument(
        "--sort-by",
        choices=["instability", "fan-in", "fan-out", "name"],
        default="instability",
        help="Sort order (default: instability descending)",
    )


def _default_db_path(workspace: str) -> str:
    """Return the default SQLite database path for the workspace."""
    return os.path.join(workspace, ".codelens", "codelens.db")


def _compute_metrics(
    db_path: str,
    fanin_threshold: int,
    fanout_threshold: int,
) -> List[Dict[str, Any]]:
    """Compute fan-in/out + instability for every module in the graph.

    A "module" is a file path (the ``file`` column in ``graph_nodes``).
    Fan-in = number of DISTINCT source files that have edges pointing TO
    nodes in this file. Fan-out = number of DISTINCT target files that
    edges FROM nodes in this file point to.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Collect all distinct files from graph_nodes
    files = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT file FROM graph_nodes WHERE file IS NOT NULL"
        )
    }
    if not files:
        conn.close()
        return []

    # Fan-out per file: count distinct target files for edges originating
    # from nodes in this file.
    fan_out: Dict[str, int] = {}
    for row in conn.execute(
        """
        SELECT DISTINCT ge.source_id AS src_node, gn_target.file AS target_file
        FROM graph_edges ge
        JOIN graph_nodes gn_src ON ge.source_id = gn_src.node_id
        LEFT JOIN graph_nodes gn_target ON ge.target_id = gn_target.node_id
        WHERE gn_src.file IS NOT NULL AND gn_target.file IS NOT NULL
        """
    ):
        src_file = None
        # Look up source file from node_id
        src_row = conn.execute(
            "SELECT file FROM graph_nodes WHERE node_id = ?", (row["src_node"],)
        ).fetchone()
        if src_row:
            src_file = src_row["file"]
        if src_file and row["target_file"] and src_file != row["target_file"]:
            fan_out[src_file] = fan_out.get(src_file, 0) + 1

    # Fan-in per file: count distinct source files that have edges pointing
    # to nodes in this file.
    fan_in: Dict[str, int] = {}
    for row in conn.execute(
        """
        SELECT DISTINCT ge.target_id AS tgt_node, gn_src.file AS src_file
        FROM graph_edges ge
        JOIN graph_nodes gn_target ON ge.target_id = gn_target.node_id
        LEFT JOIN graph_nodes gn_src ON ge.source_id = gn_src.node_id
        WHERE gn_target.file IS NOT NULL AND gn_src.file IS NOT NULL
        """
    ):
        tgt_file = None
        tgt_row = conn.execute(
            "SELECT file FROM graph_nodes WHERE node_id = ?", (row["tgt_node"],)
        ).fetchone()
        if tgt_row:
            tgt_file = tgt_row["file"]
        if tgt_file and row["src_file"] and tgt_file != row["src_file"]:
            fan_in[tgt_file] = fan_in.get(tgt_file, 0) + 1

    conn.close()

    # Build result list
    results: List[Dict[str, Any]] = []
    for f in sorted(files):
        fi = fan_in.get(f, 0)
        fo = fan_out.get(f, 0)
        total = fi + fo
        instability = fo / total if total > 0 else 0.0
        flags: List[str] = []
        if fi > fanin_threshold or fo > fanout_threshold:
            flags.append("god-module")
        results.append({
            "module": f,
            "fan_in": fi,
            "fan_out": fo,
            "instability": round(instability, 4),
            "flags": flags,
        })
    return results


def _sort_results(
    results: List[Dict[str, Any]],
    sort_by: str,
) -> List[Dict[str, Any]]:
    """Sort results by the specified key."""
    if sort_by == "name":
        return sorted(results, key=lambda r: r["module"])
    elif sort_by == "fan-in":
        return sorted(results, key=lambda r: r["fan_in"], reverse=True)
    elif sort_by == "fan-out":
        return sorted(results, key=lambda r: r["fan_out"], reverse=True)
    else:  # instability (default)
        return sorted(results, key=lambda r: r["instability"], reverse=True)


def _format_table(results: List[Dict[str, Any]]) -> str:
    """Format results as a human-readable table."""
    if not results:
        return "No modules found in graph."

    # Column widths
    mod_w = max(len(r["module"]) for r in results)
    mod_w = max(mod_w, len("Module"))
    header = (
        f"{'Module':<{mod_w}}  {'Fan-in':>6}  {'Fan-out':>7}  "
        f"{'Instability':>12}  {'Flags':s}"
    )
    sep = "-" * len(header)
    lines = [header, sep]
    for r in results:
        flags_str = ", ".join(r["flags"]) if r["flags"] else ""
        lines.append(
            f"{r['module']:<{mod_w}}  {r['fan_in']:>6}  {r['fan_out']:>7}  "
            f"{r['instability']:>12.2f}  {flags_str}"
        )
    return "\n".join(lines)


def execute(args: argparse.Namespace, workspace: str) -> Dict[str, Any]:
    """Execute the arch-metrics command.

    Returns a dict with the metrics results. When ``--format table`` is
    selected (default), also prints the table to stdout.
    """
    db_path = _default_db_path(workspace)

    if not os.path.exists(db_path):
        print(
            "Error: Graph database not found. Run `codelens scan` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    results = _compute_metrics(
        db_path,
        fanin_threshold=args.threshold_fanin,
        fanout_threshold=args.threshold_fanout,
    )
    results = _sort_results(results, args.sort_by)

    # The global formatter in codelens.py handles JSON output. We just
    # return the dict; the formatter prints it. For non-JSON formats
    # (markdown, ai, compact), the formatter also handles conversion.
    return {
        "status": "ok",
        "workspace": workspace,
        "metrics": results,
        "total_modules": len(results),
        "god_modules": [r for r in results if r["flags"]],
        "thresholds": {
            "fan_in": args.threshold_fanin,
            "fan_out": args.threshold_fanout,
        },
        "sort_by": args.sort_by,
    }

# Issue #199: deprecated "arch-metrics" alias registration removed; this module is now an implementation module imported by the "summary" umbrella command.
