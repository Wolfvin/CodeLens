"""Trace command — Trace deep call chain from a symbol."""

from trace_engine import trace_symbol, MAX_CHAIN_RESULTS
from commands import register_command


def add_args(parser):
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


def execute(args, workspace):
    return trace_symbol(
        args.name, workspace,
        direction=args.direction,
        max_depth=args.depth,
        domain=args.domain,
        max_results=args.max_results
    )


register_command("trace", "Trace deep call chain from a symbol", add_args, execute)
