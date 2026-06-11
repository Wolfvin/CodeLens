"""Circular command — Detect circular dependencies."""

from circular_engine import detect_circular
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--domain", choices=["backend", "imports", "css", "all"], default="all",
                        help="Which dependency types to check")


def execute(args, workspace):
    return detect_circular(workspace, domain=args.domain)


register_command("circular", "Detect circular dependencies", add_args, execute)
