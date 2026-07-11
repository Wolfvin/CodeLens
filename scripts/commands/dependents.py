"""Dependents command — Module-level import tracking."""

import os
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
    # Auto-swap: if 'file' arg is a directory that looks like a workspace root,
    # treat it as the workspace instead. This handles the common pattern:
    #   codelens dependents /path/to/workspace
    # where the user passes workspace as the first positional arg.
    file_arg = args.file
    if file_arg and os.path.isdir(os.path.abspath(file_arg)) and args.workspace is None:
        workspace_markers = {'.codelens', 'package.json', 'Cargo.toml', 'pyproject.toml',
                            'go.mod', 'tsconfig.json'}
        if any(os.path.exists(os.path.join(os.path.abspath(file_arg), m)) for m in workspace_markers):
            args.workspace = file_arg
            workspace = os.path.abspath(file_arg)  # Update workspace param too
            args.file = None

    file_path = args.file

    if args.direction == "graph":
        return get_dependency_graph(workspace)
    elif args.direction == "dependencies":
        if file_path is None:
            return {"status": "error", "error": "No file specified. Usage: codelens dependents <file> [workspace]"}
        return get_dependencies(file_path, workspace, depth=args.depth)
    else:
        if file_path is None:
            return {"status": "error", "error": "No file specified. Usage: codelens dependents <file> [workspace]"}
        return get_dependents(file_path, workspace, depth=args.depth)

# Issue #199: deprecated "dependents" alias registration removed; this module is now an implementation module imported by the "deps" umbrella command.
