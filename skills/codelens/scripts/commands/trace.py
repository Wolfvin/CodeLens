"""Trace command — Trace deep call chain from a symbol."""

from trace_engine import trace_symbol
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


def execute(args, workspace):
    return trace_symbol(
        args.name, workspace,
        direction=args.direction,
        max_depth=args.depth,
        domain=args.domain
    )


register_command("trace", "Trace deep call chain from a symbol", add_args, execute)
