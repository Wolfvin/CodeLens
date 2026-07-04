"""impact command — change-impact & dataflow analysis (issue #195 consolidation).

Umbrella command that absorbs:
  - impact    Change impact for a symbol (default)
  - diff      Compare registry snapshots (--git-aware for git-diff delta)
  - dataflow  Trace data flow source→sink with cross-file call graph

Usage:
    codelens impact <workspace> --name handleAuth              # impact (default)
    codelens impact <workspace> --check impact --name handleAuth
    codelens impact <workspace> --check diff --git-aware
    codelens impact <workspace> --check dataflow --source src/api.ts --sink db.query

Output: ``{"s":"ok", "st":{...}, "r":[...]}``.
"""

# @WHO:   scripts/commands/impact.py
# @WHAT:  Umbrella command for change-impact & dataflow analysis.
# @PART:  commands
# @ENTRY: execute()

import argparse
import importlib
import sys
from typing import Any, Dict, List

from commands import register_command


_CHECKS = {
    "impact": {
        "module": None,  # handled inline (legacy impact.execute logic below)
        "help": "Analyze change impact for a symbol",
    },
    "diff": {
        "module": "commands.diff",
        "help": "Compare registry snapshots (--git-aware for git-diff delta)",
    },
    "dataflow": {
        "module": "commands.dataflow",
        "help": "Trace data flow source→sink with cross-file call graph",
    },
}

ALL_CHECKS = list(_CHECKS.keys())


def add_args(parser):
    """Add impact-specific arguments to the parser."""
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Sub-analyses (issue #195):\n"
        "  impact    Analyze change impact for a symbol (default)\n"
        "  diff      Compare registry snapshots (--git-aware for git-diff delta)\n"
        "  dataflow  Trace data flow source→sink with cross-file call graph\n"
        "\n"
        "Examples:\n"
        "  codelens impact . --name handleAuth              # impact (default)\n"
        "  codelens impact . --check diff --git-aware\n"
        "  codelens impact . --check dataflow --source src/api.ts --sink db.query\n"
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--check", default=None,
                        help=f"Comma-separated sub-analyses. "
                             f"Choices: {', '.join(ALL_CHECKS)}. Default: impact.")
    parser.add_argument("--name", default=None,
                        help="impact: symbol name to analyze")
    parser.add_argument("--action", choices=["modify", "delete"], default="modify",
                        help="impact: planned action (default: modify)")
    parser.add_argument("--domain", default="auto",
                        help="impact: frontend|backend|auto (default: auto)")
    parser.add_argument("--depth", type=int, default=None,
                        help="impact/dataflow: trace depth (default: impact=5, dataflow=15)")
    # diff passthroughs
    parser.add_argument("--snapshot1", default=None, help="diff: first snapshot path")
    parser.add_argument("--snapshot2", default=None, help="diff: second snapshot path")
    parser.add_argument("--list-snapshots", action="store_true", default=False,
                        help="diff: list available snapshots and exit")
    parser.add_argument("--git-aware", action="store_true", default=False,
                        help="diff: use git-diff delta + impact")
    # dataflow passthroughs
    parser.add_argument("--source", default=None, help="dataflow: source function")
    parser.add_argument("--sink", default=None, help="dataflow: sink function")
    parser.add_argument("--max-files", type=int, default=None,
                        help="dataflow: file cap (default 3000)")
    parser.add_argument("--timeout", type=int, default=None,
                        help="dataflow: timeout in seconds (default 120)")
    parser.add_argument("--cross-file", action="store_true", default=False,
                        help="dataflow: force cross-file analysis")
    parser.add_argument("--no-cross-file", action="store_true", default=False,
                        help="dataflow: disable cross-file analysis")
    parser.add_argument("--language", default=None,
                        help="dataflow: python|javascript|typescript")
    parser.add_argument("--call-graph-only", action="store_true", default=False,
                        help="dataflow: return only the call graph, no taint")


def _parse_checks(check_arg: str) -> List[str]:
    if not check_arg:
        return ["impact"]
    parts = [c.strip() for c in check_arg.split(",") if c.strip()]
    invalid = [p for p in parts if p not in _CHECKS]
    if invalid:
        print(
            f"[CodeLens] impact: unknown --check category '{','.join(invalid)}'. "
            f"Valid: {', '.join(ALL_CHECKS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return parts or ["impact"]


def _run_legacy_impact(args, workspace):
    """Run the original impact.execute logic (issue #195: absorbed)."""
    from impact_engine import analyze_impact
    name = getattr(args, "name", None) or ""
    action = getattr(args, "action", "modify")
    domain = getattr(args, "domain", "auto")
    depth = getattr(args, "depth", None) or 5
    result = analyze_impact(name, workspace, action=action, domain=domain, depth=depth)
    if result.get("status") == "ok":
        engine_risk = result.get("risk", "low")
        stats = result.get("stats", {})
        direct_dependents = stats.get("direct_dependents", 0)
        indirect_dependents = stats.get("indirect_dependents", 0)
        affected_files = stats.get("affected_files", 0)
        result["risk_level"] = engine_risk
        if engine_risk == "critical":
            result["recommended_action"] = "Critical risk. Consider refactoring to reduce dependencies first."
        elif engine_risk == "high":
            result["recommended_action"] = "High risk. Thoroughly test all affected code after changes."
        elif engine_risk == "medium":
            result["recommended_action"] = "Proceed with caution. Review affected code before changing."
        else:
            result["recommended_action"] = "Safe to proceed. No dependent code found."
        try:
            from hybrid_engine import create_hybrid_engine
            engine = create_hybrid_engine(workspace, deep=False)
            engine.enhance_impact(result, name)
            engine.cleanup()
        except Exception:
            result.setdefault("confidence", "medium")
    return result


def _build_namespace(base_args, check_name: str) -> argparse.Namespace:
    ns = argparse.Namespace()
    for attr in ("format", "top", "max_tokens", "lite", "deep", "db_path",
                 "diff_base", "diff_scope", "disable_suppression",
                 "codelens_ignore_pattern"):
        setattr(ns, attr, getattr(base_args, attr, None))
    ns.workspace = getattr(base_args, "workspace", None)
    if check_name == "diff":
        ns.snapshot1 = getattr(base_args, "snapshot1", None)
        ns.snapshot2 = getattr(base_args, "snapshot2", None)
        ns.list_snapshots = getattr(base_args, "list_snapshots", False)
        ns.git_aware = getattr(base_args, "git_aware", False)
    elif check_name == "dataflow":
        ns.source = getattr(base_args, "source", None)
        ns.sink = getattr(base_args, "sink", None)
        ns.depth = getattr(base_args, "depth", None) or 15
        ns.max_files = getattr(base_args, "max_files", None) or 3000
        ns.timeout = getattr(base_args, "timeout", None) or 120
        ns.cross_file = getattr(base_args, "cross_file", False)
        ns.no_cross_file = getattr(base_args, "no_cross_file", False)
        ns.language = getattr(base_args, "language", None)
        ns.call_graph_only = getattr(base_args, "call_graph_only", False)
    return ns


def execute(args, workspace):
    """Run one or more impact/dataflow checks and merge results.

    @FLOW:    IMPACT_DISPATCH
    @CALLS:   _parse_checks() -> List[str]
              _run_legacy_impact() | commands.<sub>.execute() -> dict per sub
    @MUTATES: nothing (read-only)
    """
    checks = _parse_checks(getattr(args, "check", None))
    results: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {"checks_run": 0, "checks_failed": 0}

    for check_name in checks:
        try:
            if check_name == "impact":
                sub_result = _run_legacy_impact(args, workspace)
            else:
                mod = importlib.import_module(_CHECKS[check_name]["module"])
                sub_args = _build_namespace(args, check_name)
                sub_result = mod.execute(sub_args, workspace)
            if not isinstance(sub_result, dict):
                sub_result = {"status": "ok", "result": sub_result}
            sub_result["_check"] = check_name
            results.append(sub_result)
            stats["checks_run"] += 1
        except Exception as exc:
            stats["checks_failed"] += 1
            stats["checks_run"] += 1
            results.append({
                "_check": check_name,
                "s": "error",
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            print(
                f"[CodeLens] impact: --check {check_name} failed: {exc}",
                file=sys.stderr,
            )

    return {
        "s": "ok" if stats["checks_failed"] == 0 else "partial",
        "st": {
            "checks_requested": len(checks),
            **stats,
        },
        "r": results,
    }


register_command(
    "impact",
    "Change-impact & dataflow: impact (default) / diff / dataflow (issue #195)",
    add_args,
    execute,
)
