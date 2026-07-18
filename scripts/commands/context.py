"""context command — symbol & codebase context (issue #195 consolidation).

Umbrella command that absorbs:
  - context   (rich symbol context — legacy, was a query subset)
  - outline   (file structure outline)
  - trace     (deep call chain from a symbol)
  - orient    (10-second codebase orientation brief)

Usage:
    codelens context <workspace>                          # orient (default)
    codelens context <workspace> --check orient           # explicit orient
    codelens context <workspace> --check outline --file src/app.ts
    codelens context <workspace> --check trace --name handleAuth
    codelens context <workspace> --check context --name handleAuth

When --check is omitted, defaults to ``orient`` (the broadest useful default
for "give me context on this codebase"). Pass ``--name`` for symbol-specific
checks (trace, context).

Output: ``{"s":"ok", "st":{...}, "r":[...]}``.
"""

# @WHO:   scripts/commands/context.py
# @WHAT:  Umbrella command for codebase/symbol context.
# @PART:  commands
# @ENTRY: execute()

import argparse
import importlib
import sys
from typing import Any, Dict, List

from commands import register_command


_CHECKS = {
    "context": {
        "module": "commands.query",  # legacy context delegated to query
        "help": "Rich symbol context (callers, callees, metrics)",
    },
    "outline": {
        "module": "commands.outline",
        "help": "File structure outline",
    },
    "trace": {
        "module": "commands.trace",
        "help": "Deep call chain from a symbol",
    },
    "orient": {
        "module": "commands.orient",
        "help": "10-second codebase orientation brief",
    },
    "diagnostics": {
        "module": "commands.diagnostics",
        "help": "LSP lint/errors/warnings for a file (issue #253, needs --file)",
    },
    "overview": {
        "module": "commands.symbols_overview",
        "help": "Token-efficient hierarchical symbols map from registry (issue #254)",
    },
    "tags": {
        "module": "commands.tags",
        "help": "Audit @FLOW/@ENTRY/@PART doc-tags: flow inventory, header coverage, untagged files (issue #305)",
    },
    "flow": {
        "module": "commands.flow",
        "help": "Collect a named @FLOW's scattered functions into one view (--name X; issue #309)",
    },
    "source": {
        "module": "commands.source",
        "help": "Return a function's source by name — no need to read the whole file (--name X; issue #316)",
    },
}

ALL_CHECKS = list(_CHECKS.keys())


def add_args(parser):
    """Add context-specific arguments to the parser."""
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Sub-analyses (issue #195):\n"
        "  context   Rich symbol context (callers, callees, metrics)\n"
        "  outline   File structure outline\n"
        "  trace       Deep call chain from a symbol\n"
        "  orient      10-second codebase orientation brief\n"
        "  diagnostics LSP lint/errors/warnings for a file (needs --file, issue #253)\n"
        "  overview    Token-efficient hierarchical symbols map (issue #254)\n"
        "  tags        Audit @FLOW/@ENTRY/@PART doc-tags (issue #305)\n"
        "  flow        Collect a named @FLOW's scattered functions (--name X, issue #309)\n"
        "  source      Return a function's source by name (--name X, issue #316)\n"
        "\n"
        "Examples:\n"
        "  codelens context .                                  # orient (default)\n"
        "  codelens context . --check outline --file src/app.ts\n"
        "  codelens context . --check trace --name handleAuth\n"
        "  codelens context . --check context --name handleAuth\n"
        "  codelens context . --check diagnostics --file src/app.ts\n"
        "  codelens context . --check overview                 # workspace symbol map\n"
        "  codelens context . --check overview --file src/auth.ts\n"
        "  codelens context . --check tags                     # doc-tag audit\n"
        "  codelens context . --check flow                     # list all named flows\n"
        "  codelens context . --check flow --name PAYMENT      # collect one flow\n"
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--check", default=None,
                        help=f"Comma-separated sub-analyses. "
                             f"Choices: {', '.join(ALL_CHECKS)}. Default: orient.")
    parser.add_argument("--name", default=None,
                        help="context/trace: symbol name to analyze")
    parser.add_argument("--file", default=None,
                        help="outline: specific file path")
    parser.add_argument("--all", dest="all_files", action="store_true", default=False,
                        help="outline: outline all files")
    parser.add_argument("--detail", default=None,
                        help="outline: minimal|normal|full")
    parser.add_argument("--direction", default=None,
                        help="trace: up|down|both (default up)")
    parser.add_argument("--depth", type=int, default=None,
                        help="trace: max call depth (default 10)")
    parser.add_argument("--domain", default=None,
                        help="context/trace: frontend|backend|auto")
    parser.add_argument("--top", type=int, default=None, metavar="N",
                        help="orient: top-N start-here files (default 8)")
    parser.add_argument("--limit", type=int, default=None,
                        help="trace/outline: result limit")
    parser.add_argument("--offset", type=int, default=0,
                        help="trace/outline: pagination offset")
    parser.add_argument("--timeout", type=float, default=None,
                        help="diagnostics: seconds to wait for LSP to push diagnostics (default 3.0)")
    parser.add_argument("--max-files", type=int, default=None, dest="max_files",
                        help="overview: max files in workspace-wide mode (default: 200)")


def _parse_checks(check_arg: str) -> List[str]:
    if not check_arg:
        return ["orient"]  # sensible default for "give me context on this codebase"
    parts = [c.strip() for c in check_arg.split(",") if c.strip()]
    invalid = [p for p in parts if p not in _CHECKS]
    if invalid:
        print(
            f"[CodeLens] context: unknown --check category '{','.join(invalid)}'. "
            f"Valid: {', '.join(ALL_CHECKS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return parts or ["orient"]


def _build_namespace(base_args, check_name: str) -> argparse.Namespace:
    ns = argparse.Namespace()
    for attr in ("format", "top", "max_tokens", "lite", "deep", "db_path",
                 "diff_base", "diff_scope", "disable_suppression",
                 "codelens_ignore_pattern"):
        setattr(ns, attr, getattr(base_args, attr, None))
    ns.workspace = getattr(base_args, "workspace", None)
    if check_name == "context":
        # context delegates to query.execute — needs name + file + domain.
        ns.name = getattr(base_args, "name", None)
        ns.file = getattr(base_args, "file", None)
        domain = getattr(base_args, "domain", None)
        ns.domain = None if domain == "auto" else domain
    elif check_name == "outline":
        ns.file = getattr(base_args, "file", None)
        ns.detail = getattr(base_args, "detail", None) or "normal"
        ns.all_files = getattr(base_args, "all_files", False)
        ns.limit = getattr(base_args, "limit", None) or 20
        ns.offset = getattr(base_args, "offset", 0)
    elif check_name == "trace":
        ns.name = getattr(base_args, "name", None)
        ns.direction = getattr(base_args, "direction", None) or "up"
        ns.depth = getattr(base_args, "depth", None) or 10
        # trace_engine.trace_symbol() checks `domain in ("backend", "auto")`
        # / `("frontend", "auto")` — a bare None here matches neither branch,
        # so every trace silently returned 0 callers/callees regardless of
        # symbol or workspace. Must default to "auto" like trace.py's own
        # standalone add_args default, not fall through to None.
        ns.domain = getattr(base_args, "domain", None) or "auto"
        ns.limit = getattr(base_args, "limit", None) or 20
        ns.offset = getattr(base_args, "offset", 0)
        ns.max_results = 1000
        ns.use_graph = True
    elif check_name == "orient":
        # orient reads top via getattr; reuse the base value if set.
        pass  # ns.top already set above via carry-over
    elif check_name == "diagnostics":
        ns.file = getattr(base_args, "file", None)
        ns.timeout = getattr(base_args, "timeout", None) or 3.0
    elif check_name == "overview":
        ns.file = getattr(base_args, "file", None)
        ns.max_files = getattr(base_args, "max_files", None) or 200
    elif check_name == "flow":
        ns.name = getattr(base_args, "name", None)
    elif check_name == "source":
        ns.name = getattr(base_args, "name", None)
        ns.file = getattr(base_args, "file", None)
    return ns


def execute(args, workspace):
    """Run one or more context sub-analyses and merge results.

    @FLOW:    CONTEXT_DISPATCH
    @CALLS:   _parse_checks() -> List[str]
              _build_namespace() -> argparse.Namespace
              commands.<sub>.execute() -> dict per sub
    @MUTATES: nothing (read-only)
    """
    checks = _parse_checks(getattr(args, "check", None))
    results: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {"checks_run": 0, "checks_failed": 0}

    for check_name in checks:
        spec = _CHECKS[check_name]
        try:
            mod = importlib.import_module(spec["module"])
            sub_args = _build_namespace(args, check_name)
            # Special case: orient has its own text-mode printing; force json
            # so the umbrella can merge it.
            if check_name == "orient":
                if not getattr(sub_args, "format", None):
                    sub_args.format = "json"
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
                f"[CodeLens] context: --check {check_name} failed: {exc}",
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
    "context",
    "Codebase & symbol context: orient (default) / outline / trace / context (issue #195)",
    add_args,
    execute,
)
