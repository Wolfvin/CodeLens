"""Trace command — Trace deep call chain from a symbol."""

import argparse
from trace_engine import trace_symbol, MAX_CHAIN_RESULTS
from commands import register_command


def add_args(parser):
    """Add trace-specific arguments to the parser."""
    # Issue #180: surface noise-reduction flags directly in `codelens trace --help`.
    # trace output can be deep (--depth default 10) — point users at compact/lite
    # so they don't drown in chain entries when called from AI/script context.
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Notes:\n"
        "  Use --direction up to find callers (who depends on this symbol),\n"
        "  --direction down to find callees. For AI/script consumption, use\n"
        "  --format compact (token-efficient single-char keys) or --lite\n"
        "  (minimal output). Paginate with --limit / --offset."
    )
    parser.add_argument("name", help="Symbol name to trace")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--direction", choices=["up", "down", "both"], default="up",
                        help="Trace direction: up=callers, down=callees, both")
    parser.add_argument("--depth", type=int, default=10, help="Max trace depth (default 10)")
    parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                        help="Domain to trace")
    parser.add_argument("--max-results", type=int, default=MAX_CHAIN_RESULTS,
                        help=f"Max chain entries to return (default {MAX_CHAIN_RESULTS})")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max chain entries to return after pagination (default: 20). "
                             "Use --limit 0 for unlimited (still bounded by --max-results).")
    parser.add_argument("--offset", type=int, default=0,
                        help="Offset for pagination of chain entries (default: 0)")
    # v8.2 (issue #8): toggle between the new graph backend (default) and the
    # legacy flat-registry backend. Default is graph with automatic fallback
    # to flat when the graph tables are empty. Use --no-graph to force the
    # flat path for A/B comparison.
    parser.add_argument(
        "--use-graph",
        dest="use_graph",
        action="store_true",
        default=True,
        help="Use the graph_nodes/graph_edges backend (default). "
             "Falls back to flat registry if graph tables are empty.",
    )
    parser.add_argument(
        "--no-graph",
        dest="use_graph",
        action="store_false",
        help="Force the legacy flat-registry backend (A/B testing).",
    )


def execute(args, workspace):
    """Execute the trace command."""
    use_graph = getattr(args, "use_graph", True)
    result = trace_symbol(
        args.name, workspace,
        direction=args.direction,
        max_depth=args.depth,
        domain=args.domain,
        max_results=args.max_results,
        use_graph=use_graph,
    )
    # Apply pagination to chains.up and chains.down (issue #17).
    if isinstance(result, dict) and isinstance(result.get("chains"), dict):
        chains = result["chains"]
        limit = getattr(args, 'limit', 20)
        offset = max(getattr(args, 'offset', 0), 0)
        total_count = 0
        for direction_key in ("up", "down"):
            if direction_key in chains and isinstance(chains[direction_key], list):
                page_limit = limit if limit and limit > 0 else len(chains[direction_key])
                full = chains[direction_key]
                total_count += len(full)
                chains[direction_key] = full[offset:offset + page_limit]
        result["total_count"] = total_count
        result["offset"] = offset
        result["limit"] = limit
    return result

# Issue #199: deprecated "trace" alias registration removed; this module is now an implementation module imported by the "context" umbrella command.
