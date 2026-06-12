"""Benchmark command — Run accuracy and performance benchmarks against fixtures."""

import os
import sys
import json
from typing import Dict, Any

from commands import register_command

BENCHMARKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "benchmarks")


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--quick", action="store_true",
                        help="Run quick subset (4 commands only)")
    parser.add_argument("--fixture", type=str, default=None,
                        help="Run benchmarks for a specific fixture only")
    parser.add_argument("--compare", type=str, default=None,
                        help="Compare results against a baseline JSON file")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Save results to a specific JSON file")
    parser.add_argument("--update-snapshot", action="store_true",
                        help="Save results as new regression baseline")


def execute(args, workspace):
    """Execute the benchmark suite and return AI-friendly results."""
    if BENCHMARKS_DIR not in sys.path:
        sys.path.insert(0, BENCHMARKS_DIR)

    try:
        from run_benchmarks import run_benchmark_suite
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_benchmarks", os.path.join(BENCHMARKS_DIR, "run_benchmarks.py"))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            run_benchmark_suite = mod.run_benchmark_suite
        else:
            return {"status": "error", "error": "Could not import benchmark runner",
                    "error_type": "import_error"}

    results = run_benchmark_suite(
        fixture_name=args.fixture, quick=args.quick,
        output_file=args.output, compare_file=args.compare,
    )

    summary = results.get("summary", {})
    items = []
    for fn, fd in results.get("fixtures", {}).items():
        for cn, cd in fd.get("commands", {}).items():
            items.append({
                "fixture": fn, "command": cn,
                "description": cd.get("description", ""),
                "f1": cd.get("metrics", {}).get("f1", 0),
                "precision": cd.get("metrics", {}).get("precision", 0),
                "recall": cd.get("metrics", {}).get("recall", 0),
                "fpr": cd.get("metrics", {}).get("fpr", 0),
                "expected": cd.get("expected_count", 0),
                "found": cd.get("found_count", 0),
                "meets_target": cd.get("meets_target", False),
                "beats_competitor": cd.get("beats_competitor", False),
                "elapsed_seconds": cd.get("elapsed_seconds", 0),
            })

    result = {
        "status": "ok",
        "command": "benchmark",
        "stats": {
            "avg_f1": summary.get("avg_f1", 0),
            "avg_precision": summary.get("avg_precision", 0),
            "avg_recall": summary.get("avg_recall", 0),
            "avg_fpr_clean": summary.get("avg_fpr_clean", 0),
            "meets_target_pct": summary.get("meets_target_pct", 0),
            "beats_competitor_pct": summary.get("beats_competitor_pct", 0),
            "total_commands": summary.get("total_commands_run", 0),
        },
        "items": items,
        "token_efficiency": results.get("token_efficiency", {}),
    }

    if getattr(args, 'update_snapshot', False):
        try:
            if BENCHMARKS_DIR not in sys.path:
                sys.path.insert(0, BENCHMARKS_DIR)
            from check_regression import save_snapshot
            save_snapshot(results)
        except Exception:
            pass

    return result


register_command("benchmark", "Run accuracy and performance benchmarks", add_args, execute)
