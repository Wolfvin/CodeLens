"""Circular command — Detect circular dependencies."""

from circular_engine import detect_circular, MAX_CYCLES_PER_TYPE
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--domain", choices=["backend", "imports", "css", "all"], default="all",
                        help="Which dependency types to check")
    parser.add_argument("--max-cycles", type=int, default=MAX_CYCLES_PER_TYPE,
                        help=f"Maximum cycles to report per type (default: {MAX_CYCLES_PER_TYPE})")


def execute(args, workspace):
    return detect_circular(workspace, domain=args.domain, max_cycles=args.max_cycles)

# Issue #199: deprecated "circular" alias registration removed; this module is now an implementation module imported by the "deps" umbrella command.
