"""Dependents command — Module-level import tracking."""

from dependents_engine import get_dependents, get_dependencies, get_dependency_graph
from commands import register_command


def add_args(parser):
    parser.add_argument("file", help="File path to check")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--direction", choices=["dependents", "dependencies", "graph"],
                        default="dependents",
                        help="Show who imports this file, what this file imports, or full graph")
    parser.add_argument("--depth", type=int, default=3, help="Trace depth (default 3)")


def execute(args, workspace):
    if args.direction == "graph":
        return get_dependency_graph(workspace)
    elif args.direction == "dependencies":
        return get_dependencies(args.file, workspace, depth=args.depth)
    else:
        return get_dependents(args.file, workspace, depth=args.depth)


register_command("dependents", "Module-level import tracking", add_args, execute)
