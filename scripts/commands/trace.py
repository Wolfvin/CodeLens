"""Trace command — Trace deep call chain from a symbol."""

from trace_engine import trace_symbol, MAX_CHAIN_RESULTS
from commands import register_command


def add_args(parser):
    """Add trace-specific arguments to the parser."""
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
    return trace_symbol(
        args.name, workspace,
        direction=args.direction,
        max_depth=args.depth,
        domain=args.domain,
        max_results=args.max_results,
        use_graph=use_graph,
    )


register_command("trace", "Trace deep call chain from a symbol", add_args, execute)
