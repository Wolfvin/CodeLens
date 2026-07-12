"""audit command — code-quality checks (issue #195 consolidation).

Umbrella command that absorbs:
  - dead-code     Enhanced dead code detection
  - complexity    Cyclomatic/cognitive complexity
  - smell         Code smells across workspace
  - staleness     Per-file staleness detection
  - perf-hint     Performance anti-patterns
  - side-effect   Pure vs impure function analysis

(god-module from the issue mapping is part of arch-metrics, exposed via
``summary --check arch-metrics`` — there is no standalone god-module command
to absorb here.)

Usage:
    codelens audit <workspace>                              # all checks
    codelens audit <workspace> --check dead-code            # only dead-code
    codelens audit <workspace> --check complexity,smell     # pick subset

Output: ``{"s":"ok", "st":{...}, "r":[...]}`` — one entry per check under
``r`` and aggregate counts under ``st``.
"""

# @WHO:   scripts/commands/audit.py
# @WHAT:  Umbrella command for code-quality audits.
# @PART:  commands
# @ENTRY: execute()

import argparse
import importlib
import sys
from typing import Any, Dict, List

from commands import register_command


_CHECKS = {
    "dead-code": {
        "module": "commands.dead_code",
        "help": "Enhanced dead code detection",
    },
    "complexity": {
        "module": "commands.complexity",
        "help": "Cyclomatic/cognitive complexity",
    },
    "smell": {
        "module": "commands.smell",
        "help": "Code smells across workspace",
    },
    "staleness": {
        "module": "commands.staleness",
        "help": "Per-file staleness detection",
    },
    "perf-hint": {
        "module": "commands.perf_hint",
        "help": "Performance anti-patterns",
    },
    "side-effect": {
        "module": "commands.side_effect",
        "help": "Pure vs impure function analysis",
    },
}

ALL_CHECKS = list(_CHECKS.keys())


def add_args(parser):
    """Add audit-specific arguments to the parser."""
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Sub-analyses (issue #195):\n"
        "  dead-code     Enhanced dead code detection\n"
        "  complexity    Cyclomatic/cognitive complexity\n"
        "  smell         Code smells across workspace\n"
        "  staleness     Per-file staleness detection\n"
        "  perf-hint     Performance anti-patterns\n"
        "  side-effect   Pure vs impure function analysis\n"
        "\n"
        "Examples:\n"
        "  codelens audit .                          # all checks\n"
        "  codelens audit . --check dead-code        # only dead-code\n"
        "  codelens audit . --check complexity,smell # pick subset\n"
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--check", default=None,
                        help=f"Comma-separated sub-analyses. "
                             f"Choices: {', '.join(ALL_CHECKS)}. Default: all.")
    # Common passthroughs.
    parser.add_argument("--max-files", type=int, default=None,
                        help="dead-code/smell/perf-hint/side-effect/complexity: file cap")
    parser.add_argument("--max-results", type=int, default=None,
                        help="dead-code: max results per category")
    parser.add_argument("--categories", nargs="+", default=None,
                        help="dead-code/smell: sub-category filter")
    parser.add_argument("--severity", default=None,
                        help="smell/perf-hint: info|warning|critical (smell) or "
                             "critical|high|medium|low (perf-hint)")
    parser.add_argument("--threshold", type=int, default=None,
                        help="complexity: minimum complexity threshold")
    parser.add_argument("--sort", dest="sort_by", default=None,
                        help="complexity: complexity|cognitive|loc")
    parser.add_argument("--name", default=None,
                        help="complexity/side-effect: function name filter")
    parser.add_argument("--file", default=None,
                        help="complexity/side-effect: file path filter")
    parser.add_argument("--limit", type=int, default=None,
                        help="staleness/complexity: result limit")
    parser.add_argument("--category", default=None,
                        help="perf-hint: single category filter")
    parser.add_argument("--no-confirm-hash", action="store_true", default=False,
                        help="staleness: skip content-hash confirmation")
    parser.add_argument("--no-verify-impact", dest="verify_impact",
                        action="store_false", default=True,
                        help="dead-code: skip per-finding deletion_safety cross-check "
                             "against impact analysis (issue #238)")
    parser.add_argument("--verify-impact-limit", type=int, default=None,
                        help="dead-code: max findings to cross-check with impact "
                             "analysis (default: 20)")


def _parse_checks(check_arg: str) -> List[str]:
    if not check_arg:
        return list(ALL_CHECKS)
    parts = [c.strip() for c in check_arg.split(",") if c.strip()]
    invalid = [p for p in parts if p not in _CHECKS]
    if invalid:
        print(
            f"[CodeLens] audit: unknown --check category '{','.join(invalid)}'. "
            f"Valid: {', '.join(ALL_CHECKS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return parts or list(ALL_CHECKS)


def _build_namespace(base_args, check_name: str) -> argparse.Namespace:
    ns = argparse.Namespace()
    for attr in ("format", "top", "max_tokens", "lite", "deep", "db_path",
                 "diff_base", "diff_scope", "disable_suppression",
                 "codelens_ignore_pattern"):
        setattr(ns, attr, getattr(base_args, attr, None))
    ns.workspace = getattr(base_args, "workspace", None)
    if check_name == "dead-code":
        ns.categories = getattr(base_args, "categories", None)
        ns.max_files = getattr(base_args, "max_files", None) or 3000
        ns.max_results = getattr(base_args, "max_results", None) or 100
        ns.verify_impact = getattr(base_args, "verify_impact", True)
        ns.verify_impact_limit = getattr(base_args, "verify_impact_limit", None) or 20
    elif check_name == "complexity":
        ns.name = getattr(base_args, "name", None)
        ns.file = getattr(base_args, "file", None)
        ns.threshold = getattr(base_args, "threshold", None)
        ns.sort_by = getattr(base_args, "sort_by", None)
        ns.limit = getattr(base_args, "limit", None)
        ns.max_files = getattr(base_args, "max_files", None) or 5000
    elif check_name == "smell":
        ns.categories = getattr(base_args, "categories", None)
        ns.severity = getattr(base_args, "severity", None)
        ns.max_files = getattr(base_args, "max_files", None) or 5000
    elif check_name == "staleness":
        # staleness has its own --format text/json; force json here so the
        # umbrella can merge it into the unified result shape.
        ns.format = "json"
        ns.no_confirm_hash = getattr(base_args, "no_confirm_hash", False)
        ns.max_files = getattr(base_args, "max_files", None) or 10000
        ns.limit = getattr(base_args, "limit", None) or 10
    elif check_name == "perf-hint":
        ns.severity = getattr(base_args, "severity", None)
        ns.category = getattr(base_args, "category", None)
        ns.max_files = getattr(base_args, "max_files", None) or 5000
    elif check_name == "side-effect":
        ns.name = getattr(base_args, "name", None)
        ns.file = getattr(base_args, "file", None)
        ns.max_files = getattr(base_args, "max_files", None) or 3000
    return ns


def execute(args, workspace):
    """Run one or more audit checks and merge results.

    @FLOW:    AUDIT_DISPATCH
    @CALLS:   _parse_checks() -> List[str]
              _build_namespace() -> argparse.Namespace
              commands.<sub>.execute() -> dict per sub
    @MUTATES: nothing (read-only analyses)
    """
    checks = _parse_checks(getattr(args, "check", None))
    results: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {"checks_run": 0, "checks_failed": 0}

    for check_name in checks:
        spec = _CHECKS[check_name]
        try:
            mod = importlib.import_module(spec["module"])
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
                f"[CodeLens] audit: --check {check_name} failed: {exc}",
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
    "audit",
    "Code-quality audits: dead-code / complexity / smell / staleness / perf-hint / side-effect",
    add_args,
    execute,
)
