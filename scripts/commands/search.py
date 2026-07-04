"""search command — unified symbol/semantic/graph search (issue #195 consolidation).

Umbrella command that absorbs:
  - symbols          (exact symbol name lookup)
  - semantic-query   (TF-IDF semantic search by meaning)
  - query-graph      (Cypher-subset graph query)
  - search           (regex code search — the legacy behavior)

Default mode is **semantic** (find symbols by meaning). Switch via --mode:

    codelens search <workspace> "google auth"                    # semantic
    codelens search <workspace> "google auth" --mode symbol      # exact name
    codelens search <workspace> "google auth" --mode regex       # regex code
    codelens search <workspace> "MATCH (n) WHERE n.id CONTAINS x" --mode graph

For raw Cypher pass-through (power user), prefer ``codelens graph <query>``.

Output: ``{"s":"ok", "st":{...}, "r":[...]}`` shape.
"""

import argparse
import os
import sys
from typing import Any, Dict

from commands import register_command


_MODES = ("semantic", "symbol", "regex", "graph", "list", "query")


def add_args(parser):
    """Add search-specific arguments to the parser."""
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Search modes (issue #195):\n"
        "  semantic  TF-IDF semantic search by meaning (default)\n"
        "  symbol    Exact symbol name lookup (fuzzy optional)\n"
        "  regex     Regex code search across workspace files\n"
        "  graph     Cypher-subset graph query (MATCH/WHERE/RETURN/LIMIT)\n"
        "  list      List all registry entries with optional filter (issue #200)\n"
        "  query     Query a specific class/id/function with callers/callees (issue #200)\n"
        "\n"
        "Examples:\n"
        "  codelens search . \"google auth\"                    # semantic (default)\n"
        "  codelens search . \"google auth\" --mode symbol      # exact symbol\n"
        "  codelens search . \"handleChange\" --mode regex       # regex code search\n"
        "  codelens search . \"MATCH (n) WHERE n.id CONTAINS x\" --mode graph\n"
        "  codelens search . --mode list                          # list all entries\n"
        "  codelens search submit-btn --mode query               # query a symbol\n"
        "\n"
        "For raw Cypher pass-through, prefer ``codelens graph <query>``."
    )
    parser.add_argument("pattern", nargs="?", default=None,
                        help="Search query (semantic query, symbol name, regex, or Cypher). "
                             "Optional for --mode list.")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--mode", default="semantic", choices=_MODES,
                        help=f"Search mode. Choices: {', '.join(_MODES)}. Default: semantic.")
    # Regex-mode passthroughs (legacy `search` command flags).
    parser.add_argument("--type", dest="file_type", default=None,
                        help="regex mode: file type filter (html, css, js, ts, tsx, rust, python, vue, svelte)")
    parser.add_argument("--file", default=None,
                        help="regex mode: filter by file path substring")
    parser.add_argument("--max-results", type=int, default=200,
                        help="regex mode: max results (default 200)")
    parser.add_argument("--context", type=int, default=0,
                        help="regex mode: context lines around match")
    parser.add_argument("--ignore-case", action="store_true",
                        help="regex mode: case-insensitive search")
    parser.add_argument("--whole-word", action="store_true",
                        help="regex mode: match whole words only")
    # Symbol-mode passthroughs.
    parser.add_argument("--domain", default=None,
                        help="symbol mode: frontend|backend|all (default all)")
    parser.add_argument("--fuzzy", action="store_true", default=False,
                        help="symbol mode: fuzzy name matching")
    # Semantic-mode passthroughs.
    parser.add_argument("--top", type=int, default=None, metavar="N",
                        help="semantic/symbol mode: limit to top N results")
    # Graph-mode passthroughs.
    parser.add_argument("--validate", action="store_true", default=False,
                        help="graph mode: validate query without executing")
    parser.add_argument("--limit", type=int, default=None,
                        help="Result limit (applies in all modes)")
    parser.add_argument("--offset", type=int, default=0,
                        help="regex/symbol mode: pagination offset (default: 0)")
    parser.add_argument("--db-path", default=None,
                        help="Custom SQLite database path (semantic/graph modes)")
    # list-mode passthroughs (issue #200).
    parser.add_argument("--filter", dest="filter_type", default=None,
                        choices=["all", "dead", "duplicate_define", "duplicate_ref",
                                 "collision", "active"],
                        help="list mode: filter by status (default: all)")
    # query-mode passthroughs (issue #200).
    parser.add_argument("--all", dest="all_results", action="store_true", default=False,
                        help="query mode: return all callers/callees (no limit)")
    parser.add_argument("--additional-paths", default=None, metavar="PATHS",
                        help="query mode: comma-separated extra repo roots for cross-repo query (issue #15)")


def _run_semantic(args, workspace) -> Dict[str, Any]:
    from semantic_search_engine import semantic_query
    top_k = getattr(args, "top", None) or 10
    result = semantic_query(workspace=workspace, query=args.pattern,
                            top_k=top_k, db_path=getattr(args, "db_path", None))
    return result


def _run_symbol(args, workspace) -> Dict[str, Any]:
    from symbols_engine import search_symbols
    domain = getattr(args, "domain", None) or "all"
    fuzzy = getattr(args, "fuzzy", False)
    limit = getattr(args, "limit", None) or 20
    offset = getattr(args, "offset", 0)
    result = search_symbols(workspace, args.pattern, domain=domain,
                            fuzzy=fuzzy, max_results=500)
    if isinstance(result, dict) and "results" in result:
        items = result["results"]
        total = len(items)
        end = offset + (limit if limit and limit > 0 else total)
        result["results"] = items[offset:end]
        result["total_count"] = total
        result["count"] = len(result["results"])
        result["offset"] = offset
        result["limit"] = limit
        result["has_more"] = end < total
    return result


def _run_regex(args, workspace) -> Dict[str, Any]:
    from search_engine import search_workspace
    from registry import load_config
    config = load_config(os.path.abspath(workspace))
    top_n = getattr(args, 'top', None)
    if top_n is not None and getattr(args, 'limit', None) is None:
        args.limit = top_n
    result = search_workspace(
        workspace, args.pattern,
        file_type=args.file_type,
        file_filter=args.file,
        max_results=args.max_results,
        context_lines=args.context,
        case_sensitive=not args.ignore_case,
        whole_word=args.whole_word,
        config=config,
    )
    if isinstance(result, dict) and "matches" in result:
        matches = result["matches"]
        total = len(matches)
        limit = args.limit if args.limit and args.limit > 0 else total
        offset = max(args.offset, 0)
        paginated = matches[offset:offset + limit]
        result["matches"] = paginated
        result["total_count"] = total
        result["count"] = len(paginated)
        result["offset"] = offset
        result["limit"] = limit
        result["has_more"] = (offset + limit) < total
    return result


def _run_graph(args, workspace) -> Dict[str, Any]:
    from commands.query_graph import execute as _qg_execute
    # query_graph.execute reads: query, workspace, limit, validate, db_path
    sub_args = argparse.Namespace(
        query=args.pattern,
        workspace=getattr(args, "workspace", None),
        limit=getattr(args, "limit", None),
        validate=getattr(args, "validate", False),
        db_path=getattr(args, "db_path", None),
        format=getattr(args, "format", None),
        top=None, max_tokens=None, lite=False, deep=False,
        diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    return _qg_execute(sub_args, workspace)


def _run_list(args, workspace) -> Dict[str, Any]:
    """List all registry entries with optional filter (issue #200).

    Delegates to ``commands.list.execute()``. The ``pattern`` positional is
    repurposed as an optional name filter — when None, all entries are listed.

    Because ``pattern`` is the first positional in the search parser, a common
    invocation is ``search /path/to/ws --mode list`` where the user intends
    the path to be the workspace, not a name filter. We detect this case
    (workspace is None and pattern looks like a directory) and swap them.
    """
    from commands.list import execute as _list_execute
    pattern = getattr(args, "pattern", None)
    ws = getattr(args, "workspace", None)
    # Heuristic: if workspace wasn't given but pattern is an existing dir,
    # the user meant the path as the workspace (list mode has no query arg).
    if ws is None and pattern and os.path.isdir(pattern):
        ws = pattern
        pattern = None
    sub_args = argparse.Namespace(
        workspace=ws,
        domain=getattr(args, "domain", None) or "all",
        filter_type=getattr(args, "filter_type", None) or "all",
        limit=getattr(args, "limit", None) or 20,
        offset=getattr(args, "offset", 0),
        format=getattr(args, "format", None),
        top=None, max_tokens=None, lite=False, deep=False, db_path=None,
        diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = _list_execute(sub_args, workspace if workspace else ws)
    # If a pattern filter was given (and not consumed as workspace), narrow
    # results by name substring.
    if pattern and isinstance(result, dict) and "results" in result:
        filtered = [r for r in result["results"]
                    if pattern in str(r.get("name", ""))]
        result["results"] = filtered
        result["count"] = len(filtered)
        result["filtered_by"] = pattern
    return result


def _run_query(args, workspace) -> Dict[str, Any]:
    """Query a specific class/id/function with callers/callees (issue #200).

    Delegates to ``commands.query.execute()``. The ``pattern`` positional is
    the symbol name to query.
    """
    from commands.query import execute as _query_execute
    sub_args = argparse.Namespace(
        name=args.pattern,
        workspace=getattr(args, "workspace", None),
        domain=getattr(args, "domain", None),
        file=getattr(args, "file", None),
        limit=None if getattr(args, "all_results", False) else (getattr(args, "limit", None) or 20),
        all=getattr(args, "all_results", False),
        fuzzy=getattr(args, "fuzzy", False),
        additional_paths=getattr(args, "additional_paths", None),
        format=getattr(args, "format", None),
        top=None, max_tokens=None, lite=False, deep=False, db_path=None,
        diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    return _query_execute(sub_args, workspace)


def execute(args, workspace):
    """Dispatch to the selected search mode and normalize output shape.

    @FLOW:    SEARCH_DISPATCH
    @CALLS:   _run_semantic() | _run_symbol() | _run_regex() | _run_graph()
              | _run_list() | _run_query() -> dict
    @MUTATES: nothing (read-only)
    """
    mode = getattr(args, "mode", "semantic") or "semantic"
    pattern = getattr(args, "pattern", None)
    # Modes that require a pattern. list mode allows pattern=None (list all).
    _PATTERN_REQUIRED = {"semantic", "symbol", "regex", "graph", "query"}
    if mode in _PATTERN_REQUIRED and not pattern:
        return {
            "s": "error", "st": {"mode": mode}, "r": [],
            "error": f"--mode {mode} requires a pattern (search query / symbol name).",
        }
    try:
        if mode == "semantic":
            result = _run_semantic(args, workspace)
        elif mode == "symbol":
            result = _run_symbol(args, workspace)
        elif mode == "regex":
            result = _run_regex(args, workspace)
        elif mode == "graph":
            result = _run_graph(args, workspace)
        elif mode == "list":
            result = _run_list(args, workspace)
        elif mode == "query":
            result = _run_query(args, workspace)
        else:
            return {"s": "error", "st": {"mode": mode}, "r": [],
                    "error": f"unknown mode '{mode}'"}
    except Exception as exc:
        return {"s": "error", "st": {"mode": mode},
                "r": [], "error": str(exc),
                "error_type": type(exc).__name__}

    # Normalize to {s, st, r} shape while preserving original payload.
    if not isinstance(result, dict):
        return {"s": "ok", "st": {"mode": mode}, "r": [{"result": result}]}
    status = result.pop("status", "ok")
    # Move large payload lists into ``r`` if present, keep stats in ``st``.
    rows = None
    for key in ("matches", "results", "rows", "findings"):
        if key in result and isinstance(result[key], list):
            rows = result.pop(key)
            break
    return {
        "s": status,
        "st": {"mode": mode, **result},
        "r": rows if rows is not None else [],
    }


register_command(
    "search",
    "Unified search: semantic (default) / symbol / regex / graph (issue #195)",
    add_args,
    execute,
)
