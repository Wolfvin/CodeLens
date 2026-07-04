"""api-map command — API surface & graph schema (issue #195 consolidation).

Umbrella command that absorbs:
  - api-map        REST/GraphQL/gRPC routes to handlers (default)
  - graph-schema   Shape of the code graph (node/edge counts, type distribution)

(routes from the issue mapping does not exist as a registered command —
the route data is part of api-map's output.)

Usage:
    codelens api-map <workspace>                          # api-map (default)
    codelens api-map <workspace> --check api-map --method GET
    codelens api-map <workspace> --check graph-schema
    codelens api-map <workspace> --check api-map,graph-schema  # both

Output: ``{"s":"ok", "st":{...}, "r":[...]}``.
"""

# @WHO:   scripts/commands/api_map.py
# @WHAT:  Umbrella command for API surface & graph schema.
# @PART:  commands
# @ENTRY: execute()

import argparse
import importlib
import sys
from typing import Any, Dict, List

from commands import register_command


_CHECKS = {
    "api-map": {
        "module": None,  # handled inline
        "help": "Map REST/GraphQL/gRPC routes to handlers",
    },
    "graph-schema": {
        "module": "commands.graph_schema",
        "help": "Shape of the code graph (node/edge counts, type distribution)",
    },
}

ALL_CHECKS = list(_CHECKS.keys())


def add_args(parser):
    """Add api-map-specific arguments to the parser."""
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Sub-analyses (issue #195):\n"
        "  api-map        Map REST/GraphQL/gRPC routes to handlers (default)\n"
        "  graph-schema   Shape of the code graph (node/edge counts, types)\n"
        "\n"
        "Examples:\n"
        "  codelens api-map .                                  # api-map (default)\n"
        "  codelens api-map . --check api-map --method GET\n"
        "  codelens api-map . --check graph-schema\n"
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--check", default=None,
                        help=f"Comma-separated sub-analyses. "
                             f"Choices: {', '.join(ALL_CHECKS)}. Default: api-map.")
    parser.add_argument("--method", choices=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                        default=None, help="api-map: filter by HTTP method")
    parser.add_argument("--path", dest="path_filter", default=None,
                        help="api-map: filter by route path substring")
    parser.add_argument("--production-only", dest="production_only", action="store_true",
                        default=False,
                        help="api-map: filter out routes from test files")
    parser.add_argument("--db-path", default=None,
                        help="graph-schema: custom SQLite database path")


def _parse_checks(check_arg: str) -> List[str]:
    if not check_arg:
        return ["api-map"]
    parts = [c.strip() for c in check_arg.split(",") if c.strip()]
    invalid = [p for p in parts if p not in _CHECKS]
    if invalid:
        print(
            f"[CodeLens] api-map: unknown --check category '{','.join(invalid)}'. "
            f"Valid: {', '.join(ALL_CHECKS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return parts or ["api-map"]


def _run_legacy_api_map(args, workspace):
    from apimap_engine import map_api_routes
    return map_api_routes(workspace, method=args.method, path_filter=args.path_filter)


def _build_namespace(base_args, check_name: str) -> argparse.Namespace:
    ns = argparse.Namespace()
    for attr in ("format", "top", "max_tokens", "lite", "deep", "db_path",
                 "diff_base", "diff_scope", "disable_suppression",
                 "codelens_ignore_pattern"):
        setattr(ns, attr, getattr(base_args, attr, None))
    ns.workspace = getattr(base_args, "workspace", None)
    if check_name == "graph-schema":
        ns.db_path = getattr(base_args, "db_path", None)
    return ns


def execute(args, workspace):
    """Run one or more api-map sub-analyses and merge results.

    @FLOW:    API_MAP_DISPATCH
    @CALLS:   _parse_checks() -> List[str]
              _run_legacy_api_map() | commands.graph_schema.execute() -> dict
    @MUTATES: nothing (read-only)
    """
    checks = _parse_checks(getattr(args, "check", None))
    results: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {"checks_run": 0, "checks_failed": 0}

    for check_name in checks:
        try:
            if check_name == "api-map":
                sub_result = _run_legacy_api_map(args, workspace)
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
                f"[CodeLens] api-map: --check {check_name} failed: {exc}",
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
    "api-map",
    "API surface & graph schema: api-map (default) / graph-schema (issue #195)",
    add_args,
    execute,
)
