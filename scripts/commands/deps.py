"""deps command — dependency graph intelligence (issue #195 consolidation).

Umbrella command that absorbs:
  - affected         (which test files are affected by source changes)
  - dependents       (module-level import tracking)
  - circular         (circular dependency detection)
  - import-snapshot  (import .codelens.gz snapshot into the graph DB)

Usage:
    codelens deps <workspace>                          # run all checks
    codelens deps <workspace> --check circular         # only circular
    codelens deps <workspace> --check affected,dependents
    codelens deps <workspace> --check import-snapshot --input path.codelens.gz
    codelens deps auth/foo.ts --check affected         # symbol-aware mode

Output (compact / json): ``{"s":"ok", "st":{...}, "r":[...]}`` shape with
one entry per requested check under ``r`` and aggregate stats under ``st``.
"""

# @WHO:   scripts/commands/deps.py
# @WHAT:  Umbrella command for dependency-graph intelligence.
# @PART:  commands
# @ENTRY: execute()

import argparse
import os
import sys
from typing import Any, Dict, List

from commands import register_command


# Map each --check category to (module_path, execute_attr, required_args).
# ``required_args`` is a function(args) -> dict of namespace attributes that
# MUST be present on the synthetic namespace before delegating.
_CHECKS = {
    "affected": {
        "module": "commands.affected",
        "help": "Identify test files affected by source changes",
    },
    "dependents": {
        "module": "commands.dependents",
        "help": "Module-level import tracking",
    },
    "circular": {
        "module": "commands.circular",
        "help": "Detect circular dependencies",
    },
    "import-snapshot": {
        "module": "commands.import_snapshot",
        "help": "Import a .codelens.gz snapshot into the graph DB",
    },
}

ALL_CHECKS = list(_CHECKS.keys())


def add_args(parser):
    """Add deps-specific arguments to the parser."""
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Sub-analyses (issue #195):\n"
        "  affected          Test files affected by source changes\n"
        "  dependents        Module-level import tracking\n"
        "  circular          Circular dependency detection\n"
        "  import-snapshot   Import .codelens.gz into graph DB\n"
        "\n"
        "Examples:\n"
        "  codelens deps .                              # all checks\n"
        "  codelens deps . --check circular             # only circular\n"
        "  codelens deps . --check affected,dependents  # pick subset\n"
        "  codelens deps . --check import-snapshot --input s.codelens.gz\n"
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--check", default=None,
                        help=f"Comma-separated sub-analyses to run. "
                             f"Choices: {', '.join(ALL_CHECKS)}. "
                             f"Default: run all.")
    # Sub-command specific flags — passed through to the delegated executor.
    parser.add_argument("--files", nargs="*", default=None,
                        help="affected: source files to analyze")
    parser.add_argument("--depth", type=int, default=None,
                        help="affected/dependents: traversal depth")
    parser.add_argument("--filter", default=None,
                        help="affected: glob filter for test files")
    parser.add_argument("--include-source", action="store_true", default=False,
                        help="affected: include source dependents in output")
    parser.add_argument("--direction", default=None,
                        help="dependents: dependents|dependencies|graph")
    parser.add_argument("--domain", default=None,
                        help="circular: backend|imports|css|all")
    parser.add_argument("--max-cycles", type=int, default=None,
                        help="circular: max cycles per type")
    parser.add_argument("--input", default=None,
                        help="import-snapshot: path to .codelens.gz file")
    parser.add_argument("--merge", action="store_true", default=False,
                        help="import-snapshot: deduplicate with existing graph")
    parser.add_argument("--db-path", default=None,
                        help="Custom SQLite database path")


def _parse_checks(check_arg: str) -> List[str]:
    """Parse --check argument into a list of valid check names."""
    if not check_arg:
        return list(ALL_CHECKS)
    parts = [c.strip() for c in check_arg.split(",") if c.strip()]
    invalid = [p for p in parts if p not in _CHECKS]
    if invalid:
        print(
            f"[CodeLens] deps: unknown --check category '{','.join(invalid)}'. "
            f"Valid: {', '.join(ALL_CHECKS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return parts or list(ALL_CHECKS)


def _build_namespace(base_args, check_name: str) -> argparse.Namespace:
    """Build a synthetic argparse.Namespace for the delegated sub-command.

    Only attributes the sub-command's ``add_args``/``execute`` reads are set;
    everything else falls back to ``None``/``False`` via ``getattr`` in the
    sub-command code.
    """
    ns = argparse.Namespace()
    # Carry over global flags the sub-commands may read.
    for attr in ("format", "top", "max_tokens", "lite", "deep", "db_path",
                 "diff_base", "diff_scope", "disable_suppression",
                 "codelens_ignore_pattern"):
        setattr(ns, attr, getattr(base_args, attr, None))
    # Workspace + check-specific passthroughs.
    ns.workspace = getattr(base_args, "workspace", None)
    if check_name == "affected":
        ns.files = getattr(base_args, "files", None) or []
        ns.depth = getattr(base_args, "depth", None) or 5
        ns.filter = getattr(base_args, "filter", None)
        ns.include_source = getattr(base_args, "include_source", False)
        ns.as_json = True  # always JSON; main formatter handles --format
        ns.quiet = False
        ns.stdin = False
    elif check_name == "dependents":
        ns.file = (getattr(base_args, "files", None) or [None])[0]
        ns.direction = getattr(base_args, "direction", None) or "dependents"
        ns.depth = getattr(base_args, "depth", None) or 3
    elif check_name == "circular":
        ns.domain = getattr(base_args, "domain", None) or "all"
        ns.max_cycles = getattr(base_args, "max_cycles", None)
        if ns.max_cycles is None:
            # Defer default to the engine — load lazily.
            try:
                from circular_engine import MAX_CYCLES_PER_TYPE
                ns.max_cycles = MAX_CYCLES_PER_TYPE
            except Exception:
                ns.max_cycles = 50
    elif check_name == "import-snapshot":
        ns.input = getattr(base_args, "input", None)
        ns.merge = getattr(base_args, "merge", False)
        ns.db_path = getattr(base_args, "db_path", None)
    return ns


def execute(args, workspace):
    """Run one or more dependency-graph checks and merge results.

    @FLOW:    DEPS_DISPATCH
    @CALLS:   _parse_checks() -> List[str]
              _build_namespace() -> argparse.Namespace
              commands.<sub>.execute() -> dict per sub
    @MUTATES: graph DB (only import-snapshot writes)
    """
    checks = _parse_checks(getattr(args, "check", None))
    results: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {"checks_run": 0, "checks_failed": 0}

    for check_name in checks:
        spec = _CHECKS[check_name]
        try:
            import importlib
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
                f"[CodeLens] deps: --check {check_name} failed: {exc}",
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
    "deps",
    "Dependency-graph intelligence: affected / dependents / circular / import-snapshot",
    add_args,
    execute,
)
